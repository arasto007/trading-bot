"""اندیکاتور passthrough — اندیکاتورها یک‌بار در data_source محاسبه شده‌اند."""

from __future__ import annotations

import pandas as pd

from tradingbot.ports.indicators import IIndicatorEngine


class PassthroughIndicatorEngine(IIndicatorEngine):
    """چون داده‌ی بک‌تست از قبل enriched است، فقط همان DataFrame را برمی‌گرداند."""

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def enrich_for_market(self, df: pd.DataFrame, timeframe: str, symbol: str | None) -> pd.DataFrame:
        return df
