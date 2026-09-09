"""Phase 25H — operator MT5 session execution (fresh evidence, immutability-safe)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.bidask_ingestion import ingest_bidask_parquet
from tradingbot.backtest.bidask_validation import (
    compute_spread_quality,
    validate_bidask_dataset,
    write_spread_quality_report,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    EconomicsProvenance,
    MappingStatus,
    audit_backtest_datasets,
    save_dataset_metadata,
)
from tradingbot.backtest.mt5_readonly_evidence import (
    ReadOnlyCollectionResult,
    collect_historical_ticks,
    collect_readonly_symbol_catalog,
    save_readonly_evidence,
    ticks_to_m5_bidask_bars,
)
from tradingbot.backtest.phase25g_run import verify_bidask_backtest_loading
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    SymbolSpecSnapshot,
    audit_from_operator_artifacts,
    build_equivalence_audit,
    write_equivalence_audit_report,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE25H_ARTIFACT_PREFIX = "phase25h"
STALE_EVIDENCE_NOTE = "stale_operator_evidence_2026-09-02"
FRESH_EVIDENCE_CLASS = "FRESH_LIVE_EVIDENCE"


@dataclass
class Phase25HReport:
    status: str = "DEFERRED"
    evidence_class: str = "DEFERRED"
    mt5_connected: bool = False
    mt5_started_by_script: bool = False
    bidask_dataset_created: bool = False
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    cost_completeness: str = CostCompleteness.UNKNOWN.value
    account_environment: str = ""
    server: str = ""
    broker: str = ""
    symbol_select_called: bool = False
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    immutability_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "phase": "25H",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": self.status,
            "evidence_class": self.evidence_class,
            "mt5_connected_read_only": self.mt5_connected,
            "mt5_started_by_script": self.mt5_started_by_script,
            "symbol_select_called": self.symbol_select_called,
            "bidask_dataset_created": self.bidask_dataset_created,
            "ev_eq_01": self.ev_eq_01,
            "cost_completeness": self.cost_completeness,
            "account_environment": self.account_environment,
            "server": self.server,
            "broker": self.broker,
            "immutability_ok": self.immutability_ok,
            "errors": self.errors,
            "artifacts": self.artifacts,
            "operator_note": "PHASE 25H DEFERRED — MT5 OPERATOR SESSION REQUIRED"
            if self.status == "DEFERRED"
            else "",
        }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_immutability_manifest(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Hash all existing backtest parquets — baseline for before/after checks."""
    root = Path(base_dir or Path.cwd())
    entries = audit_backtest_datasets(base_dir=root)
    datasets: dict[str, Any] = {}
    for e in entries:
        p = Path(e.path)
        if not p.is_file():
            continue
        datasets[p.name] = {
            "path": str(p.resolve()),
            "sha256": _sha256_file(p),
            "row_count": e.row_count,
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dataset_count": len(datasets),
        "datasets": datasets,
    }


