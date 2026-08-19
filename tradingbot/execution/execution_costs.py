"""Spread, slippage, and commission cost models."""

from __future__ import annotations

import math
from typing import Any

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario, OrderSide


SESSION_SPREAD_MULT = {
    "Asian": 1.35,
    "London": 1.0,
    "Overlap": 0.85,
    "New York": 0.95,
}


def session_from_hour(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asian"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 16:
        return "Overlap"
    if 16 <= hour < 21:
        return "New York"
    return "Asian"


def base_spread_points(ctx: ExecutionContext) -> float:
    spread = float(ctx.spread_points)
    session_mult = SESSION_SPREAD_MULT.get(ctx.session, 1.0)
    vol_mult = 1.0 + max(0.0, (ctx.atr_percentile - 50.0) / 100.0)
    liq_mult = 1.0 + max(0.0, (0.6 - ctx.liquidity_score) * 0.8)
    news_mult = 1.8 if ctx.is_news_window else 1.0
    weekend_mult = 2.5 if ctx.is_weekend else 1.0
    fast_mult = 1.4 if ctx.is_fast_market else 1.0
    slow_mult = 0.95 if ctx.is_slow_market else 1.0
    return max(0.05, spread * session_mult * vol_mult * liq_mult * news_mult * weekend_mult * fast_mult * slow_mult)


def scenario_spread_multiplier(profile: ExecutionProfile) -> float:
    mapping = {
        ExecutionScenario.NORMAL: 1.0,
        ExecutionScenario.HIGH_SPREAD: 2.5,
        ExecutionScenario.HIGH_SLIPPAGE: 1.1,
        ExecutionScenario.HIGH_LATENCY: 1.05,
        ExecutionScenario.LOW_LIQUIDITY: 1.8,
        ExecutionScenario.NEWS: 2.2,
        ExecutionScenario.FLASH_CRASH: 3.5,
        ExecutionScenario.WEEKEND: 2.8,
    }
    return mapping.get(profile.scenario, 1.0) * profile.spread_multiplier


def compute_spread_points(ctx: ExecutionContext, profile: ExecutionProfile) -> float:
    return round(base_spread_points(ctx) * scenario_spread_multiplier(profile), 4)


def slippage_probability(ctx: ExecutionContext, profile: ExecutionProfile) -> dict[str, float]:
    """Return probabilities for negative, zero, positive slippage."""
    atr_factor = min(1.0, ctx.atr / max(ctx.reference_price * 0.001, 0.01))
    spread_factor = min(1.0, ctx.spread_points / 0.5)
    liq_factor = max(0.0, 1.0 - ctx.liquidity_score)
    lot_factor = min(1.0, ctx.requested_lot / 0.10)
    session_bias = 0.05 if ctx.session in ("Overlap", "New York") else 0.0
    trend_bias = ctx.trend_strength * 0.08

    neg = 0.35 + 0.20 * atr_factor + 0.15 * spread_factor + 0.15 * liq_factor + 0.10 * lot_factor
    pos = 0.10 + session_bias + trend_bias
    if profile.scenario == ExecutionScenario.HIGH_SLIPPAGE:
        neg *= 1.8
    elif profile.scenario == ExecutionScenario.FLASH_CRASH:
        neg *= 2.2
    neg = min(0.90, neg * profile.slippage_multiplier)
    pos = min(0.35, pos * profile.slippage_multiplier)
    zero = max(0.0, 1.0 - neg - pos)
    total = neg + zero + pos
    return {"negative": neg / total, "zero": zero / total, "positive": pos / total}


def slippage_magnitude_points(ctx: ExecutionContext, profile: ExecutionProfile) -> float:
    base = 0.05 + 0.08 * (ctx.atr_percentile / 100.0) + 0.06 * (1.0 - ctx.liquidity_score)
    base += 0.04 * min(1.0, ctx.requested_lot / 0.05)
    if ctx.is_fast_market:
        base *= 1.5
    if ctx.is_news_window:
        base *= 1.3
    return max(0.0, base * profile.slippage_multiplier)


def apply_side_price(reference: float, side: OrderSide, spread: float, slippage: float) -> float:
    half = spread / 2.0
    if side == OrderSide.BUY:
        return reference + half + slippage
    return reference - half - slippage


def execution_cost_points(spread: float, slippage: float, impact: float) -> float:
    return round(spread / 2.0 + abs(slippage) + impact, 4)


def spread_distribution_samples(contexts: list[ExecutionContext], profile: ExecutionProfile) -> dict[str, Any]:
    spreads = [compute_spread_points(c, profile) for c in contexts]
    if not spreads:
        return {"count": 0}
    spreads_sorted = sorted(spreads)
    n = len(spreads_sorted)

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, int(p * (n - 1))))
        return spreads_sorted[idx]

    return {
        "count": n,
        "mean": round(sum(spreads) / n, 4),
        "min": round(spreads_sorted[0], 4),
        "max": round(spreads_sorted[-1], 4),
        "p50": round(pct(0.5), 4),
        "p95": round(pct(0.95), 4),
        "std": round(_std(spreads), 4),
    }


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
