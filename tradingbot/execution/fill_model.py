"""Fill model — partial fills, requotes, price gaps."""

from __future__ import annotations

import random

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile
from tradingbot.execution.liquidity_model import effective_liquidity, max_fillable_lot


PARTIAL_FILL_LEVELS = (0.0, 0.25, 0.50, 0.75, 1.0)


def choose_fill_ratio(
    ctx: ExecutionContext,
    profile: ExecutionProfile,
    rng: random.Random,
) -> float:
    if not profile.partial_fill_enabled:
        return 1.0

    liq = effective_liquidity(ctx, profile)
    shortage = 1.0 - liq
    if shortage < 0.15:
        return 1.0

    weights = {
        1.0: max(0.05, liq),
        0.75: shortage * 0.35,
        0.50: shortage * 0.30,
        0.25: shortage * 0.20,
        0.0: shortage * 0.10,
    }
    total = sum(weights.values())
    roll = rng.random() * total
    cumulative = 0.0
    for level in PARTIAL_FILL_LEVELS:
        cumulative += weights.get(level, 0.0)
        if roll <= cumulative:
            return level
    return 1.0


def compute_filled_lot(requested_lot: float, fill_ratio: float, profile: ExecutionProfile, ctx: ExecutionContext) -> float:
    cap = max_fillable_lot(ctx, profile)
    filled = requested_lot * fill_ratio
    return round(min(filled, cap), 4)


def should_requote(ctx: ExecutionContext, profile: ExecutionProfile, rng: random.Random) -> bool:
    base = profile.requote_probability
    if ctx.is_fast_market:
        base *= 2.5
    if ctx.is_news_window:
        base *= 2.0
    if ctx.is_weekend:
        base *= 1.5
    return rng.random() < min(0.45, base)


def price_gap_points(ctx: ExecutionContext, rng: random.Random) -> float:
    if not ctx.is_fast_market and ctx.atr_percentile < 85:
        return 0.0
    gap = rng.uniform(0.0, ctx.atr * 0.15)
    if ctx.is_weekend:
        gap += rng.uniform(0.0, ctx.atr * 0.25)
    return round(gap, 4)


def fill_statistics(fills: list[dict]) -> dict:
    if not fills:
        return {"count": 0}
    ratios = [float(f.get("fill_ratio", 1.0)) for f in fills]
    partial = sum(1 for r in ratios if r < 1.0)
    requotes = sum(1 for f in fills if f.get("requoted"))
    return {
        "count": len(fills),
        "full_fill_pct": round(sum(1 for r in ratios if r >= 1.0) / len(ratios) * 100, 2),
        "partial_fill_pct": round(partial / len(ratios) * 100, 2),
        "requote_pct": round(requotes / len(fills) * 100, 2),
        "fill_ratio_distribution": {
            str(level): sum(1 for r in ratios if abs(r - level) < 0.01)
            for level in PARTIAL_FILL_LEVELS
        },
        "mean_fill_ratio": round(sum(ratios) / len(ratios), 4),
    }
