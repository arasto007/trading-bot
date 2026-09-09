"""Phase 25J — operator MT5 evidence completion + cost-evidence closure."""

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
    PHASE25I_AUDIT_JSON,
    ReportEvidenceClass,
    audit_commission_evidence,
    audit_slippage_evidence,
    audit_spread_evidence,
    audit_swap_evidence,
    build_upgrade_requirements,
    classify_economics_provenance,
    dataset_eligibility_for_row,
    load_all_operator_deals,
    run_phase25i_audit,
)
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets, load_dataset_metadata, save_dataset_metadata
from tradingbot.backtest.mt5_readonly_evidence import (
    collect_historical_ticks,
    collect_readonly_symbol_catalog,
    save_readonly_evidence,
    ticks_to_m5_bidask_bars,
)
from tradingbot.backtest.phase25h_run import (
    FRESH_EVIDENCE_CLASS,
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

PHASE25J_PREFIX = "phase25j"
PHASE25J_AUDIT_JSON = "logs/phase25j_cost_evidence_audit.json"
PHASE25J_REPORT_MD = "logs/phase25j_cost_evidence_report.md"
BASELINE_MANIFEST = "logs/phase25h_immutability_before.json"


@dataclass
class Phase25JReport:
    status: str = "PASS_WITH_DEFERRAL"
    mt5_connected: bool = False
    mt5_started_by_script: bool = False
    symbol_select_called: bool = False
    evidence_class: str = ReportEvidenceClass.DEFERRED.value
    bidask_dataset_created: bool = False
    bidask_quality_ok: bool = False
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    cost_completeness: str = CostCompleteness.UNKNOWN.value
    account_environment: str = ""
    server: str = ""
    broker: str = ""
    fresh_catalog_collected: bool = False
    immutability_ok: bool = True
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "phase": "25J",
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
            "account_environment": self.account_environment,
            "server": self.server,
            "broker": self.broker,
            "immutability_ok": self.immutability_ok,
            "errors": self.errors,
            "artifacts": self.artifacts,
            "operator_note": "PHASE 25J DEFERRED — MT5 OPERATOR SESSION REQUIRED"
            if self.status in ("DEFERRED", "PASS_WITH_DEFERRAL") and not self.mt5_connected
            else "",
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


def run_phase25j_mt5_collection(
    base_dir: str | Path | None = None,
    *,
    tick_days: int = 3,
) -> Phase25JReport:
    """Attach-only MT5 collection — phase25j artifacts. Does NOT start MT5."""
    root = Path(base_dir or Path.cwd())
    report = Phase25JReport()
    report.mt5_started_by_script = False
    report.symbol_select_called = False

    before = _baseline_manifest(root)
    j_before = root / "logs" / f"{PHASE25J_PREFIX}_immutability_before.json"
    _write_json(j_before, before)
    report.artifacts.append(str(j_before))

    catalog = collect_readonly_symbol_catalog()
    cat_path = root / "logs" / f"{PHASE25J_PREFIX}_readonly_catalog.json"
    raw_json = root / "logs" / f"{PHASE25J_PREFIX}_bidask_collection_raw.json"

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
                "fresh_live_collected": False,
                "operator_note": "DEFERRED — NO IPC CONNECTION",
            },
        )
        report.artifacts.append(str(raw_json))

        stale = write_equivalence_audit_report(
            audit_from_operator_artifacts(base_dir=root),
            root / "logs" / f"{PHASE25J_PREFIX}_symbol_equivalence_stale_ref.json",
        )
        eq = write_equivalence_audit_report(
            [
                build_equivalence_audit(
                    SymbolSpecSnapshot(symbol="XAUUSD", exists=False, environment="UNKNOWN"),
                    SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, environment="UNKNOWN"),
                )
            ],
            root / "logs" / f"{PHASE25J_PREFIX}_symbol_equivalence_audit.json",
        )
        report.ev_eq_01 = EquivalenceConclusion.NOT_PROVEN.value
        report.artifacts.extend([str(stale), str(eq)])
        report.status = "PASS_WITH_DEFERRAL"
        report.evidence_class = ReportEvidenceClass.DEFERRED.value
        report.immutability_ok, imm = verify_immutability(before, base_dir=root)
        if not report.immutability_ok:
            report.errors.extend(imm)
        coll = root / "logs" / f"{PHASE25J_PREFIX}_collection_report.json"
        _write_json(coll, report.to_dict())
        report.artifacts.append(str(coll))
        return report

    report.mt5_connected = True
    report.fresh_catalog_collected = True
    report.evidence_class = FRESH_EVIDENCE_CLASS
    report.account_environment = catalog.account_environment
    report.server = catalog.server
    report.broker = "LiteFinance" if "LiteFinance" in (catalog.server or "") else catalog.server or ""
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
        [eq_audit], root / "logs" / f"{PHASE25J_PREFIX}_symbol_equivalence_audit.json"
    )
    report.ev_eq_01 = eq_audit.ev_eq_01
    report.artifacts.append(str(eq_path))

    ticks_df, tick_meta = collect_historical_ticks(PRIMARY_SYMBOL, days=tick_days)
    raw_ticks = root / "logs" / f"{PHASE25J_PREFIX}_ticks_raw.parquet"
    _write_json(
        raw_json,
        {
            "status": "COLLECTED" if tick_meta.get("ok") else "FAILED",
            "evidence_class": FRESH_EVIDENCE_CLASS if tick_meta.get("ok") else ReportEvidenceClass.DEFERRED.value,
            "collection_utc": tick_meta.get("collection_utc"),
            "symbol": PRIMARY_SYMBOL,
            "account_environment": catalog.account_environment,
            "server": catalog.server,
            "method": tick_meta.get("method"),
            "tick_meta": tick_meta,
            "raw_ticks_parquet": str(raw_ticks) if tick_meta.get("ok") else None,
            "fresh_live_collected": bool(tick_meta.get("ok")),
            "stale_reference": STALE_EVIDENCE_NOTE,
        },
    )
    report.artifacts.append(str(raw_json))

    if ticks_df is None or ticks_df.empty:
        report.errors.append(tick_meta.get("error", "no ticks"))
        report.status = "PARTIAL"
        report.immutability_ok, _ = verify_immutability(before, base_dir=root)
        coll = root / "logs" / f"{PHASE25J_PREFIX}_collection_report.json"
        _write_json(coll, report.to_dict())
        report.artifacts.append(str(coll))
        return report

    ticks_df.to_parquet(raw_ticks, index=False)
    report.artifacts.append(str(raw_ticks))

    bars = ticks_to_m5_bidask_bars(ticks_df)
    bars["spread"] = bars["ask"] - bars["bid"]
    validation = validate_bidask_dataset(bars)
    qpath = root / "logs" / f"{PHASE25J_PREFIX}_bidask_quality.json"
    quality = compute_spread_quality(
        bars,
        dataset_path=None,
        symbol=PRIMARY_SYMBOL,
        source="mt5_copy_ticks_range",
    )
    qpayload = quality.to_dict()
    qpayload["validation_ok"] = validation.ok
    qpayload["validation_errors"] = list(validation.errors)
    qpayload["spread_classification"] = "OBSERVED_DATASET_SPREAD"
    qpayload["evidence_class"] = FRESH_EVIDENCE_CLASS
    _write_json(qpath, qpayload)
    report.artifacts.append(str(qpath))
    report.bidask_quality_ok = validation.ok

    if not validation.ok:
        report.errors.append(f"validation_failed:{validation.errors}")
        report.status = "PARTIAL"
        report.immutability_ok, _ = verify_immutability(before, base_dir=root)
        coll = root / "logs" / f"{PHASE25J_PREFIX}_collection_report.json"
        _write_json(coll, report.to_dict())
        report.artifacts.append(str(coll))
        return report

    staging = root / "logs" / f"{PHASE25J_PREFIX}_M5_bidask_staging.parquet"
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
    meta.economics_provenance["phase"] = "25J"
    meta.economics_provenance["artifact_prefix"] = PHASE25J_PREFIX
    ingest_bidask_parquet(staging, target, meta, copy=True)
    meta.spread_source = "OBSERVED_DATASET_SPREAD"
    save_dataset_metadata(target, meta)

    cfg = BacktestConfig(spread_mode="AUTO")
    cost_model = build_backtest_cost_model(cfg, frame=bars)
    report.cost_completeness = cost_model.completeness.value
    report.bidask_dataset_created = True
    report.status = "PASS"

    report.immutability_ok, imm = verify_immutability(before, base_dir=root)
    if not report.immutability_ok:
        report.errors.extend(imm)
        report.status = "PARTIAL"

    after = build_immutability_manifest(root)
    after_path = root / "logs" / f"{PHASE25J_PREFIX}_immutability_after.json"
    _write_json(after_path, after)
    report.artifacts.extend([str(target), str(target.with_name(target.stem + ".metadata.json")), str(after_path)])

    coll = root / "logs" / f"{PHASE25J_PREFIX}_collection_report.json"
    _write_json(coll, report.to_dict())
    report.artifacts.append(str(coll))
    return report


