"""Liquidity availability and shortage model."""

from __future__ import annotations

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario


SESSION_LIQUIDITY = {
    "Asian": 0.55,
    "London": 0.80,
    "Overlap": 0.95,
    "New York": 0.85,
}


def base_liquidity_score(ctx: ExecutionContext) -> float:
    session = SESSION_LIQUIDITY.get(ctx.session, 0.65)
    vol_penalty = max(0.0, (ctx.atr_percentile - 70.0) / 100.0) * 0.35
    news_penalty = 0.25 if ctx.is_news_window else 0.0
    weekend_penalty = 0.45 if ctx.is_weekend else 0.0
    lot_demand = min(0.35, ctx.requested_lot / 0.20 * 0.20)
    score = session - vol_penalty - news_penalty - weekend_penalty - lot_demand
    return max(0.05, min(1.0, score))


def scenario_liquidity_multiplier(profile: ExecutionProfile) -> float:
    if profile.scenario == ExecutionScenario.LOW_LIQUIDITY:
        return 0.35 * profile.liquidity_multiplier
    if profile.scenario == ExecutionScenario.FLASH_CRASH:
        return 0.20 * profile.liquidity_multiplier
    if profile.scenario == ExecutionScenario.NEWS:
        return 0.55 * profile.liquidity_multiplier
    if profile.scenario == ExecutionScenario.WEEKEND:
        return 0.25 * profile.liquidity_multiplier
    return profile.liquidity_multiplier


def effective_liquidity(ctx: ExecutionContext, profile: ExecutionProfile) -> float:
    return max(0.01, min(1.0, base_liquidity_score(ctx) * scenario_liquidity_multiplier(profile)))


def liquidity_shortage_factor(ctx: ExecutionContext, profile: ExecutionProfile) -> float:
    """0 = no shortage, 1 = severe shortage."""
    liq = effective_liquidity(ctx, profile)
    return round(max(0.0, 1.0 - liq), 4)


def max_fillable_lot(ctx: ExecutionContext, profile: ExecutionProfile) -> float:
    liq = effective_liquidity(ctx, profile)
    cap = 0.50 * liq
    return round(max(0.01, cap), 4)
