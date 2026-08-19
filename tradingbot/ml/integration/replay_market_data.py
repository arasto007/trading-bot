"""Phase 10.1 — replay market data for kernel shadow runs."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from tradingbot.domain.models import MarketKey


class ReplayMarketDataAdapter:
    """Expose candles[:bar_index+1] to kernel DataStage — read-only, no MT5 orders."""

    def __init__(self, candles: pd.DataFrame) -> None:
        self._candles = self._normalize(candles)
        self._bar_index = len(self._candles) - 1

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if not isinstance(out.index, pd.DatetimeIndex):
            if "time" in out.columns:
                out = out.set_index("time")
        out.index = pd.to_datetime(out.index, utc=True)
        return out.sort_index()

    @property
    def bar_index(self) -> int:
        return self._bar_index

    def set_bar_index(self, index: int) -> None:
        self._bar_index = max(0, min(index, len(self._candles) - 1))

    async def update_all(self, symbols: list[str], timeframes: list[str]) -> None:
        pass

    async def ensure_connected(self) -> bool:
        return True

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        end = self._bar_index + 1
        start = max(0, end - bars)
        return self._candles.iloc[start:end].copy()

    def slice_recent_days(self, days: int) -> None:
        if days <= 0:
            return
        mx = self._candles.index.max()
        cutoff = mx - timedelta(days=days)
        self._candles = self._candles.loc[self._candles.index >= cutoff]
        self._bar_index = len(self._candles) - 1
