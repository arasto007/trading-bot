"""Phase 13.6 — regime routing policy combinations."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    OptimizerConfig,
    RegimeThresholdParams,
    composite_score,
)

REGIME_POLICIES: tuple[str, ...] = ("A", "B", "C", "D")

POLICY_DESCRIPTIONS: dict[str, str] = {
    "A": "RANGE->Phase9.9, TREND->Trend, HIGH_VOL/NO_TRADE->BLOCK",
    "B": "RANGE->Phase9.9, TREND->Trend, HIGH_VOL->Trend only, NO_TRADE->BLOCK",
    "C": "RANGE->Phase9.9, TREND->BLOCK, HIGH_VOL/NO_TRADE->BLOCK",
    "D": "ALL REGIMES->Phase9.9 baseline",
}


def resolve_routing_action(regime: str, policy: str) -> str:
    regime = str(regime).upper()
    policy = str(policy).upper()

    if policy == "D":
        return "RANGE" if regime != "NO_TRADE" else "BLOCK"
    if policy == "RANGE_ONLY":
        return "RANGE" if regime != "NO_TRADE" else "BLOCK"
    if policy == "TREND_ONLY":
        return "TREND" if regime == "TREND" else "BLOCK"
    if regime == "NO_TRADE":
        return "BLOCK"
    if policy == "C" and regime == "TREND":
        return "BLOCK"
    if policy == "B" and regime == "HIGH_VOLATILITY":
        return "TREND"
    if regime == "HIGH_VOLATILITY":
        return "BLOCK"
    if regime == "RANGE":
        return "RANGE"
    if regime == "TREND":
        return "TREND"
    return "BLOCK"


def optimize_regime_policies(
    merged,
    candles,
    *,
    regime_params: RegimeThresholdParams | None = None,
    range_buy_threshold: float = 0.55,
    range_sell_threshold: float = 0.45,
    trend_ml_threshold: float = 0.55,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest

    params = regime_params or RegimeThresholdParams()
    rows: list[dict[str, Any]] = []
    policy_grid = ("A",) if quick else REGIME_POLICIES

    for policy in policy_grid:
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
                "policy": policy,
                "description": POLICY_DESCRIPTIONS[policy],
                "metrics": m,
                "score": composite_score(m),
            }
        )

    ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
    return {
        "policies": list(REGIME_POLICIES),
        "ranking": ranked,
        "best_policy": ranked[0]["policy"] if ranked else "A",
    }
