"""Phase 13.6 — confidence-based trade filtering."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig

CONFIDENCE_GRID: tuple[float, ...] = (0.0, 0.25, 0.35, 0.45, 0.55)


def optimize_confidence_filter(
    merged,
    candles,
    *,
    config: OptimizerConfig,
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.router_optimizer.optimizer_types import composite_score
    from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest

    grid = (0.0, 0.35, 0.55) if quick else CONFIDENCE_GRID
    rows: list[dict[str, Any]] = []
    for min_conf in grid:
        cfg = OptimizerConfig(
            regime_params=config.regime_params,
            range_buy_threshold=config.range_buy_threshold,
            range_sell_threshold=config.range_sell_threshold,
            trend_ml_threshold=config.trend_ml_threshold,
            policy=config.policy,
            min_confidence=min_conf,
            seed=config.seed,
            symbol=config.symbol,
        )
        bt = run_optimized_backtest(
            merged, candles, config=cfg, base_dir=base_dir, engine_cache=engine_cache
        )
        m = bt["metrics"]
        rows.append({"min_confidence": min_conf, "metrics": m, "score": composite_score(m)})

    ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
    return {
        "grid": list(grid),
        "ranking": ranked,
        "best_min_confidence": ranked[0]["min_confidence"] if ranked else 0.0,
    }
