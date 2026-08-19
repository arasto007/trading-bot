"""Phase 14.4 — quality threshold grid search."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.config import QUALITY_GRID
from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_4.pipeline_simulator import (
    PipelineThresholds,
    build_quality_adapter,
    load_production_engines,
    run_pipeline_records,
    trade_metrics_from_records,
)


def optimize_quality_threshold(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    confidence_threshold: float = 0.55,
    max_risk_percent: float = 0.50,
    quick: bool = False,
) -> dict[str, Any]:
    grid = QUALITY_GRID[:2] if quick else QUALITY_GRID
    rows: list[dict[str, Any]] = []
    unified = build_unified_frame(candles, dataset)
    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

    for threshold in grid:
        th = PipelineThresholds(
            confidence_threshold=confidence_threshold,
            quality_threshold=threshold,
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
        blocked = sum(1 for r in records if not r["allowed"] and r["raw_signal"] in ("BUY", "SELL"))
        accepted = metrics["trades"]
        avg_q = sum(r["quality_score"] for r in records if r["allowed"]) / max(accepted, 1)
        rows.append(
            {
                "quality_threshold": threshold,
                "accepted_trades": accepted,
                "blocked_trades": blocked,
                "mean_quality_accepted": round(avg_q, 4),
                **metrics,
            }
        )

    ranked = sorted(rows, key=lambda r: (r["profit_factor"], r["accepted_trades"]), reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i

    return {
        "phase": "14.4",
        "grid": list(grid),
        "results": rows,
        "best": ranked[0] if ranked else None,
        "ranking": ranked,
    }