def build_dataset_cost_matrix(
    base_dir: Path,
    *,
    collection: Phase25JReport | None = None,
) -> list[dict[str, Any]]:
    """Full dataset-level cost matrix including fresh bid/ask if present."""
    entries = audit_backtest_datasets(base_dir=base_dir)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        row = dataset_eligibility_for_row(entry)
        meta = load_dataset_metadata(entry.path)
        env = meta.account_environment if meta else None
        broker = meta.broker if meta else None
        server = meta.server if meta else None
        econ_class = classify_economics_provenance(
            dataset_symbol=row.symbol,
            economics_source=entry.economics_provenance,
            evidence_timestamp=meta.evidence_timestamp if meta else None,
        )
        if entry.spread_mode == SpreadMode.DATASET.value and collection and collection.fresh_catalog_collected:
            econ_class = FRESH_EVIDENCE_CLASS
        rows.append(
            {
                "dataset": row.filename,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "environment": env or "UNKNOWN",
                "broker": broker or "UNKNOWN",
                "server": server or "UNKNOWN",
                "economics_provenance": econ_class,
                "spread": row.spread,
                "commission": row.commission,
                "swap": row.swap,
                "slippage": row.slippage,
                "overall_completeness": row.overall_completeness,
                "cost_adjusted_metrics_eligible": row.cost_adjusted_metrics_allowed,
                "research_backtest_eligible": row.research_backtest_eligible,
                "cost_aware_backtest_eligible": row.cost_aware_backtest_eligible,
            }
        )
    return rows


