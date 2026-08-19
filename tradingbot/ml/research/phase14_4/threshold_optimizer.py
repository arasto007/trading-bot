"""Phase 14.4 — combined threshold optimization."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.confidence_optimizer import optimize_confidence_threshold
from tradingbot.ml.research.phase14_4.quality_optimizer import optimize_quality_threshold
from tradingbot.ml.research.phase14_4.config import RISK_CAP_GRID
from tradingbot.ml.research.phase14_4.pipeline_simulator import (
    PipelineThresholds,
    run_pipeline_records,
    trade_metrics_from_records,
)


def optimize_risk_caps(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    confidence_threshold: float = 0.55,
    quality_threshold: float = 0.65,
    quick: bool = False,
) -> dict[str, Any]:
    grid = RISK_CAP_GRID[:2] if quick else RISK_CAP_GRID
    rows: list[dict[str, Any]] = []

    for cap in grid:
        th = PipelineThresholds(
            confidence_threshold=confidence_threshold,
            quality_threshold=quality_threshold,
            max_risk_percent=cap,
        )
        records = run_pipeline_records(
            candles, dataset, symbol=symbol, timeframe=timeframe, seed=seed, thresholds=th, stride=5
        )
        metrics = trade_metrics_from_records(records)
        rows.append({"max_risk_percent": cap, **metrics})

    return {"phase": "14.4", "grid": list(grid), "results": rows}


def run_threshold_search(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quick: bool = False,
) -> dict[str, Any]:
    confidence = optimize_confidence_threshold(
        candles, dataset, symbol=symbol, timeframe=timeframe, seed=seed, quick=quick
    )
    best_conf = float(confidence["best"]["confidence_threshold"]) if confidence.get("best") else 0.55

    quality = optimize_quality_threshold(
        candles,
        dataset,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        confidence_threshold=best_conf,
        quick=quick,
    )
    best_qual = float(quality["best"]["quality_threshold"]) if quality.get("best") else 0.65

    risk = optimize_risk_caps(
        candles,
        dataset,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        confidence_threshold=best_conf,
        quality_threshold=best_qual,
        quick=quick,
    )

    return {
        "confidence": confidence,
        "quality": quality,
        "risk_caps": risk,
        "recommended": {
            "confidence_threshold": best_conf,
            "quality_threshold": best_qual,
            "max_risk_percent": 0.50,
        },
    }
