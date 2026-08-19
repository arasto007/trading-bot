"""Phase 13.6 — regime threshold grid search."""

from __future__ import annotations

from itertools import product
from typing import Any

from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    OptimizerConfig,
    RegimeThresholdParams,
    composite_score,
)

TREND_ADX_GRID: tuple[float, ...] = (20.0, 25.0, 30.0)
RANGE_ADX_GRID: tuple[float, ...] = (15.0, 20.0, 25.0)
ATR_LOW_VOL_GRID: tuple[float, ...] = (20.0, 30.0, 40.0)


def optimize_regime_thresholds(
    merged,
    candles,
    *,
    range_buy_threshold: float = 0.55,
    range_sell_threshold: float = 0.45,
    trend_ml_threshold: float = 0.55,
    policy: str = "A",
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest

    trend_grid = (25.0,) if quick else TREND_ADX_GRID
    range_grid = (20.0,) if quick else RANGE_ADX_GRID
    atr_grid = (30.0,) if quick else ATR_LOW_VOL_GRID
    rows: list[dict[str, Any]] = []
    for adx_trend, adx_range, atr_low in product(trend_grid, range_grid, atr_grid):
        params = RegimeThresholdParams(
            adx_trend_min=adx_trend,
            adx_range_max=adx_range,
            atr_low_vol=atr_low,
        )
        cfg = OptimizerConfig(
            regime_params=params,
            range_buy_threshold=range_buy_threshold,
            range_sell_threshold=range_sell_threshold,
            trend_ml_threshold=trend_ml_threshold,
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
                "adx_trend_min": adx_trend,
                "adx_range_max": adx_range,
                "atr_low_vol": atr_low,
                "metrics": m,
                "score": composite_score(m),
            }
        )

    ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
    best = ranked[0] if ranked else {}
    return {
        "grid": {
            "trend_adx": list(trend_grid),
            "range_adx": list(range_grid),
            "atr_low_vol": list(atr_grid),
            "quick": quick,
        },
        "ranking": ranked[:15],
        "best_params": {
            "adx_trend_min": best.get("adx_trend_min", 25.0),
            "adx_range_max": best.get("adx_range_max", 20.0),
            "atr_low_vol": best.get("atr_low_vol", 30.0),
        },
        "best_score": best.get("score", 0.0),
    }
