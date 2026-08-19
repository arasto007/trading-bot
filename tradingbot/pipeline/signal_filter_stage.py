"""Pipeline stage: WPSQF signal quality filter (after ML, before RiskGate)."""

from __future__ import annotations

from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.pipeline.base import PipelineStage
from tradingbot.services.signal_filter_mode import SignalFilterMode, resolve_signal_filter_mode
from tradingbot.services.winner_population_signal_quality_filter import WinnerPopulationSignalQualityFilter


class SignalFilterStage(PipelineStage):
    name = PipelineStageName.SIGNAL_FILTER

    def __init__(self, *, config: dict | None = None) -> None:
        self._config = config or {}
        self._filter = WinnerPopulationSignalQualityFilter(config=self._config)

    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        if resolve_signal_filter_mode(config=self._config) == SignalFilterMode.OFF:
            return True
        if ctx.signal is None or ctx.enriched_ohlcv is None:
            return False

        closed = exclude_forming_bar(ctx.enriched_ohlcv)
        if closed is None or closed.empty:
            ctx.signal = None
            return False

        ts = closed.index[-1]
        result = self._filter.evaluate(ctx.signal, closed, timestamp=str(ts))
        meta = dict(ctx.signal.metadata or {})
        meta["wpsqf"] = result.to_dict()
        ctx.signal.metadata = meta

        if not result.allowed:
            ctx.signal = None
            return False
        return True
