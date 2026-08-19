"""Phase 14.4 — confidence threshold grid search."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.config import CONFIDENCE_GRID, MIN_TRADES_PASS
from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_4.pipeline_simulator import (
    PipelineThresholds,
    build_quality_adapter,
    load_production_engines,
    run_pipeline_records,
    trade_metrics_from_records,
)


def optimize_confidence_threshold(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quality_threshold: float = 0.65,
    max_risk_percent: float = 0.50,
    quick: bool = False,
) -> dict[str, Any]:
    grid = CONFIDENCE_GRID[:2] if quick else CONFIDENCE_GRID
    rows: list[dict[str, Any]] = []
    unified = build_unified_frame(candles, dataset)
    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

    for threshold in grid:
        th = PipelineThresholds(
            confidence_threshold=threshold,
            quality_threshold=quality_threshold,
            max_risk_percent=max_risk_percent,
        )
        adapter, _, _ = build_quality_adapter(
            candles,
            symbol=symbol,
            seed=seed,
            thresholds=th,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        records = run_pipeline_records(
            candles,
            dataset,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            thresholds=th,
            adapter=adapter,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=unified,
            stride=5,
        )
        metrics = trade_metrics_from_records(records)
        effective_trades = metrics["trades"] * max(1, 5)  # stride=5 in grid search
        rejected = effective_trades < MIN_TRADES_PASS
        rows.append(
            {
                "confidence_threshold": threshold,
                **metrics,
                "effective_trades_est": int(effective_trades),
                "rejected": rejected,
                "rejection_reason": "trades_below_300" if rejected else None,
            }
        )

    valid = [r for r in rows if not r["rejected"]]
    ranked = sorted(
        valid,
        key=lambda r: (r["profit_factor"], r["expectancy"], r["trades"]),
        reverse=True,
    )
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i

    return {
        "phase": "14.4",
        "grid": list(grid),
        "min_trades": MIN_TRADES_PASS,
        "results": rows,
        "best": ranked[0] if ranked else None,
        "ranking": ranked,
    }
