"""Phase 13.7 — router recalibration using robust scoring."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_7.config import RouterVariant, ROUTER_VARIANTS
from tradingbot.ml.research.phase13_7.robust_score import robust_composite_score
from tradingbot.ml.research.phase13_7.trade_constraints import constraint_status
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    OptimizerConfig,
    RegimeThresholdParams,
    ml_threshold_pair,
)
from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest


def variant_to_config(variant: RouterVariant, *, seed: int = 42, symbol: str = "XAUUSD") -> OptimizerConfig:
    buy, sell = ml_threshold_pair(0.55)
    return OptimizerConfig(
        regime_params=RegimeThresholdParams(),
        range_buy_threshold=buy,
        range_sell_threshold=sell,
        trend_ml_threshold=variant.trend_ml_threshold,
        policy=variant.policy,
        min_confidence=variant.min_confidence,
        seed=seed,
        symbol=symbol,
    )


def run_router_backtest(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    variant: RouterVariant,
    *,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
) -> dict[str, Any]:
    cfg = variant_to_config(variant, seed=seed, symbol=symbol)
    bt = run_optimized_backtest(
        merged, candles, config=cfg, base_dir=base_dir, engine_cache=engine_cache
    )
    constraints = constraint_status(bt["metrics"])
    return {
        "variant": variant.key,
        "label": variant.label,
        "description": variant.description,
        "config": cfg,
        "metrics": bt["metrics"],
        "trades": bt["trades"],
        "constraints": constraints,
    }


def recalibrate_routers(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    walk_forward_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    wf = walk_forward_scores or {}
    rows: list[dict[str, Any]] = []
    for variant in ROUTER_VARIANTS:
        result = run_router_backtest(
            merged, candles, variant, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=engine_cache
        )
        wf_score = wf.get(variant.key, 0.5)
        score = robust_composite_score(result["metrics"], walk_forward_score=wf_score)
        rows.append(
            {
                **result,
                "walk_forward_score": wf_score,
                "robust_score": score,
            }
        )
    return sorted(rows, key=lambda r: r["robust_score"], reverse=True)
