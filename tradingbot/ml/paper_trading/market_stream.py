"""Phase 9.10 — read-only market data stream (CandleStore or MT5 copy_rates)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore

logger = logging.getLogger(__name__)


class MarketStream:
    """Sequential closed-candle provider — no order execution."""

    def __init__(self, *, base_dir: str | None = None, use_mt5: bool = False, mt5_config: dict[str, Any] | None = None) -> None:
        self.base_dir = base_dir
        self.use_mt5 = use_mt5
        self.mt5_config = mt5_config or {}
        self._store = CandleStore(base_dir)

    def load_candles(self, symbol: str, timeframe: str) -> pd.DataFrame:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        if self.use_mt5:
            df = self._load_mt5(symbol, timeframe)
            if df is not None and not df.empty:
                return df
            logger.warning("MT5 read failed; falling back to CandleStore")
        df = self._store.load(symbol, timeframe)
        if df is None or df.empty:
            raise FileNotFoundError(f"No candle data for {symbol} {timeframe}")
        return self._normalize(df)

    def recent_bars(self, symbol: str, timeframe: str, *, days: int | None = None) -> pd.DataFrame:
        df = self.load_candles(symbol, timeframe)
        if days is None:
            return df
        mx = pd.Timestamp(df.index.max())
        if mx.tzinfo is None:
            mx = mx.tz_localize("UTC")
        cutoff = mx - timedelta(days=days)
        return df.loc[df.index >= cutoff]

    def iter_closed_bars(self, df: pd.DataFrame, *, start_index: int = 60):
        """Yield (index, bar) chronologically — only past/current bar, no future."""
        for i in range(start_index, len(df)):
            yield i, df.iloc[i]

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if not isinstance(out.index, pd.DatetimeIndex):
            if "time" in out.columns:
                out = out.set_index("time")
        out.index = pd.to_datetime(out.index, utc=True)
        return out.sort_index()

    def _load_mt5(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        try:
            from tradingbot.ml.data.mt5_fetch import fetch_candles

            bars = 5000 if not self.mt5_config.get("days") else min(100_000, int(self.mt5_config["days"]) * 288)
            return fetch_candles(self.mt5_config, symbol, timeframe, bars=bars)
        except Exception as exc:
            logger.warning("MT5 read-only fetch failed: %s", exc)
            return None
