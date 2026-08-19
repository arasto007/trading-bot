"""
موتور اندیکاتور — پیاده‌سازی تمیزِ `IIndicatorEngine`.

این آداپتر جایگزین `LegacyIndicatorEngine` است و به‌جای فراخوانی
`engine.features.calculate_indicators`، از ماژول خالص
`tradingbot.domain.indicators` استفاده می‌کند.

رفتار آن عمداً با نسخه‌ی قدیم سازگار است (همان ستون‌ها و فرمول‌ها)، اما کد آن
داخل معماری جدید و قابل‌تست است و هیچ وابستگی‌ای به `engine/` ندارد جز خواندن
پیکربندی پیش‌فرض (برای override پارامترها).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.adapters.timeframes import to_legacy
from tradingbot.domain import indicators
from tradingbot.ports.indicators import IIndicatorEngine


class TechnicalIndicatorEngine(IIndicatorEngine):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.enrich_for_market(df, "M5", None)

    def enrich_for_market(
        self, df: pd.DataFrame, timeframe: str, symbol: str | None
    ) -> pd.DataFrame:
        legacy_tf = to_legacy(timeframe)
        return indicators.compute_indicators(
            df, config=self._config, timeframe=legacy_tf, symbol=symbol
        )
