"""Port: ذخیره‌سازی — جایگزین Storage (parquet/sqlite)."""

from typing import Protocol

import pandas as pd

from tradingbot.domain.models import MarketKey


class IMarketDataStore(Protocol):
    def save(self, market: MarketKey, df: pd.DataFrame) -> None: ...
    def load(self, market: MarketKey) -> pd.DataFrame | None: ...
