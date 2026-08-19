"""Phase 15A — preparation orchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase15a.checklist import build_production_checklist
from tradingbot.ml.phase15a.config import phase15a_final_report_path
from tradingbot.ml.phase15a.engine_discovery import discover_engines
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.health_check import run_health_checks
from tradingbot.ml.phase15a.pipeline_validator import validate_pipeline
from tradingbot.ml.phase15a.report_generator import write_phase15a_reports
from tradingbot.ml.phase15a.trend_bundle import freeze_trend_bundle, load_trend_bundle, validate_trend_checksum

logger = logging.getLogger(__name__)


@dataclass
class Phase15AResult:
    status: str
    recommendation: str
    architecture_readiness_score: float
    production_readiness_score: float
    integration_readiness: str
    blockers: list[dict[str, str]]
    reports_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15A",
            "status": self.status,
            "recommendation": self.recommendation,
            "architecture_readiness_score": self.architecture_readiness_score,
            "production_readiness_score": self.production_readiness_score,
            "integration_readiness": self.integration_readiness,
            "blockers": self.blockers,
            "reports_dir": self.reports_dir,
        }


def _score_architecture(health: dict, discovery: dict, pipeline: dict, checklist: dict) -> float:
    points = 0.0
    if health.get("passes"):
        points += 2.5
    if discovery.get("active"):
        points += 1.5
    if pipeline.get("passes"):
        points += 2.0
    if checklist.get("preparation_complete"):
        points += 2.0
    if pipeline.get("interfaces", {}).get("passes"):
        points += 2.0
    return round(min(10.0, points), 1)


def _score_production(checklist: dict, health: dict) -> float:
    completed = len(checklist.get("completed", []))
    total = len(checklist.get("items", []))
    base = (completed / max(total, 1)) * 6.0
    if health.get("phase9_9", {}).get("passes"):
        base += 2.0
    if health.get("trend_rf_v40", {}).get("passes"):
        base += 2.0
    return round(min(10.0, base), 1)


def run_phase15a_preparation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    freeze_if_missing: bool = True,
    sample_bars: int = 5,
) -> Phase15AResult:
    """Execute Phase 15A preparation — no kernel or execution changes."""
    logger.info("Phase 15A preparation starting")

    if freeze_if_missing:
        chk = validate_trend_checksum(base_dir=base_dir)
        if not chk.get("valid"):
            logger.info("Freezing trend RF bundle")
            freeze_trend_bundle(symbol=symbol, timeframe=timeframe, seed=seed, base_dir=base_dir)

    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=freeze_if_missing, symbol=symbol)
    checksum = validate_trend_checksum(base_dir=base_dir)
    registry = EngineRegistry.build_default(
        base_dir=str(base_dir) if base_dir else None,
        build_trend_if_missing=freeze_if_missing,
        symbol=symbol,
    )
    health = run_health_checks(base_dir=base_dir, registry=registry)
    discovery = discover_engines(base_dir=base_dir, persist_manifests=True)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        pipeline = {"passes": False, "error": "candles_unavailable", "phase": "15A"}
    else:
        pipeline = validate_pipeline(
            candles, dataset, registry=registry, symbol=symbol, timeframe=timeframe, sample_bars=sample_bars,
        )

    checklist = build_production_checklist(
        health=health,
        discovery=discovery,
        pipeline=pipeline,
        interfaces_ok=pipeline.get("interfaces", {}).get("passes", False),
        base_dir=base_dir,
    )

    arch_score = _score_architecture(health, discovery, pipeline, checklist)
    prod_score = _score_production(checklist, health)

    blockers: list[dict[str, str]] = []
    if not checksum.get("valid"):
        blockers.append({"id": "B-TREND", "detail": "Trend bundle checksum invalid or missing"})
    if not pipeline.get("passes"):
        blockers.append({"id": "B-PIPE", "detail": "ML pipeline validation failed"})
    blockers.append({"id": "B-KERNEL", "detail": "TradingKernel integration not started (expected for 15A)"})
    blockers.append({"id": "B-WF", "detail": "WF robustness below gate — unresolved from Phase 14.10"})

    prep_ok = checklist.get("ready_for_phase15b", False) and checksum.get("valid")
    recommendation = "READY_FOR_PHASE15B" if prep_ok else "NEEDS_REVIEW"
    status = "PASS" if prep_ok and health.get("passes") else "NEEDS_REVIEW"

    final_report = {
        "phase": "15A",
        "status": status,
        "recommendation": recommendation,
        "architecture_readiness_score": arch_score,
        "production_readiness_score": prod_score,
        "integration_readiness": "PREPARED_NOT_WIRED",
        "trend_bundle_frozen": bool(checksum.get("valid")),
        "engines_registered": registry.list_ids(),
        "health_status": health.get("status"),
        "pipeline_passes": pipeline.get("passes"),
        "blockers_before_15b": [b for b in blockers if b["id"] != "B-KERNEL"],
        "blockers_before_live": blockers,
        "checklist": {
            "completed": checklist.get("completed"),
            "missing": checklist.get("missing"),
        },
    }

    reports_path = write_phase15a_reports(
        base_dir=base_dir,
        health=health,
        discovery=discovery,
        pipeline=pipeline,
        registry=registry,
        bundle=bundle,
        checksum=checksum,
        final_report=final_report,
    )

    logger.info("Phase 15A complete: %s -> %s", status, reports_path)
    return Phase15AResult(
        status=status,
        recommendation=recommendation,
        architecture_readiness_score=arch_score,
        production_readiness_score=prod_score,
        integration_readiness="PREPARED_NOT_WIRED",
        blockers=blockers,
        reports_dir=str(reports_path),
    )
