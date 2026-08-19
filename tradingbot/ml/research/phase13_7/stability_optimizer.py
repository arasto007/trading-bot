"""Phase 13.7 — stability optimization across router variants."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_7.config import ROUTER_VARIANTS
from tradingbot.ml.research.phase13_7.robust_score import compare_scores, robust_composite_score
from tradingbot.ml.research.phase13_7.router_recalibrator import recalibrate_routers
from tradingbot.ml.research.phase13_7.trade_constraints import constraint_status
from tradingbot.ml.research.phase13_7.walk_forward_validator import run_walk_forward_for_variant
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache


def optimize_router_stability(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    cache = engine_cache or EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    wf_scores: dict[str, float] = {}
    wf_results: dict[str, Any] = {}

    for variant in ROUTER_VARIANTS:
        wf = run_walk_forward_for_variant(
            merged, candles, variant, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=cache, quick=quick
        )
        wf_results[variant.key] = wf
        wf_scores[variant.key] = float(wf.get("robustness", {}).get("robustness_score", 0.0))

    ranked = recalibrate_routers(
        merged,
        candles,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        walk_forward_scores=wf_scores,
    )

    comparison = []
    for row in ranked:
        m = row["metrics"]
        comparison.append(
            {
                "variant": row["variant"],
                "label": row["label"],
                "trades": m.get("trades", 0),
                "profit_factor": m.get("profit_factor", 0.0),
                "expectancy": m.get("expectancy", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "max_drawdown": m.get("max_drawdown", 0.0),
                "robust_score": row["robust_score"],
                "walk_forward_score": row["walk_forward_score"],
                "constraints": row["constraints"],
            }
        )

    best = ranked[0] if ranked else None
    return {
        "phase": "13.7",
        "variants_tested": len(ROUTER_VARIANTS),
        "ranking": compare_scores(comparison),
        "best_variant": best["variant"] if best else None,
        "best_config": best,
        "walk_forward_by_variant": wf_results,
    }