def run_phase25j_closure_audit(
    base_dir: str | Path | None = None,
    *,
    collection: Phase25JReport | None = None,
) -> dict[str, Any]:
    """Offline cost-evidence closure — integrates Phase 25I + Phase 25J collection status."""
    root = Path(base_dir or Path.cwd())
    if collection is None:
        coll_path = root / "logs" / f"{PHASE25J_PREFIX}_collection_report.json"
        if coll_path.is_file():
            raw = json.loads(coll_path.read_text(encoding="utf-8-sig"))
            collection = Phase25JReport(
                status=raw.get("status", "PASS_WITH_DEFERRAL"),
                mt5_connected=bool(raw.get("mt5_connected_read_only")),
                evidence_class=raw.get("evidence_class", ReportEvidenceClass.DEFERRED.value),
                bidask_dataset_created=bool(raw.get("bidask_dataset_created")),
                ev_eq_01=raw.get("ev_eq_01", EquivalenceConclusion.NOT_PROVEN.value),
                cost_completeness=raw.get("cost_completeness", CostCompleteness.UNKNOWN.value),
                account_environment=raw.get("account_environment", ""),
                server=raw.get("server", ""),
                broker=raw.get("broker", ""),
                fresh_catalog_collected=bool(raw.get("fresh_catalog_collected")),
            )

    i_report = run_phase25i_audit(base_dir=root)
    deals, specs = load_all_operator_deals(root)
    matrix = build_dataset_cost_matrix(root, collection=collection)

    before = _baseline_manifest(root)
    imm_ok, imm_issues = verify_immutability(before, base_dir=root)

    fresh_note = FRESH_EVIDENCE_CLASS if collection and collection.mt5_connected else ReportEvidenceClass.DEFERRED.value
    stale = [
        "operator_broker_evidence @ 2026-09-02 (preserved — STALE_OPERATOR_EVIDENCE)",
    ]
    if not (collection and collection.mt5_connected):
        stale.append("Phase 25J live MT5 collection DEFERRED — NO IPC CONNECTION")

    return {
        "schema_version": 1,
        "phase": "25J",
        "status": collection.status if collection and collection.mt5_connected else "PASS_WITH_DEFERRAL",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mt5_collection": collection.to_dict() if collection else {"status": "NOT_RUN"},
        "fresh_live_evidence": fresh_note,
        "cost_inventory": [c.to_dict() for c in i_report.cost_inventory],
        "commission": audit_commission_evidence(deals).to_dict(),
        "swap": audit_swap_evidence(deals, specs).to_dict(),
        "slippage": audit_slippage_evidence(deals).to_dict(),
        "spread": audit_spread_evidence(audit_backtest_datasets(base_dir=root)).to_dict(),
        "ev_eq_01": collection.ev_eq_01 if collection else i_report.ev_eq_01,
        "cost_completeness_matrix": matrix,
        "cost_adjusted_metrics_any_dataset": any(r["cost_adjusted_metrics_eligible"] for r in matrix),
        "upgrade_requirements": build_upgrade_requirements(),
        "explicit_unknowns": i_report.explicit_unknowns,
        "stale_evidence": stale,
        "phase25i_reference": str(root / PHASE25I_AUDIT_JSON),
        "immutability_ok": imm_ok,
        "immutability_issues": imm_issues,
        "credentials_exposed": False,
        "safety": {
            **i_report.safety,
            "mt5_started_by_script": False,
            "mt5_attached_read_only": bool(collection and collection.mt5_connected),
        },
    }


