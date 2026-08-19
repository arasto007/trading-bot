"""Phase 14.5 — confidence threshold sweep."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase14_5.config import (
    CONFIDENCE_GRID,
    DEFAULT_MAX_RISK_PERCENT,
    DEFAULT_QUALITY_THRESHOLD,
    GRID_STRIDE,
    MIN_TRADE_FLOOR,
)
from tradingbot.ml.research.phase14_5.pipeline_runner import run_pipeline_with_policy, sweep_metrics
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame


def run_confidence_sweep(
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
    grid = CONFIDENCE_GRID[:2] if quick else CONFIDENCE_GRID
    stride = GRID_STRIDE
    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    rows: list[dict[str, Any]] = []

    for threshold in grid:
        records = run_pipeline_with_policy(
            candles,
            dataset,
            confidence_threshold=threshold,
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
        metrics = sweep_metrics(records, stride=stride)
        rejected = metrics["effective_trades_est"] < MIN_TRADE_FLOOR
        rows.append(
            {
                "confidence_threshold": threshold,
                **metrics,
                "rejected": rejected,
                "rejection_reason": "trades_below_300" if rejected else None,
            }
        )

    valid = [r for r in rows if not r["rejected"]]
    return {
        "phase": "14.5",
        "grid": list(grid),
        "stride": stride,
        "min_trade_floor": MIN_TRADE_FLOOR,
        "results": rows,
        "valid_count": len(valid),
        "ranking": sorted(valid, key=lambda r: (r["expectancy"], r["profit_factor"]), reverse=True),
    }
