"""Phase 13.9 — unified router backtest using preserved features."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range
from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.research.regime_router.trend_engine_adapter import TrendEngineAdapter
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams, baseline_phase135_config
from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest


class UnifiedRangeWrapper:
    """Maps phase99_* columns for frozen Phase 9.9 range adapter (read-only)."""

    def __init__(self, inner: RangeEngineAdapter) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def evaluate(self, *, row: pd.Series, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("candles") is not None and kwargs.get("bar_index") is not None:
            return self._inner.evaluate(row=row, **kwargs)
        return self._inner.evaluate(row=row_for_phase99_range(row), **kwargs)


def run_unified_router_backtest(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    config: OptimizerConfig | None = None,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    trend_adapter: TrendEngineAdapter | Any | None = None,
) -> dict[str, Any]:
    unified = build_unified_frame(candles, dataset)
    cfg = config or baseline_phase135_config()
    cfg = OptimizerConfig(**{**cfg.__dict__, "symbol": symbol, "seed": seed})
    cache = engine_cache or EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    range_wrapped = UnifiedRangeWrapper(cache.range_engine())
    trend = trend_adapter or cache.trend_engine(cfg.trend_ml_threshold)
    return run_optimized_backtest(
        unified,
        candles,
        config=cfg,
        range_adapter=range_wrapped,
        trend_adapter=trend,
        base_dir=base_dir,
        engine_cache=cache,
    )


def run_unified_range_only(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
) -> dict[str, Any]:
    cfg = OptimizerConfig(regime_params=RegimeThresholdParams(), policy="RANGE_ONLY", seed=seed, symbol=symbol)
    return run_unified_router_backtest(candles, dataset, config=cfg, seed=seed, symbol=symbol, base_dir=base_dir)
