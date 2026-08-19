"""Phase 13.6 — ML threshold grid search."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    OptimizerConfig,
    RegimeThresholdParams,
    composite_score,
    ml_threshold_pair,
)

ML_THRESHOLDS: tuple[float, ...] = (0.45, 0.50, 0.55, 0.60, 0.65)


def optimize_thresholds(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    regime_params: RegimeThresholdParams | None = None,
    policy: str = "A",
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest

    params = regime_params or RegimeThresholdParams()
    rows: list[dict[str, Any]] = []
    grid = (0.55,) if quick else ML_THRESHOLDS

    for threshold in grid:
        buy_t, sell_t = ml_threshold_pair(threshold)
        cfg = OptimizerConfig(
            regime_params=params,
            range_buy_threshold=buy_t,
            range_sell_threshold=sell_t,
            trend_ml_threshold=threshold,
            policy=policy,
            seed=seed,
            symbol=symbol,
        )
        bt = run_optimized_backtest(
            merged, candles, config=cfg, base_dir=base_dir, engine_cache=engine_cache
        )
        m = bt["metrics"]
        rows.append(
            {
                "threshold": threshold,
                "range_buy": buy_t,
                "range_sell": sell_t,
                "trend_ml": threshold,
                "metrics": m,
                "score": composite_score(m),
            }
        )

    ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
    return {
        "candidates": list(grid),
        "ranking": ranked,
        "best_threshold": ranked[0]["threshold"] if ranked else 0.55,
        "ranking_criteria": ["walk_forward_pf", "expectancy", "overfit_penalty"],
    }
