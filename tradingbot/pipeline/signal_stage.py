"""مرحله ۳: سیگنال — معادل StrategyManager.generate_combined_signals + generate_signal."""

from __future__ import annotations

from tradingbot.domain.enums import PipelineStageName, SignalDirection
from tradingbot.domain.models import CycleContext
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.pipeline.base import PipelineStage
from tradingbot.ports.strategies import IStrategyRegistry


class SignalStage(PipelineStage):
    name = PipelineStageName.SIGNALS

    def __init__(self, strategies: IStrategyRegistry) -> None:
        self._strategies = strategies
        self._last_closed_bar: dict[str, object] = {}

    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        if ctx.enriched_ohlcv is None:
            ctx.add_error("SignalStage: enriched_ohlcv missing")
            return False

        closed = exclude_forming_bar(ctx.enriched_ohlcv)
        if closed is None or closed.empty:
            return False

        market_key = str(ctx.market)
        last_ts = closed.index[-1]
        if self._last_closed_bar.get(market_key) == last_ts:
            return False
        self._last_closed_bar[market_key] = last_ts

        correlation = portfolio_snapshot.get("correlation_data")
        signal = self._strategies.generate_signal(
            ctx.market, closed, correlation_data=correlation
        )
        if signal is None or signal.direction == SignalDirection.HOLD:
            return False
        ctx.signal = signal
        return True
