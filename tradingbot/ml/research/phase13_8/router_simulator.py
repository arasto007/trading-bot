"""Phase 13.8 — router simulation with recovered trend engine."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase13_8.config import ROUTER_SIM_VARIANTS, RouterSimVariant
from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams, ml_threshold_pair
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame, run_optimized_backtest


def simulate_routers(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    trend_engine: RecoveredTrendEngine,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
) -> list[dict[str, Any]]:
    merged = prepare_merged_frame(candles, dataset)
    cache = engine_cache or EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    buy, sell = ml_threshold_pair(0.55)
    rows: list[dict[str, Any]] = []

    for rv in ROUTER_SIM_VARIANTS:
        if rv.range_only:
            cfg = OptimizerConfig(regime_params=RegimeThresholdParams(), policy="RANGE_ONLY", seed=seed, symbol=symbol)
            bt = run_optimized_backtest(merged, candles, config=cfg, base_dir=base_dir, engine_cache=cache)
            trend_trades = 0
        else:
            engine = RecoveredTrendEngine(
                model=trend_engine.model,
                scaler=trend_engine.scaler,
                model_name=trend_engine.model_name,
                threshold=rv.trend_threshold,
                rule_fn=trend_engine.rule_fn,
                symbol=symbol,
            )
            cfg = OptimizerConfig(
                regime_params=RegimeThresholdParams(),
                range_buy_threshold=buy,
                range_sell_threshold=sell,
                trend_ml_threshold=rv.trend_threshold,
                policy=rv.policy,
                seed=seed,
                symbol=symbol,
            )
            bt = run_optimized_backtest(
                merged,
                candles,
                config=cfg,
                base_dir=base_dir,
                engine_cache=cache,
                trend_adapter=engine,
            )
            trend_trades = sum(
                1 for t in bt["trades"] if t.get("type") == "trade" and t.get("source_engine") == "trend_ml"
            )

        m = bt["metrics"]
        rows.append(
            {
                "router": rv.key,
                "label": rv.label,
                "trades": m.get("trades", 0),
                "profit_factor": m.get("profit_factor", 0.0),
                "expectancy": m.get("expectancy", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "max_drawdown": m.get("max_drawdown", 0.0),
                "trend_contribution": trend_trades,
            }
        )
    return rows
