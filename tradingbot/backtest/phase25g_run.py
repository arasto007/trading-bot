"""Phase 25G — operator MT5 session orchestration and bid/ask dataset population."""

from __future__ import annotations

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
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    EconomicsProvenance,
    MappingStatus,
    observed_litefinance_xauusd_i_economics,
    save_dataset_metadata,
)
from tradingbot.backtest.mt5_readonly_evidence import (
    ReadOnlyCollectionResult,
    collect_historical_ticks,
    collect_readonly_symbol_catalog,
    save_readonly_evidence,
    ticks_to_m5_bidask_bars,
)
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    SymbolSpecSnapshot,
    build_equivalence_audit,
    write_equivalence_audit_report,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.config.live import PRIMARY_SYMBOL


@dataclass
class Phase25GReport:
    status: str = "DEFERRED"
    mt5_connected: bool = False
    mt5_started_by_script: bool = False
    bidask_dataset_created: bool = False
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    cost_completeness: str = CostCompleteness.UNKNOWN.value
    account_environment: str = ""
    server: str = ""
    broker: str = ""
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": self.status,
            "mt5_connected_read_only": self.mt5_connected,
            "mt5_started_by_script": self.mt5_started_by_script,
            "bidask_dataset_created": self.bidask_dataset_created,
            "ev_eq_01": self.ev_eq_01,
            "cost_completeness": self.cost_completeness,
            "account_environment": self.account_environment,
            "server": self.server,
            "broker": self.broker,
            "errors": self.errors,
            "artifacts": self.artifacts,
        }


def _catalog_to_spec_snapshots(catalog: ReadOnlyCollectionResult) -> list[SymbolSpecSnapshot]:
    snaps: list[SymbolSpecSnapshot] = []
    for sym in ("XAUUSD", "XAUUSD_i"):
        block = catalog.symbol_specs.get(sym) or {}
        snaps.append(
            SymbolSpecSnapshot(
                symbol=sym,
                exists=bool(block.get("exists")),
                visible=block.get("visible"),
                environment=catalog.account_environment,
                server=catalog.server,
                evidence_artifact="logs/phase25g_readonly_catalog.json",
                evidence_timestamp=catalog.collection_utc,
                spec=dict(block.get("spec") or {}),
            )
        )
    return snaps


def _build_equivalence_from_live_catalog(catalog: ReadOnlyCollectionResult, root: Path) -> dict[str, Any]:
    left = next((s for s in _catalog_to_spec_snapshots(catalog) if s.symbol == "XAUUSD"), None)
    right = next((s for s in _catalog_to_spec_snapshots(catalog) if s.symbol == "XAUUSD_i"), None)
    if left is None or right is None:
        return {"ev_eq_01_overall": EquivalenceConclusion.NOT_PROVEN.value, "environment_audits": []}
    audit = build_equivalence_audit(left, right, same_environment=True)
    out = write_equivalence_audit_report([audit], root / "logs" / "phase25g_symbol_equivalence_audit.json")
    payload = json.loads(out.read_text(encoding="utf-8"))
    return payload


def _build_bidask_metadata(
    *,
    validation_row_count: int,
    date_start: str | None,
    date_end: str | None,
    timezone: str,
    raw_evidence_path: str,
    catalog: ReadOnlyCollectionResult,
    collection_utc: str | None,
) -> DatasetMetadata:
    econ = observed_litefinance_xauusd_i_economics()
    broker = "LiteFinance" if "LiteFinance" in (catalog.server or "") else None
    return DatasetMetadata(
        dataset_symbol=PRIMARY_SYMBOL,
        configured_instrument_symbol=PRIMARY_SYMBOL,
        mapping_status=MappingStatus.MATCH.value,
        economics_source=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
        economics_provenance={
            "source": EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
            "artifact": raw_evidence_path,
            "method": "mt5_copy_ticks_range_m5_aggregate",
        },
        timeframe="M5",
        spread_mode=SpreadMode.DATASET.value,
        spread_source="BID_ASK_OBSERVED",
        historical_bid_ask_available=True,
        broker=broker,
        server=catalog.server or None,
        account_environment=catalog.account_environment or None,
        evidence_timestamp=collection_utc,
        source_artifact=raw_evidence_path,
        symbol_equivalence=EquivalenceConclusion.NOT_PROVEN.value,
        provenance_summary="Observed MT5 tick bid/ask aggregated to M5 — OBSERVED_DATASET_SPREAD",
        datetime_range={
            "start": date_start,
            "end": date_end,
            "timezone": timezone,
            "row_count": validation_row_count,
        },
        contract_size=econ.get("contract_size"),
        point=econ.get("point"),
        digits=econ.get("digits"),
        tick_size=econ.get("tick_size"),
        tick_value=econ.get("tick_value"),
        tick_value_profit=econ.get("tick_value_profit"),
        tick_value_loss=econ.get("tick_value_loss"),
        volume_min=econ.get("volume_min"),
        volume_max=econ.get("volume_max"),
        volume_step=econ.get("volume_step"),
        stops_level=econ.get("stops_level"),
        freeze_level=econ.get("freeze_level"),
        commission_status="UNKNOWN",
        swap_status="UNKNOWN",
        slippage_status="UNKNOWN",
        cost_completeness=CostCompleteness.PARTIAL.value,
    )


