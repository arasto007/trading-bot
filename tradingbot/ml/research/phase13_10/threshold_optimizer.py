"""Phase 13.10 — trend ML threshold grid search."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase13_10.config import MIN_TRADES_REJECT, THRESHOLD_GRID
from tradingbot.ml.research.phase13_10.robust_score import count_trend_trades, threshold_composite_score
from tradingbot.ml.research.phase13_10.trend_engines import build_trend_adapter
from tradingbot.ml.research.phase13_10.walk_forward import quick_wf_score_for_config
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_router_backtest
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams


def optimize_trend_threshold(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    model: Any,
    scaler: Any,
    model_name: str,
    rule_fn: Callable[..., str],
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    cache = engine_cache or EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    grid = THRESHOLD_GRID[:2] if quick else THRESHOLD_GRID
    rows: list[dict[str, Any]] = []

    for threshold in grid:
        adapter = build_trend_adapter(
            model=model,
            scaler=scaler,
            model_name=model_name,
            threshold=threshold,
            rule_fn=rule_fn,
            symbol=symbol,
        )
        cfg = OptimizerConfig(
            regime_params=RegimeThresholdParams(),
            policy="A",
            trend_ml_threshold=threshold,
            seed=seed,
            symbol=symbol,
        )
        bt = run_unified_router_backtest(
            candles,
            dataset,
            config=cfg,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            engine_cache=cache,
            trend_adapter=adapter,
        )
        m = bt["metrics"]
        trades = int(m.get("trades", 0))
        trend_trades = count_trend_trades(bt)
        rejected = trades < MIN_TRADES_REJECT
        wf = quick_wf_score_for_config(
            candles,
            dataset,
            config=cfg,
            trend_adapter=adapter,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            quick=quick,
        )
        score = 0.0 if rejected else threshold_composite_score(m, walk_forward_score=wf)
        rows.append(
            {
                "threshold": threshold,
                "model": model_name,
                "trades": trades,
                "trend_trades": trend_trades,
                "profit_factor": round(float(m.get("profit_factor", 0.0)), 4),
                "expectancy": round(float(m.get("expectancy", m.get("expectancy_r", 0.0))), 4),
                "max_drawdown": round(float(m.get("max_drawdown", 0.0)), 4),
                "win_rate": round(float(m.get("win_rate", 0.0)), 4),
                "walk_forward_score": round(wf, 4),
                "composite_score": score,
                "rejected": rejected,
                "rejection_reason": "trades_below_100" if rejected else None,
            }
        )

    valid = [r for r in rows if not r["rejected"]]
    ranked = sorted(valid, key=lambda r: r["composite_score"], reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    best = ranked[0] if ranked else None

    return {
        "phase": "13.10",
        "grid": list(grid),
        "results": rows,
        "valid_count": len(valid),
        "best_threshold": best["threshold"] if best else None,
        "best": best,
        "ranking": ranked,
    }