def verify_immutability(
    before: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> tuple[bool, list[str]]:
    """Return True if all baseline parquets unchanged."""
    after = build_immutability_manifest(base_dir=base_dir)
    issues: list[str] = []
    before_ds = before.get("datasets") or {}
    after_ds = after.get("datasets") or {}
    for name, meta in before_ds.items():
        if name not in after_ds:
            issues.append(f"missing:{name}")
            continue
        if after_ds[name].get("sha256") != meta.get("sha256"):
            issues.append(f"mutated:{name}")
        if after_ds[name].get("row_count") != meta.get("row_count"):
            issues.append(f"row_count_changed:{name}")
    return len(issues) == 0, issues


def _resolve_bidask_target(root: Path) -> Path:
    """Versioned target — never overwrite existing dataset."""
    base = root / "data" / "backtest" / "XAUUSD_i_M5_bidask.parquet"
    if not base.is_file():
        return base
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / "data" / "backtest" / f"XAUUSD_i_M5_bidask_{ts}.parquet"


def _economics_from_catalog_spec(spec: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "contract_size": spec.get("trade_contract_size"),
        "point": spec.get("point"),
        "digits": spec.get("digits"),
        "tick_size": spec.get("trade_tick_size"),
        "tick_value": spec.get("trade_tick_value"),
        "tick_value_profit": spec.get("trade_tick_value_profit"),
        "tick_value_loss": spec.get("trade_tick_value_loss"),
        "volume_min": spec.get("volume_min"),
        "volume_max": spec.get("volume_max"),
        "volume_step": spec.get("volume_step"),
        "stops_level": spec.get("trade_stops_level"),
        "freeze_level": spec.get("trade_freeze_level"),
    }
    return {k: v for k, v in mapping.items() if v is not None}


def _swap_status_from_spec(spec: dict[str, Any]) -> str:
    if spec.get("swap_long") is not None or spec.get("swap_short") is not None:
        return "BROKER_RATE_ONLY"
    return "UNKNOWN"


def _build_bidask_metadata(
    *,
    validation_row_count: int,
    date_start: str | None,
    date_end: str | None,
    timezone: str,
    raw_evidence_path: str,
    catalog: ReadOnlyCollectionResult,
    collection_utc: str | None,
    target_path: Path,
) -> DatasetMetadata:
    xau_i = catalog.symbol_specs.get(PRIMARY_SYMBOL) or {}
    spec = dict(xau_i.get("spec") or {})
    econ = _economics_from_catalog_spec(spec)
    broker = "LiteFinance" if "LiteFinance" in (catalog.server or "") else catalog.server or None
    return DatasetMetadata(
        dataset_symbol=PRIMARY_SYMBOL,
        configured_instrument_symbol=PRIMARY_SYMBOL,
        mapping_status=MappingStatus.MATCH.value,
        economics_source=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
        economics_provenance={
            "source": FRESH_EVIDENCE_CLASS,
            "artifact": raw_evidence_path,
            "method": "mt5_copy_ticks_range_m5_aggregate",
            "stale_reference": STALE_EVIDENCE_NOTE,
        },
        timeframe="M5",
        spread_mode=SpreadMode.DATASET.value,
        spread_source="BID_ASK_OBSERVED",
        spread_status="OBSERVED",
        historical_bid_ask_available=True,
        broker=broker,
        server=catalog.server or None,
        account_environment=catalog.account_environment or None,
        evidence_timestamp=collection_utc,
        source_artifact=str(target_path),
        symbol_equivalence=EquivalenceConclusion.NOT_PROVEN.value,
        provenance_summary="FRESH LIVE MT5 tick bid/ask aggregated to M5 — OBSERVED_DATASET_SPREAD",
        datetime_range={
            "start": date_start,
            "end": date_end,
            "timezone": timezone,
            "row_count": validation_row_count,
        },
        commission_status="UNKNOWN",
        swap_status=_swap_status_from_spec(spec),
        slippage_status="UNKNOWN",
        cost_completeness=CostCompleteness.PARTIAL.value,
        **econ,
    )


def _catalog_snapshots(catalog: ReadOnlyCollectionResult) -> list[SymbolSpecSnapshot]:
    snaps: list[SymbolSpecSnapshot] = []
    for sym in ("XAUUSD", "XAUUSD_i"):
        block = catalog.symbol_specs.get(sym) or {}
        spec = dict(block.get("spec") or {})
        quote = block.get("quote") or {}
        if quote:
            spec.setdefault("bid", quote.get("bid"))
            spec.setdefault("ask", quote.get("ask"))
        snaps.append(
            SymbolSpecSnapshot(
                symbol=sym,
                exists=bool(block.get("exists")),
                visible=block.get("visible"),
                environment=catalog.account_environment,
                server=catalog.server,
                evidence_artifact=f"logs/{PHASE25H_ARTIFACT_PREFIX}_readonly_catalog.json",
                evidence_timestamp=catalog.collection_utc,
                spec=spec,
            )
        )
    return snaps


def run_phase25h_collection(
    base_dir: str | Path | None = None,
    *,
    tick_days: int = 3,
) -> Phase25HReport:
    """
    Phase 25H operator session — attach-only MT5, fresh evidence artifacts.

    Does NOT start MT5, bot, or send orders. Does NOT mutate existing parquets.
    """
    root = Path(base_dir or Path.cwd())
    report = Phase25HReport()
    report.mt5_started_by_script = False
    report.symbol_select_called = False

    before_manifest = build_immutability_manifest(root)
    manifest_path = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_immutability_before.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(before_manifest, indent=2), encoding="utf-8")
    report.artifacts.append(str(manifest_path))

    catalog = collect_readonly_symbol_catalog()
    cat_path = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_readonly_catalog.json"

    if not catalog.ok:
        report.errors.extend(catalog.errors)
        raw_path = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_bidask_collection_raw.json"
        raw = {
            "status": "DEFERRED",
            "evidence_class": "DEFERRED",
            "reason": catalog.errors,
            "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "method": "read-only attach-only; no symbol_select; no orders",
            "stale_reference": STALE_EVIDENCE_NOTE,
            "fresh_live_collected": False,
        }
        raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        report.artifacts.append(str(raw_path))

        stale_audits = audit_from_operator_artifacts(base_dir=root)
        stale_path = write_equivalence_audit_report(
            stale_audits,
            root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_symbol_equivalence_stale_ref.json",
        )
        not_proven_audit = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=False, environment=catalog.account_environment or "UNKNOWN"),
            SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, environment=catalog.account_environment or "UNKNOWN"),
        )
        eq_path = write_equivalence_audit_report(
            [not_proven_audit],
            root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_symbol_equivalence_audit.json",
        )
        report.ev_eq_01 = EquivalenceConclusion.NOT_PROVEN.value
        report.artifacts.extend([str(stale_path), str(eq_path)])
        report.status = "DEFERRED"
        report.evidence_class = "DEFERRED"
        report.immutability_ok, imm_issues = verify_immutability(before_manifest, base_dir=root)
        if not report.immutability_ok:
            report.errors.extend(imm_issues)
        _write_report(root, report)
        return report

    report.mt5_connected = True
    report.evidence_class = FRESH_EVIDENCE_CLASS
    report.account_environment = catalog.account_environment
    report.server = catalog.server
    report.broker = "LiteFinance" if "LiteFinance" in (catalog.server or "") else catalog.server
    save_readonly_evidence(catalog, cat_path)
    report.artifacts.append(str(cat_path))

    left, right = _catalog_snapshots(catalog)[:2]
    eq_audit = build_equivalence_audit(left, right, same_environment=True)
    eq_path = write_equivalence_audit_report(
        [eq_audit], root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_symbol_equivalence_audit.json"
    )
    report.ev_eq_01 = eq_audit.ev_eq_01
    report.artifacts.append(str(eq_path))

    ticks_df, tick_meta = collect_historical_ticks(PRIMARY_SYMBOL, days=tick_days)
    raw_ticks_path = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_ticks_raw.parquet"
    raw_json_path = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_bidask_collection_raw.json"

    raw_doc: dict[str, Any] = {
        "status": "COLLECTED" if tick_meta.get("ok") else "FAILED",
        "evidence_class": FRESH_EVIDENCE_CLASS if tick_meta.get("ok") else "PARTIAL",
        "collection_utc": tick_meta.get("collection_utc"),
        "symbol": PRIMARY_SYMBOL,
        "account_environment": catalog.account_environment,
        "server": catalog.server,
        "method": tick_meta.get("method"),
        "tick_meta": tick_meta,
        "raw_ticks_parquet": str(raw_ticks_path) if tick_meta.get("ok") else None,
        "fresh_live_collected": bool(tick_meta.get("ok")),
    }
    raw_json_path.write_text(json.dumps(raw_doc, indent=2), encoding="utf-8")
    report.artifacts.append(str(raw_json_path))

    if ticks_df is None or ticks_df.empty:
        report.errors.append(tick_meta.get("error", "no ticks"))
        report.status = "PARTIAL"
        report.immutability_ok, _ = verify_immutability(before_manifest, base_dir=root)
        _write_report(root, report)
        return report

    ticks_df.to_parquet(raw_ticks_path, index=False)
    report.artifacts.append(str(raw_ticks_path))

    bars = ticks_to_m5_bidask_bars(ticks_df)
    bars["spread"] = bars["ask"] - bars["bid"]
    validation = validate_bidask_dataset(bars)
    if not validation.ok:
        report.errors.append(f"validation_failed:{validation.errors}")
        report.status = "PARTIAL"
        report.immutability_ok, _ = verify_immutability(before_manifest, base_dir=root)
        _write_report(root, report)
        return report

    staging = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_M5_bidask_staging.parquet"
    bars.to_parquet(staging, index=True)
    target = _resolve_bidask_target(root)

    meta = _build_bidask_metadata(
        validation_row_count=validation.row_count,
        date_start=validation.date_start,
        date_end=validation.date_end,
        timezone=validation.timezone,
        raw_evidence_path=str(raw_json_path),
        catalog=catalog,
        collection_utc=tick_meta.get("collection_utc"),
        target_path=target,
    )

    ingest_bidask_parquet(staging, target, meta, copy=True)
    meta.spread_source = "BID_ASK_OBSERVED"
    save_dataset_metadata(target, meta)

    quality = compute_spread_quality(
        bars,
        dataset_path=target,
        symbol=PRIMARY_SYMBOL,
        source="mt5_copy_ticks_range",
    )
    qpayload = quality.to_dict()
    qpayload["spread_classification"] = "OBSERVED_DATASET_SPREAD"
    qpayload["evidence_class"] = FRESH_EVIDENCE_CLASS
    qpath = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_bidask_quality.json"
    qpath.write_text(json.dumps(qpayload, indent=2), encoding="utf-8")

    cfg = BacktestConfig(spread_mode="AUTO")
    cost_model = build_backtest_cost_model(cfg, frame=bars)
    report.cost_completeness = cost_model.completeness.value
    report.bidask_dataset_created = True
    report.status = "PASS"
    report.artifacts.extend([str(target), str(target.with_name(target.stem + ".metadata.json")), str(qpath)])

    report.immutability_ok, imm_issues = verify_immutability(before_manifest, base_dir=root)
    if not report.immutability_ok:
        report.errors.extend(imm_issues)
        report.status = "PARTIAL"

    after_manifest = build_immutability_manifest(root)
    after_path = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_immutability_after.json"
    after_path.write_text(json.dumps(after_manifest, indent=2), encoding="utf-8")
    report.artifacts.append(str(after_path))
    _write_report(root, report)
    return report


def _write_report(root: Path, report: Phase25HReport) -> Path:
    out = root / "logs" / f"{PHASE25H_ARTIFACT_PREFIX}_collection_report.json"
    payload = report.to_dict()
    if report.status == "DEFERRED":
        payload["operator_note"] = "PHASE 25H DEFERRED — MT5 OPERATOR SESSION REQUIRED"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report.artifacts.append(str(out))
    return out
