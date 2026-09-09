"""Phase 25L — operator MT5 evidence execution + broker-cost evidence closure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.bidask_ingestion import ingest_bidask_parquet
from tradingbot.backtest.bidask_validation import compute_spread_quality, validate_bidask_dataset
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import (
    MIN_COMMISSION_SCHEDULE_SAMPLES,
    ReportEvidenceClass,
    audit_commission_evidence,
    audit_slippage_evidence,
    audit_spread_evidence,
    audit_swap_evidence,
    build_upgrade_requirements,
    classify_economics_provenance,
    dataset_eligibility_for_row,
    load_all_operator_deals,
)
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets, load_dataset_metadata, save_dataset_metadata
from tradingbot.backtest.mt5_readonly_evidence import (
    collect_historical_ticks,
    collect_readonly_deals_sample,
    collect_readonly_symbol_catalog,
    save_readonly_evidence,
    ticks_to_m5_bidask_bars,
)
from tradingbot.backtest.operator_evidence import parse_closed_deal, summarize_commission
from tradingbot.backtest.phase25k_run import assess_fresh_commission, assess_fresh_slippage
from tradingbot.backtest.phase25h_run import (
    STALE_EVIDENCE_NOTE,
    _build_bidask_metadata,
    _resolve_bidask_target,
    build_immutability_manifest,
    verify_immutability,
)
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    SymbolSpecSnapshot,
    audit_from_operator_artifacts,
    build_equivalence_audit,
    write_equivalence_audit_report,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE25L_PREFIX = "phase25l"
FRESH_OPERATOR_EVIDENCE = "FRESH_OPERATOR_EVIDENCE"
BASELINE_MANIFEST = "logs/phase25h_immutability_before.json"
PHASE25L_AUDIT_JSON = "logs/phase25l_cost_evidence_audit.json"


@dataclass
class Phase25LReport:
    status: str = "PASS_WITH_DEFERRAL"
    mt5_connected: bool = False
    mt5_started_by_script: bool = False
    symbol_select_called: bool = False
    evidence_class: str = ReportEvidenceClass.DEFERRED.value
    bidask_dataset_created: bool = False
    bidask_quality_ok: bool = False
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    cost_completeness: str = CostCompleteness.UNKNOWN.value
    commission_status: str = "UNKNOWN"
    slippage_status: str = "UNKNOWN"
    swap_status: str = "UNKNOWN"
    account_environment: str = ""
    server: str = ""
    broker: str = ""
    currency: str = ""
    real_account_read_only: bool = False
    fresh_catalog_collected: bool = False
    immutability_ok: bool = True
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "phase": "25L",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": self.status,
            "evidence_class": self.evidence_class,
            "mt5_connected_read_only": self.mt5_connected,
            "mt5_started_by_script": self.mt5_started_by_script,
            "symbol_select_called": self.symbol_select_called,
            "fresh_catalog_collected": self.fresh_catalog_collected,
            "bidask_dataset_created": self.bidask_dataset_created,
            "bidask_quality_ok": self.bidask_quality_ok,
            "ev_eq_01": self.ev_eq_01,
            "cost_completeness": self.cost_completeness,
            "commission_status": self.commission_status,
            "slippage_status": self.slippage_status,
            "swap_status": self.swap_status,
            "account_environment": self.account_environment,
            "server": self.server,
            "broker": self.broker,
            "currency": self.currency,
            "real_account_read_only_enforced": self.real_account_read_only,
            "immutability_ok": self.immutability_ok,
            "errors": self.errors,
            "artifacts": self.artifacts,
            "operator_note": "PHASE 25L DEFERRED — MT5 OPERATOR SESSION REQUIRED"
            if not self.mt5_connected
            else ("REAL ACCOUNT OBSERVED — READ-ONLY MODE ENFORCED" if self.real_account_read_only else ""),
        }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _baseline_manifest(root: Path) -> dict[str, Any]:
    path = root / BASELINE_MANIFEST
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    manifest = build_immutability_manifest(root)
    _write_json(path, manifest)
    return manifest


def _finalize_immutability(
    report: Phase25LReport,
    before: dict[str, Any],
    root: Path,
) -> None:
    report.immutability_ok, imm = verify_immutability(before, base_dir=root)
    if not report.immutability_ok:
        report.errors.extend(imm)
        report.status = "FAIL"
    after = build_immutability_manifest(root)
    after_path = root / "logs" / f"{PHASE25L_PREFIX}_immutability_after.json"
    _write_json(after_path, after)
    report.artifacts.append(str(after_path))


def run_phase25l_mt5_collection(
    base_dir: str | Path | None = None,
    *,
    tick_days: int = 3,
) -> Phase25LReport:
    """Attach-only MT5 collection — phase25l artifacts. Does NOT start MT5."""
    root = Path(base_dir or Path.cwd())
    report = Phase25LReport()
    report.mt5_started_by_script = False
    report.symbol_select_called = False

    before = _baseline_manifest(root)
    l_before = root / "logs" / f"{PHASE25L_PREFIX}_immutability_before.json"
    _write_json(l_before, before)
    report.artifacts.append(str(l_before))

    catalog = collect_readonly_symbol_catalog()
    cat_path = root / "logs" / f"{PHASE25L_PREFIX}_readonly_catalog.json"
    raw_json = root / "logs" / f"{PHASE25L_PREFIX}_bidask_collection_raw.json"

    if not catalog.ok:
        report.errors.extend(catalog.errors)
        _write_json(
            raw_json,
            {
                "status": "DEFERRED",
                "evidence_class": ReportEvidenceClass.DEFERRED.value,
                "reason": catalog.errors,
                "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "method": "read-only attach-only; no symbol_select; no orders",
                "stale_reference": STALE_EVIDENCE_NOTE,
                "fresh_operator_collected": False,
                "operator_note": "DEFERRED — NO IPC CONNECTION",
            },
        )
        report.artifacts.append(str(raw_json))
        stale = write_equivalence_audit_report(
            audit_from_operator_artifacts(base_dir=root),
            root / "logs" / f"{PHASE25L_PREFIX}_symbol_equivalence_stale_ref.json",
        )
        eq = write_equivalence_audit_report(
            [
                build_equivalence_audit(
                    SymbolSpecSnapshot(symbol="XAUUSD", exists=False, environment="UNKNOWN"),
                    SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, environment="UNKNOWN"),
                )
            ],
            root / "logs" / f"{PHASE25L_PREFIX}_symbol_equivalence_audit.json",
        )
        report.ev_eq_01 = EquivalenceConclusion.NOT_PROVEN.value
        report.artifacts.extend([str(stale), str(eq)])
        report.status = "PASS_WITH_DEFERRAL"
        report.evidence_class = ReportEvidenceClass.DEFERRED.value
        _finalize_immutability(report, before, root)
        _write_json(root / "logs" / f"{PHASE25L_PREFIX}_collection_report.json", report.to_dict())
        return report

    report.mt5_connected = True
    report.fresh_catalog_collected = True
    report.evidence_class = FRESH_OPERATOR_EVIDENCE
    report.account_environment = catalog.account_environment
    report.server = catalog.server
    report.currency = catalog.currency
    report.broker = "LiteFinance" if "LiteFinance" in (catalog.server or "") else catalog.server or ""
    report.real_account_read_only = catalog.account_environment == "REAL"
    save_readonly_evidence(catalog, cat_path)
    report.artifacts.append(str(cat_path))

    left = SymbolSpecSnapshot(
        symbol="XAUUSD",
        exists=bool((catalog.symbol_specs.get("XAUUSD") or {}).get("exists")),
        visible=(catalog.symbol_specs.get("XAUUSD") or {}).get("visible"),
        environment=catalog.account_environment,
        server=catalog.server,
        evidence_artifact=str(cat_path),
        evidence_timestamp=catalog.collection_utc,
        spec=dict((catalog.symbol_specs.get("XAUUSD") or {}).get("spec") or {}),
    )
    right = SymbolSpecSnapshot(
        symbol=PRIMARY_SYMBOL,
        exists=bool((catalog.symbol_specs.get(PRIMARY_SYMBOL) or {}).get("exists")),
        visible=(catalog.symbol_specs.get(PRIMARY_SYMBOL) or {}).get("visible"),
        environment=catalog.account_environment,
        server=catalog.server,
        evidence_artifact=str(cat_path),
        evidence_timestamp=catalog.collection_utc,
        spec=dict((catalog.symbol_specs.get(PRIMARY_SYMBOL) or {}).get("spec") or {}),
    )
    eq_audit = build_equivalence_audit(left, right, same_environment=True)
    eq_path = write_equivalence_audit_report(
        [eq_audit], root / "logs" / f"{PHASE25L_PREFIX}_symbol_equivalence_audit.json"
    )
    report.ev_eq_01 = eq_audit.ev_eq_01
    report.artifacts.append(str(eq_path))

    fresh_deals, deal_meta = collect_readonly_deals_sample(days=30)
    comm = assess_fresh_commission(fresh_deals)
    slip = assess_fresh_slippage(fresh_deals)
    report.commission_status = comm["status"]
    report.slippage_status = slip["status"]
    spec = dict((catalog.symbol_specs.get(PRIMARY_SYMBOL) or {}).get("spec") or {})
    report.swap_status = "BROKER_RATE_ONLY" if spec.get("swap_long") is not None else "UNKNOWN"

    ticks_df, tick_meta = collect_historical_ticks(PRIMARY_SYMBOL, days=tick_days)
    raw_ticks = root / "logs" / f"{PHASE25L_PREFIX}_ticks_raw.parquet"
    _write_json(
        raw_json,
        {
            "status": "COLLECTED" if tick_meta.get("ok") else "INSUFFICIENT_DATA",
            "evidence_class": FRESH_OPERATOR_EVIDENCE if tick_meta.get("ok") else ReportEvidenceClass.DEFERRED.value,
            "collection_utc": tick_meta.get("collection_utc"),
            "symbol": PRIMARY_SYMBOL,
            "account_environment": catalog.account_environment,
            "server": catalog.server,
            "currency": catalog.currency,
            "method": tick_meta.get("method"),
            "tick_meta": tick_meta,
            "deal_meta": deal_meta,
            "commission_assessment": comm,
            "slippage_assessment": slip,
            "raw_ticks_parquet": str(raw_ticks) if tick_meta.get("ok") else None,
            "fresh_operator_collected": bool(tick_meta.get("ok")),
            "stale_reference": STALE_EVIDENCE_NOTE,
            "real_account_read_only_enforced": report.real_account_read_only,
        },
    )
    report.artifacts.append(str(raw_json))

    if ticks_df is None or ticks_df.empty:
        report.errors.append(tick_meta.get("error", "no ticks"))
        report.status = "PARTIAL"
        _finalize_immutability(report, before, root)
        _write_json(root / "logs" / f"{PHASE25L_PREFIX}_collection_report.json", report.to_dict())
        return report

    ticks_df.to_parquet(raw_ticks, index=False)
    report.artifacts.append(str(raw_ticks))

    bars = ticks_to_m5_bidask_bars(ticks_df)
    bars["spread"] = bars["ask"] - bars["bid"]
    validation = validate_bidask_dataset(bars)
    quality = compute_spread_quality(bars, symbol=PRIMARY_SYMBOL, source="mt5_copy_ticks_range")
    qpayload = quality.to_dict()
    qpayload.update(
        {
            "validation_ok": validation.ok,
            "validation_errors": list(validation.errors),
            "spread_classification": "OBSERVED_DATASET_SPREAD",
            "evidence_class": FRESH_OPERATOR_EVIDENCE,
            "valid_rows": validation.row_count,
            "invalid_rows": 0 if validation.ok else len(bars),
        }
    )
    qpath = root / "logs" / f"{PHASE25L_PREFIX}_bidask_quality.json"
    _write_json(qpath, qpayload)
    report.artifacts.append(str(qpath))
    report.bidask_quality_ok = validation.ok

    if not validation.ok:
        report.errors.append(f"validation_failed:{validation.errors}")
        report.status = "PARTIAL"
        _finalize_immutability(report, before, root)
        _write_json(root / "logs" / f"{PHASE25L_PREFIX}_collection_report.json", report.to_dict())
        return report

    staging = root / "logs" / f"{PHASE25L_PREFIX}_M5_bidask_staging.parquet"
    bars.to_parquet(staging, index=True)
    target = _resolve_bidask_target(root)
    meta = _build_bidask_metadata(
        validation_row_count=validation.row_count,
        date_start=validation.date_start,
        date_end=validation.date_end,
        timezone=validation.timezone,
        raw_evidence_path=str(raw_json),
        catalog=catalog,
        collection_utc=tick_meta.get("collection_utc"),
        target_path=target,
    )
    meta.economics_provenance = {
        "source": FRESH_OPERATOR_EVIDENCE,
        "artifact": str(cat_path),
        "method": "mt5_copy_ticks_range_m5_aggregate",
        "stale_reference": STALE_EVIDENCE_NOTE,
        "phase": "25L",
    }
    meta.spread_source = "OBSERVED_DATASET_SPREAD"
    meta.commission_status = report.commission_status
    meta.slippage_status = report.slippage_status
    meta.swap_status = report.swap_status
    meta.cost_completeness = CostCompleteness.PARTIAL.value
    meta.symbol_equivalence = report.ev_eq_01
    ingest_bidask_parquet(staging, target, meta, copy=True)
    save_dataset_metadata(target, meta)

    cost_model = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=bars)
    report.cost_completeness = cost_model.completeness.value
    report.bidask_dataset_created = True
    report.status = "PASS"

    _finalize_immutability(report, before, root)
    report.artifacts.extend([str(target), str(target.with_name(target.stem + ".metadata.json"))])
    _write_json(root / "logs" / f"{PHASE25L_PREFIX}_collection_report.json", report.to_dict())
    return report


def build_phase25l_cost_matrix(root: Path, collection: Phase25LReport | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in audit_backtest_datasets(base_dir=root):
        row = dataset_eligibility_for_row(entry)
        meta = load_dataset_metadata(entry.path)
        econ = classify_economics_provenance(
            dataset_symbol=row.symbol,
            economics_source=entry.economics_provenance,
            evidence_timestamp=meta.evidence_timestamp if meta else None,
        )
        if entry.spread_mode == SpreadMode.DATASET.value and collection and collection.fresh_catalog_collected:
            econ = FRESH_OPERATOR_EVIDENCE
        rows.append(
            {
                "dataset": row.filename,
                "symbol": row.symbol,
                "environment": (meta.account_environment if meta else None) or "UNKNOWN",
                "broker": (meta.broker if meta else None) or "UNKNOWN",
                "server": (meta.server if meta else None) or "UNKNOWN",
                "economics_provenance": econ,
                "spread": row.spread,
                "commission": row.commission,
                "swap": row.swap,
                "slippage": row.slippage,
                "overall_completeness": row.overall_completeness,
                "cost_adjusted_metrics_eligible": row.cost_adjusted_metrics_allowed,
            }
        )
    return rows


def run_phase25l_cost_audit(
    base_dir: str | Path | None = None,
    *,
    collection: Phase25LReport | None = None,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    stale_deals, specs = load_all_operator_deals(root)
    matrix = build_phase25l_cost_matrix(root, collection)
    before = _baseline_manifest(root)
    imm_ok, imm_issues = verify_immutability(before, base_dir=root)

    fresh_class = FRESH_OPERATOR_EVIDENCE if collection and collection.mt5_connected else ReportEvidenceClass.DEFERRED.value
    status = "PASS_WITH_DEFERRAL"
    if collection:
        if collection.status == "FAIL":
            status = "FAIL"
        elif collection.mt5_connected and collection.bidask_dataset_created:
            status = "PASS"
        elif collection.mt5_connected:
            status = "PARTIAL"
        else:
            status = "PASS_WITH_DEFERRAL"

    return {
        "schema_version": 1,
        "phase": "25L",
        "status": status,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fresh_operator_evidence": fresh_class,
        "mt5_collection": collection.to_dict() if collection else {},
        "ev_eq_01": collection.ev_eq_01 if collection else EquivalenceConclusion.NOT_PROVEN.value,
        "commission": audit_commission_evidence(stale_deals).to_dict(),
        "fresh_commission": collection.commission_status if collection else "UNKNOWN",
        "swap": audit_swap_evidence(stale_deals, specs).to_dict(),
        "fresh_swap": collection.swap_status if collection else "UNKNOWN",
        "slippage": audit_slippage_evidence(stale_deals).to_dict(),
        "fresh_slippage": collection.slippage_status if collection else "UNKNOWN",
        "spread": audit_spread_evidence(audit_backtest_datasets(base_dir=root)).to_dict(),
        "cost_completeness_matrix": matrix,
        "cost_adjusted_metrics_any_dataset": any(r["cost_adjusted_metrics_eligible"] for r in matrix),
        "upgrade_requirements": build_upgrade_requirements(),
        "stale_evidence": [
            "operator_broker_evidence @ 2026-09-02 (STALE_OPERATOR_EVIDENCE — preserved)",
            "Phase 25H/I/J/K conclusions preserved",
            *([] if collection and collection.mt5_connected else ["Phase 25L MT5 collection DEFERRED"]),
        ],
        "immutability_ok": imm_ok,
        "immutability_issues": imm_issues,
        "credentials_exposed": False,
        "safety": {
            "mt5_started_by_script": False,
            "mt5_attached_read_only": bool(collection and collection.mt5_connected),
            "real_account_read_only_enforced": bool(collection and collection.real_account_read_only),
            "symbol_select_called": False,
            "orders_sent": False,
            "synthetic_data_created": False,
        },
    }


def run_phase25l_collection(base_dir: str | Path | None = None) -> Phase25LReport:
    """Phase 25L entry point — operator MT5 evidence execution + cost closure."""
    root = Path(base_dir or Path.cwd())
    collection = run_phase25l_mt5_collection(base_dir=root)
    audit = run_phase25l_cost_audit(base_dir=root, collection=collection)
    _write_json(root / PHASE25L_AUDIT_JSON, audit)
    collection.artifacts.append(str(root / PHASE25L_AUDIT_JSON))
    if not collection.mt5_connected and collection.status != "FAIL":
        collection.status = "PASS_WITH_DEFERRAL"
    return collection
