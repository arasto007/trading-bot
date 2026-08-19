"""Port: محاسبه اندیکاتور — جایگزین features.calculate_indicators."""

from typing import Protocol

import pandas as pd


class IIndicatorEngine(Protocol):
    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """افزودن RSI, MACD, ATR, ADX, Bollinger, ... به DataFrame."""
        ...
