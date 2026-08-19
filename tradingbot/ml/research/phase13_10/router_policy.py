"""Phase 13.10 — router policy comparison."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_10.config import ROUTER_POLICIES
from tradingbot.ml.research.phase13_10.monte_carlo import run_monte_carlo_phase13_10
from tradingbot.ml.research.phase13_10.robust_score import count_trend_trades, threshold_composite_score
from tradingbot.ml.research.phase13_10.trend_engines import build_trend_adapter
from tradingbot.ml.research.phase13_10.walk_forward import quick_wf_score_for_config, run_expanding_walk_forward
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_router_backtest
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams


def compare_router_policies(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    model: Any,
    scaler: Any,
    model_name: str,
    rule_fn: Any,
    best_threshold: float = 0.45,
    relaxed_threshold: float = 0.30,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    cache = engine_cache or EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    policies = ROUTER_POLICIES[:2] if quick else ROUTER_POLICIES
    rows: list[dict[str, Any]] = []

    for policy_def in policies:
        threshold = relaxed_threshold if policy_def.relaxed_ml else best_threshold
        if policy_def.range_only:
            adapter = None
            cfg = OptimizerConfig(
                regime_params=RegimeThresholdParams(),
                policy="RANGE_ONLY",
                seed=seed,
                symbol=symbol,
            )
        else:
            adapter = build_trend_adapter(
                model=model,
                scaler=scaler,
                model_name=model_name,
                threshold=threshold,
                rule_fn=rule_fn,
                symbol=symbol,
                rules_only=policy_def.rules_only,
            )
            cfg = OptimizerConfig(
                regime_params=RegimeThresholdParams(),
                policy=policy_def.policy,
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
        trend_trades = count_trend_trades(bt)
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
        mc = run_monte_carlo_phase13_10(
            bt["trades"],
            simulations=50 if quick else 1000,
            seed=seed,
        )
        rows.append(
            {
                "policy": policy_def.key,
                "label": policy_def.label,
                "description": policy_def.description,
                "trades": int(m.get("trades", 0)),
                "trend_trades": trend_trades,
                "profit_factor": round(float(m.get("profit_factor", 0.0)), 4),
                "expectancy": round(float(m.get("expectancy", m.get("expectancy_r", 0.0))), 4),
                "max_drawdown": round(float(m.get("max_drawdown", 0.0)), 4),
                "walk_forward_score": round(wf, 4),
                "monte_carlo_profitable_pct": mc["profitable_pct"],
                "monte_carlo_passes": mc["passes_gate"],
                "robust_score": threshold_composite_score(m, walk_forward_score=wf),
            }
        )

    ranked = sorted(rows, key=lambda r: r["robust_score"], reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i

    return {
        "phase": "13.10",
        "policies_tested": [p.key for p in policies],
        "results": rows,
        "best_policy": ranked[0]["policy"] if ranked else None,
        "ranking": ranked,
    }
