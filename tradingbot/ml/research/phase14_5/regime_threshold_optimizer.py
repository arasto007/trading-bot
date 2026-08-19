"""Phase 14.5 — per-regime confidence threshold optimization."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase14_5.config import (
    DEFAULT_MAX_RISK_PERCENT,
    DEFAULT_QUALITY_THRESHOLD,
    GRID_STRIDE,
    REGIME_CONFIDENCE_GRID,
)
from tradingbot.ml.research.phase14_5.pipeline_runner import RegimeConfidencePolicy, run_pipeline_with_policy, sweep_metrics
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame


def optimize_regime_thresholds(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quick: bool = False,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
) -> dict[str, Any]:
    grid = REGIME_CONFIDENCE_GRID[:2] if quick else REGIME_CONFIDENCE_GRID
    stride = GRID_STRIDE
    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

    per_regime: dict[str, dict[str, Any]] = {}
    for regime in ("RANGE", "TREND"):
        best_row: dict[str, Any] | None = None
        for th in grid:
            policy = RegimeConfidencePolicy(
                thresholds={
                    "RANGE": th if regime == "RANGE" else 0.35,
                    "TREND": th if regime == "TREND" else 0.35,
                    "HIGH_VOLATILITY": 1.0,
                    "NO_TRADE": 1.0,
                }
            )
            records = run_pipeline_with_policy(
                candles,
                dataset,
                regime_policy=policy,
                quality_threshold=DEFAULT_QUALITY_THRESHOLD,
                max_risk_percent=DEFAULT_MAX_RISK_PERCENT,
                symbol=symbol,
                timeframe=timeframe,
                seed=seed,
                stride=stride,
                range_engine=range_engine,
                trend_engine=trend_engine,
                unified=unified,
            )
            subset = [r for r in records if r["regime"] == regime]
            metrics = sweep_metrics(subset, stride=stride)
            row = {"threshold": th, **metrics}
            if best_row is None or row["expectancy"] > best_row["expectancy"]:
                best_row = row
        per_regime[regime] = best_row or {"threshold": 0.55}

    policy = {
        "RANGE": float(per_regime["RANGE"]["threshold"]),
        "TREND": float(per_regime["TREND"]["threshold"]),
        "HIGH_VOLATILITY": 1.0,
        "NO_TRADE": 1.0,
    }

    final_records = run_pipeline_with_policy(
        candles,
        dataset,
        regime_policy=RegimeConfidencePolicy(thresholds=policy),
        quality_threshold=DEFAULT_QUALITY_THRESHOLD,
        max_risk_percent=DEFAULT_MAX_RISK_PERCENT,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    final_metrics = sweep_metrics(final_records, stride=stride)

    return {
        "phase": "14.5",
        "regime_policy": policy,
        "per_regime_search": per_regime,
        "combined_metrics": final_metrics,
        "adaptive": True,
    }
