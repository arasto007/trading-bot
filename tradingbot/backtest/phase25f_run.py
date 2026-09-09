"""Phase 25F offline orchestration — equivalence audit, bid/ask capture, ingestion."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingbot.backtest.bidask_ingestion import ingest_bidask_parquet
from tradingbot.backtest.bidask_validation import (
    compute_spread_quality,
    validate_bidask_dataset,
    write_spread_quality_report,
)
from tradingbot.backtest.cost_model import SpreadMode
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    EconomicsProvenance,
    LITEFINANCE_DEMO_EVIDENCE,
    LITEFINANCE_EVIDENCE_TIMESTAMP,
    MappingStatus,
    observed_litefinance_xauusd_i_economics,
    save_dataset_metadata,
)
from tradingbot.backtest.mt5_readonly_evidence import (
    collect_historical_ticks,
    collect_readonly_symbol_catalog,
    save_readonly_evidence,
    ticks_to_m5_bidask_bars,
)
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    audit_from_operator_artifacts,
    write_equivalence_audit_report,
)
from tradingbot.config.live import PRIMARY_SYMBOL


@dataclass
class Phase25FReport:
    mt5_catalog_collected: bool = False
    mt5_ticks_collected: bool = False
    bidask_dataset_created: bool = False
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


def _build_bidask_metadata(
    *,
    validation_row_count: int,
    date_start: str | None,
    date_end: str | None,
    timezone: str,
    tick_meta_path: str,
    server: str | None,
    account_environment: str | None,
    collection_utc: str | None,
) -> DatasetMetadata:
    econ = observed_litefinance_xauusd_i_economics()
    meta = DatasetMetadata(
        dataset_symbol=PRIMARY_SYMBOL,
        configured_instrument_symbol=PRIMARY_SYMBOL,
        mapping_status=MappingStatus.MATCH.value,
        economics_source=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
        economics_provenance={
            "source": EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
            "artifact": tick_meta_path,
            "method": "mt5_copy_ticks_range_m5_aggregate",
        },
        timeframe="M5",
        spread_mode=SpreadMode.DATASET.value,
        spread_source="BID_ASK_OBSERVED",
        historical_bid_ask_available=True,
        broker="LiteFinance",
        server=server,
        account_environment=account_environment,
        evidence_timestamp=collection_utc or LITEFINANCE_EVIDENCE_TIMESTAMP,
        source_artifact=LITEFINANCE_DEMO_EVIDENCE,
        symbol_equivalence="MATCHING_LABEL_ONLY",
        provenance_summary="Observed MT5 tick bid/ask aggregated to M5 — DATASET spread, not PROXY",
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
    )
    return meta


def run_offline_equivalence_audit(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Build EV-EQ-01 audit from existing operator artifacts (no MT5)."""
    audits = audit_from_operator_artifacts(base_dir=base_dir)
    out = write_equivalence_audit_report(
        audits,
        Path(base_dir or Path.cwd()) / "logs" / "phase25f_symbol_equivalence_audit.json",
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    return {"path": str(out), "ev_eq_01_overall": payload.get("ev_eq_01_overall")}


def run_mt5_readonly_collection(
    base_dir: str | Path | None = None,
    *,
    attempt_ticks: bool = True,
    tick_days: int = 7,
) -> dict[str, Any]:
    """Attempt read-only MT5 catalog + tick collection. Failures are non-fatal."""
    root = Path(base_dir or Path.cwd())
    summary: dict[str, Any] = {"catalog": None, "ticks": None, "ingestion": None}

    catalog = collect_readonly_symbol_catalog()
    cat_path = root / "logs" / "phase25f_readonly_catalog.json"
    if catalog.ok:
        save_readonly_evidence(catalog, cat_path)
        summary["catalog"] = {"ok": True, "path": str(cat_path)}
    else:
        summary["catalog"] = {"ok": False, "errors": catalog.errors}
        return summary

    if not attempt_ticks:
        return summary

    ticks_df, tick_meta = collect_historical_ticks(PRIMARY_SYMBOL, days=tick_days)
    tick_meta_path = root / "logs" / "phase25f_tick_collection.json"
    tick_meta_path.write_text(json.dumps(tick_meta, indent=2), encoding="utf-8")
    summary["ticks"] = tick_meta

    if ticks_df is None or ticks_df.empty:
        return summary

    bars = ticks_to_m5_bidask_bars(ticks_df)
    validation = validate_bidask_dataset(bars)
    if not validation.ok:
        summary["ingestion"] = {"ok": False, "validation": validation.to_dict()}
        return summary

    staging = root / "logs" / "phase25f_XAUUSD_i_M5_bidask_staging.parquet"
    bars.to_parquet(staging, index=True)
    target = root / "data" / "backtest" / "XAUUSD_i_M5_bidask.parquet"

    meta = _build_bidask_metadata(
        validation_row_count=validation.row_count,
        date_start=validation.date_start,
        date_end=validation.date_end,
        timezone=validation.timezone,
        tick_meta_path=str(tick_meta_path),
        server=catalog.server or None,
        account_environment=catalog.account_environment or None,
        collection_utc=tick_meta.get("collection_utc"),
    )

    ingest_bidask_parquet(staging, target, meta, copy=True)
    meta.spread_source = "BID_ASK_OBSERVED"
    save_dataset_metadata(target, meta)

    quality = compute_spread_quality(bars, dataset_path=target, symbol=PRIMARY_SYMBOL)
    qpath = write_spread_quality_report(quality, root / "logs" / "phase25f_bidask_quality.json")

    summary["ingestion"] = {
        "ok": True,
        "dataset": str(target),
        "sidecar": str(target.with_name(target.stem + ".metadata.json")),
        "quality_report": str(qpath),
        "row_count": len(bars),
    }
    return summary
