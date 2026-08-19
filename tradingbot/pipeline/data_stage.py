"""مرحله ۱: بارگذاری OHLCV — معادل DataPipeline.fetch + Storage.load."""

from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext
from tradingbot.pipeline.base import PipelineStage
from tradingbot.ports.market_data import IMarketDataProvider


class DataStage(PipelineStage):
    name = PipelineStageName.DATA

    def __init__(
        self, market_data: IMarketDataProvider, min_bars: int = 80, fetch_bars: int = 300
    ) -> None:
        self._market_data = market_data
        self._min_bars = min_bars
        self._fetch_bars = fetch_bars

    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        df = self._market_data.get_ohlcv(ctx.market, bars=self._fetch_bars)
        if df is None or len(df) < self._min_bars:
            ctx.add_error(f"Insufficient data for {ctx.market}")
            return False
        ctx.raw_ohlcv = df
        return True
