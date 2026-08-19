"""Market impact estimation."""

from __future__ import annotations

from typing import Any

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario


def estimate_market_impact_points(ctx: ExecutionContext, profile: ExecutionProfile) -> float:
    lot_ratio = min(2.0, ctx.requested_lot / max(0.01, max_fillable_reference(ctx)))
    vol_factor = ctx.atr_percentile / 100.0
    spread_factor = min(1.5, ctx.spread_points / 0.30)
    liq_penalty = max(0.0, 1.0 - ctx.liquidity_score)

    impact = 0.02 * lot_ratio + 0.04 * vol_factor + 0.03 * spread_factor + 0.06 * liq_penalty
    impact *= ctx.atr * 0.05

    if profile.scenario == ExecutionScenario.FLASH_CRASH:
        impact *= 2.5
    elif profile.scenario == ExecutionScenario.LOW_LIQUIDITY:
        impact *= 1.8
    elif profile.scenario == ExecutionScenario.NEWS:
        impact *= 1.4

    return round(max(0.0, impact * profile.impact_multiplier), 4)


def max_fillable_reference(ctx: ExecutionContext) -> float:
    return 0.10 if ctx.liquidity_score > 0.7 else 0.05


def market_impact_summary(impacts: list[float]) -> dict[str, Any]:
    if not impacts:
        return {"count": 0}
    s = sorted(impacts)
    n = len(s)
    return {
        "count": n,
        "mean": round(sum(s) / n, 4),
        "p50": round(s[n // 2], 4),
        "p95": round(s[int(n * 0.95)], 4),
        "max": round(s[-1], 4),
    }