def run_phase25g_collection(
    base_dir: str | Path | None = None,
    *,
    tick_days: int = 3,
) -> Phase25GReport:
    """
    Phase 25G operator evidence collection — read-only MT5, single connection attempt path.

    Does not start MT5, bot, or send orders. Does not mutate existing parquets.
    """
    root = Path(base_dir or Path.cwd())
    report = Phase25GReport()
    report.mt5_started_by_script = False

    catalog = collect_readonly_symbol_catalog()
    cat_path = root / "logs" / "phase25g_readonly_catalog.json"

    if not catalog.ok:
        report.errors.extend(catalog.errors)
        raw_path = root / "logs" / "phase25g_bidask_collection_raw.json"
        raw = {
            "status": "DEFERRED",
            "reason": catalog.errors,
            "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "method": "read-only; no symbol_select; no orders",
        }
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        report.artifacts.append(str(raw_path))

        from tradingbot.backtest.symbol_equivalence import audit_from_operator_artifacts

        audits = audit_from_operator_artifacts(base_dir=root)
        eq_path = write_equivalence_audit_report(
            audits, root / "logs" / "phase25g_symbol_equivalence_audit.json"
        )
        report.ev_eq_01 = EquivalenceConclusion.NOT_PROVEN.value
        report.artifacts.append(str(eq_path))
        report.status = "DEFERRED"
        _write_report(root, report)
        return report

    report.mt5_connected = True
    report.account_environment = catalog.account_environment
    report.server = catalog.server
    report.broker = "LiteFinance" if "LiteFinance" in catalog.server else catalog.server
    save_readonly_evidence(catalog, cat_path)
    report.artifacts.append(str(cat_path))

    eq_payload = _build_equivalence_from_live_catalog(catalog, root)
    report.ev_eq_01 = eq_payload.get("ev_eq_01_overall", EquivalenceConclusion.NOT_PROVEN.value)
    report.artifacts.append(str(root / "logs" / "phase25g_symbol_equivalence_audit.json"))

    ticks_df, tick_meta = collect_historical_ticks(PRIMARY_SYMBOL, days=tick_days)
    raw_path = root / "logs" / "phase25g_bidask_collection_raw.json"
    raw_staging = root / "logs" / "phase25g_ticks_raw.parquet"

    raw_doc: dict[str, Any] = {
        "status": "COLLECTED" if tick_meta.get("ok") else "FAILED",
        "collection_utc": tick_meta.get("collection_utc"),
        "symbol": PRIMARY_SYMBOL,
        "account_environment": catalog.account_environment,
        "server": catalog.server,
        "method": tick_meta.get("method"),
        "tick_meta": tick_meta,
        "raw_ticks_parquet": str(raw_staging) if tick_meta.get("ok") else None,
    }
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw_doc, indent=2), encoding="utf-8")
    report.artifacts.append(str(raw_path))

    if ticks_df is None or ticks_df.empty:
        report.errors.append(tick_meta.get("error", "no ticks"))
        report.status = "PARTIAL"
        _write_report(root, report)
        return report

    ticks_df.to_parquet(raw_staging, index=False)
    bars = ticks_to_m5_bidask_bars(ticks_df)
    validation = validate_bidask_dataset(bars)
    if not validation.ok:
        report.errors.append(f"validation_failed:{validation.errors}")
        report.status = "PARTIAL"
        _write_report(root, report)
        return report

    staging = root / "logs" / "phase25g_XAUUSD_i_M5_bidask_staging.parquet"
    bars.to_parquet(staging, index=True)
    target = root / "data" / "backtest" / "XAUUSD_i_M5_bidask.parquet"

    meta = _build_bidask_metadata(
        validation_row_count=validation.row_count,
        date_start=validation.date_start,
        date_end=validation.date_end,
        timezone=validation.timezone,
        raw_evidence_path=str(raw_path),
        catalog=catalog,
        collection_utc=tick_meta.get("collection_utc"),
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
    qpath = write_spread_quality_report(quality, root / "logs" / "phase25g_bidask_quality.json")
    report.artifacts.extend([str(target), str(target.with_name(target.stem + ".metadata.json")), str(qpath)])

    cfg = BacktestConfig(spread_mode="AUTO")
    cost_model = build_backtest_cost_model(cfg, frame=bars)
    report.cost_completeness = cost_model.completeness.value
    report.bidask_dataset_created = True
    report.status = "PASS"
    _write_report(root, report)
    return report


def _write_report(root: Path, report: Phase25GReport) -> Path:
    out = root / "logs" / "phase25g_collection_report.json"
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    report.artifacts.append(str(out))
    return out


def verify_bidask_backtest_loading(parquet_path: str | Path) -> dict[str, Any]:
    """Offline verification that bid/ask parquet loads with DATASET spread mode."""
    path = Path(parquet_path)
    if not path.is_file():
        return {"ok": False, "error": "dataset_missing"}
    df = pd.read_parquet(path)
    cfg = BacktestConfig(spread_mode="AUTO")
    ohlc = df.drop(columns=[c for c in df.columns if str(c).lower() in ("bid", "ask")], errors="ignore")
    proxy_model = build_backtest_cost_model(cfg, frame=ohlc)
    dataset_model = build_backtest_cost_model(cfg, frame=df)
    return {
        "ok": True,
        "dataset_spread_mode": dataset_model.spread_mode.value,
        "ohlc_spread_mode": proxy_model.spread_mode.value,
        "dataset_completeness": dataset_model.completeness.value,
        "cost_adjusted_allowed": dataset_model.completeness == CostCompleteness.COMPLETE,
    }
