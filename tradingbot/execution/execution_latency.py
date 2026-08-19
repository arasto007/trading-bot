"""Latency distribution model — decision through execution."""

from __future__ import annotations

import random
from typing import Any

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, LatencyProfile


LATENCY_COMPONENTS_MS = {
    LatencyProfile.NORMAL: {
        "decision": (8.0, 3.0),
        "python": (2.0, 1.0),
        "mt5": (15.0, 8.0),
        "broker": (25.0, 12.0),
        "network": (10.0, 5.0),
        "execution": (20.0, 10.0),
    },
    LatencyProfile.FAST_VPS: {
        "decision": (4.0, 1.5),
        "python": (1.0, 0.5),
        "mt5": (8.0, 3.0),
        "broker": (12.0, 5.0),
        "network": (4.0, 2.0),
        "execution": (10.0, 4.0),
    },
    LatencyProfile.SLOW_VPS: {
        "decision": (15.0, 6.0),
        "python": (5.0, 2.0),
        "mt5": (35.0, 15.0),
        "broker": (55.0, 25.0),
        "network": (30.0, 12.0),
        "execution": (45.0, 20.0),
    },
}


def _sample_normal(rng: random.Random, mean: float, std: float) -> float:
    return max(0.0, rng.gauss(mean, std))


def sample_latency_breakdown(
    ctx: ExecutionContext,
    profile: ExecutionProfile,
    rng: random.Random,
) -> dict[str, float]:
    params = LATENCY_COMPONENTS_MS[profile.latency_profile]
    breakdown = {k: round(_sample_normal(rng, m, s), 3) for k, (m, s) in params.items()}
    if ctx.is_fast_market:
        for k in breakdown:
            breakdown[k] *= 0.85
    if ctx.is_slow_market:
        for k in breakdown:
            breakdown[k] *= 1.35
    if profile.scenario.value == "high_latency":
        for k in breakdown:
            breakdown[k] *= 2.0
    delay_mult = profile.delay_multiplier
    for k in ("broker", "network", "execution"):
        breakdown[k] = round(breakdown[k] * delay_mult, 3)
    breakdown["total"] = round(sum(breakdown.values()), 3)
    return breakdown


def sample_total_latency_ms(
    ctx: ExecutionContext,
    profile: ExecutionProfile,
    rng: random.Random,
) -> tuple[float, dict[str, float]]:
    breakdown = sample_latency_breakdown(ctx, profile, rng)
    return breakdown["total"], breakdown


def latency_distribution_samples(
    contexts: list[ExecutionContext],
    profile: ExecutionProfile,
    *,
    seed: int = 42,
) -> dict[str, Any]:
    rng = random.Random(seed)
    totals: list[float] = []
    component_sums: dict[str, float] = {}
    for ctx in contexts:
        total, breakdown = sample_total_latency_ms(ctx, profile, rng)
        totals.append(total)
        for k, v in breakdown.items():
            component_sums[k] = component_sums.get(k, 0.0) + v
    n = len(totals) or 1
    totals_sorted = sorted(totals)

    def pct(p: float) -> float:
        if not totals_sorted:
            return 0.0
        idx = min(len(totals_sorted) - 1, max(0, int(p * (len(totals_sorted) - 1))))
        return totals_sorted[idx]

    return {
        "count": len(totals),
        "profile": profile.latency_profile.value,
        "total_ms": {
            "mean": round(sum(totals) / n, 3),
            "p50": round(pct(0.5), 3),
            "p95": round(pct(0.95), 3),
            "max": round(max(totals) if totals else 0.0, 3),
        },
        "component_means_ms": {k: round(v / n, 3) for k, v in component_sums.items()},
    }
