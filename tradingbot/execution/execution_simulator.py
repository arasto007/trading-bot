"""Production-grade execution simulator — research layer only."""

from __future__ import annotations

import random
from typing import Any

from tradingbot.execution.execution_costs import (
    apply_side_price,
    compute_spread_points,
    execution_cost_points,
    slippage_magnitude_points,
    slippage_probability,
)
from tradingbot.execution.execution_latency import sample_total_latency_ms
from tradingbot.execution.execution_models import (
    ExecutionContext,
    ExecutionProfile,
    ExecutionResult,
    ExecutionScenario,
    FillOutcome,
    OrderSide,
)
from tradingbot.execution.fill_model import choose_fill_ratio, compute_filled_lot, price_gap_points, should_requote
from tradingbot.execution.liquidity_model import effective_liquidity
from tradingbot.execution.market_impact import estimate_market_impact_points
from tradingbot.execution.order_queue import sample_queue_delay_ms


def execution_quality_score(
    *,
    spread_points: float,
    latency_ms: float,
    slippage_points: float,
    fill_ratio: float,
    market_impact_points: float,
    queue_delay_ms: float,
) -> float:
    spread_score = max(0.0, 100.0 - spread_points * 80.0)
    latency_score = max(0.0, 100.0 - latency_ms / 2.0)
    slip_score = max(0.0, 100.0 - abs(slippage_points) * 120.0)
    fill_score = fill_ratio * 100.0
    impact_score = max(0.0, 100.0 - market_impact_points * 150.0)
    queue_score = max(0.0, 100.0 - queue_delay_ms / 1.5)
    score = (
        spread_score * 0.20
        + latency_score * 0.15
        + slip_score * 0.20
        + fill_score * 0.20
        + impact_score * 0.15
        + queue_score * 0.10
    )
    return round(max(0.0, min(100.0, score)), 2)


class ExecutionSimulator:
    """Simulate realistic MT5 market execution without touching production adapters."""

    def __init__(self, profile: ExecutionProfile | None = None) -> None:
        self.profile = profile or ExecutionProfile()
        self._rng = random.Random(self.profile.seed)

    def simulate(self, ctx: ExecutionContext, *, queue_depth: int = 0) -> ExecutionResult:
        spread = compute_spread_points(ctx, self.profile)
        slip_probs = slippage_probability(ctx, self.profile)
        slip_mag = slippage_magnitude_points(ctx, self.profile)
        roll = self._rng.random()
        if roll < slip_probs["negative"]:
            slippage = slip_mag
            slip_sign = -1
        elif roll < slip_probs["negative"] + slip_probs["positive"]:
            slippage = -slip_mag * 0.6
            slip_sign = 1
        else:
            slippage = 0.0
            slip_sign = 0

        latency_ms, latency_breakdown = sample_total_latency_ms(ctx, self.profile, self._rng)
        queue_delay_ms = sample_queue_delay_ms(ctx, self.profile, self._rng, queue_depth=queue_depth)
        impact = estimate_market_impact_points(ctx, self.profile)
        gap = price_gap_points(ctx, self._rng)
        requoted = should_requote(ctx, self.profile, self._rng)

        if requoted:
            spread *= 1.15
            slippage += slip_mag * 0.5
            slip_sign = -1 if slippage >= 0 else 1

        fill_ratio = choose_fill_ratio(ctx, self.profile, self._rng)
        filled_lot = compute_filled_lot(ctx.requested_lot, fill_ratio, self.profile, ctx)

        adjusted_slippage = slippage + impact + gap
        if ctx.side == OrderSide.BUY:
            signed_slip = abs(adjusted_slippage)
        else:
            signed_slip = -abs(adjusted_slippage)

        fill_price = apply_side_price(ctx.reference_price, ctx.side, spread, signed_slip)
        total_cost = execution_cost_points(spread, signed_slip, impact)
        score = execution_quality_score(
            spread_points=spread,
            latency_ms=latency_ms + queue_delay_ms,
            slippage_points=signed_slip,
            fill_ratio=fill_ratio,
            market_impact_points=impact,
            queue_delay_ms=queue_delay_ms,
        )

        outcome = FillOutcome(
            fill_price=round(fill_price, 5),
            filled_lot=filled_lot,
            fill_ratio=fill_ratio,
            spread_points=spread,
            slippage_points=round(signed_slip, 4),
            slippage_sign=slip_sign,
            latency_ms=latency_ms,
            queue_delay_ms=queue_delay_ms,
            market_impact_points=impact,
            requoted=requoted,
            partial_fill=fill_ratio < 1.0,
            execution_score=score,
        )
        liq = effective_liquidity(ctx, self.profile)
        diagnostics = {
            "scenario": self.profile.scenario.value,
            "latency_profile": self.profile.latency_profile.value,
            "liquidity_score": round(liq, 4),
            "latency_breakdown_ms": latency_breakdown,
            "gap_points": gap,
            "slippage_probabilities": slip_probs,
        }
        return ExecutionResult(
            context=ctx,
            outcome=outcome,
            total_cost_points=total_cost,
            effective_price=outcome.fill_price,
            diagnostics=diagnostics,
        )

    def simulate_batch(self, contexts: list[ExecutionContext]) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for i, ctx in enumerate(contexts):
            results.append(self.simulate(ctx, queue_depth=i % 5))
        return results


def context_from_trade(trade: dict[str, Any], *, hour: int = 12) -> ExecutionContext:
    from tradingbot.execution.execution_costs import session_from_hour

    direction = str(trade.get("direction", "BUY"))
    return ExecutionContext(
        symbol=str(trade.get("symbol", "XAUUSD")),
        side=OrderSide.BUY if direction == "BUY" else OrderSide.SELL,
        requested_lot=float(trade.get("lot", 0.01)),
        reference_price=float(trade.get("entry_price", 2000.0)),
        timestamp=str(trade.get("timestamp", "")),
        session=session_from_hour(hour),
        atr=float(trade.get("atr", 1.5)),
        atr_percentile=float(trade.get("atr_percentile", 50.0)),
        spread_points=float(trade.get("spread", 0.30)),
        liquidity_score=float(trade.get("liquidity_score", 0.7)),
        trend_strength=float(trade.get("trend_strength", 0.5)),
    )
