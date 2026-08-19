"""Port: دریافت و به‌روزرسانی داده بازار — جایگزین DataPipeline + Storage fetch."""

from typing import Protocol

import pandas as pd

from tradingbot.domain.models import MarketKey


class IMarketDataProvider(Protocol):
    """قرارداد منبع داده — live (MT5) یا backtest (parquet)."""

    async def update_all(self, symbols: list[str], timeframes: list[str]) -> None:
        """به‌روزرسانی داده همه symbol/timeframe (معادل DataPipeline.update_data)."""
        ...

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        """بارگذاری OHLCV برای یک بازار."""
        ...
