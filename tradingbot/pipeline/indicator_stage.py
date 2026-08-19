"""مرحله ۲: اندیکاتور — معادل features.calculate_indicators."""

from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext
from tradingbot.pipeline.base import PipelineStage
from tradingbot.ports.indicators import IIndicatorEngine


class IndicatorStage(PipelineStage):
    name = PipelineStageName.INDICATORS

    def __init__(self, indicators: IIndicatorEngine) -> None:
        self._indicators = indicators

    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        if ctx.raw_ohlcv is None:
            ctx.add_error("IndicatorStage: raw_ohlcv missing")
            return False
        raw = ctx.raw_ohlcv.copy()
        if hasattr(self._indicators, "enrich_for_market"):
            ctx.enriched_ohlcv = self._indicators.enrich_for_market(
                raw, ctx.market.timeframe, ctx.market.symbol
            )
        else:
            ctx.enriched_ohlcv = self._indicators.enrich(raw)
        return True