def render_phase25j_report_md(audit: dict[str, Any]) -> str:
    mt5 = audit.get("mt5_collection") or {}
    lines = [
        "# Phase 25J Cost Evidence Closure Report",
        "",
        f"Generated: {audit.get('generated_at')}",
        f"Status: **{audit.get('status')}**",
        f"Fresh live evidence: **{audit.get('fresh_live_evidence')}**",
        "",
        "## MT5 collection",
        "",
        f"- Connected: {mt5.get('mt5_connected_read_only', False)}",
        f"- Bid/ask dataset created: {mt5.get('bidask_dataset_created', False)}",
        f"- EV-EQ-01: {audit.get('ev_eq_01')}",
        "",
        "## Cost components",
        "",
        "| Component | Status |",
        "|-----------|--------|",
        f"| Commission | {audit.get('commission', {}).get('status', 'UNKNOWN')} |",
        f"| Swap | {audit.get('swap', {}).get('status', 'UNKNOWN')} |",
        f"| Slippage | {audit.get('slippage', {}).get('status', 'UNKNOWN')} |",
        f"| Spread | {audit.get('spread', {}).get('status', 'PROXY')} |",
        "",
        f"**cost_adjusted_metrics (any dataset):** {audit.get('cost_adjusted_metrics_any_dataset', False)}",
        "",
        "## Dataset matrix summary",
        "",
    ]
    matrix = audit.get("cost_completeness_matrix") or []
    proxy_n = sum(1 for r in matrix if r.get("spread") == SpreadMode.PROXY.value)
    dataset_n = sum(1 for r in matrix if r.get("spread") == SpreadMode.DATASET.value)
    lines.append(f"- PROXY spread datasets: {proxy_n}")
    lines.append(f"- DATASET spread datasets: {dataset_n}")
    lines.extend(["", "## Stale / deferred", ""])
    for s in audit.get("stale_evidence") or []:
        lines.append(f"- {s}")
    lines.extend(["", "## Safety", ""])
    for k, v in (audit.get("safety") or {}).items():
        if isinstance(v, bool):
            lines.append(f"- {k}: {'NO' if v is False else 'YES'}")
        else:
            lines.append(f"- {k}: {v}")
    return "\n".join(lines) + "\n"


def write_phase25j_artifacts(base_dir: str | Path | None, audit: dict[str, Any]) -> list[str]:
    root = Path(base_dir or Path.cwd())
    paths: list[str] = []
    j = root / PHASE25J_AUDIT_JSON
    _write_json(j, audit)
    paths.append(str(j))
    md = root / PHASE25J_REPORT_MD
    md.write_text(render_phase25j_report_md(audit), encoding="utf-8")
    paths.append(str(md))
    return paths


def run_phase25j_collection(base_dir: str | Path | None = None) -> Phase25JReport:
    """
    Phase 25J entry point — MT5 attach attempt + cost-evidence closure.

    PATH A: MT5 running → fresh evidence + optional bid/ask dataset.
    PATH B: MT5 offline → PASS_WITH_DEFERRAL + offline closure audit.
    """
    root = Path(base_dir or Path.cwd())
    collection = run_phase25j_mt5_collection(base_dir=root)
    audit = run_phase25j_closure_audit(base_dir=root, collection=collection)
    if collection.mt5_connected and collection.bidask_dataset_created:
        audit["status"] = collection.status
    elif not collection.mt5_connected:
        audit["status"] = "PASS_WITH_DEFERRAL"
    artifact_paths = write_phase25j_artifacts(root, audit)
    collection.artifacts.extend(artifact_paths)
    return collection
