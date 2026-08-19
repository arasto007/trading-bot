"""Phase 10.2 — MT5 read-only live market adapter (copy_rates + symbol_info_tick only)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pandas as pd

from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.domain.models import MarketKey
from tradingbot.domain.ohlcv import exclude_forming_bar, normalize_ohlcv
from tradingbot.domain.session_logic import spread_pips_from_prices
from tradingbot.ml.data.mt5_fetch import fetch_candles

logger = logging.getLogger(__name__)


@dataclass
class ClosedCandle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "open": round(self.open, 6),
            "high": round(self.high, 6),
            "low": round(self.low, 6),
            "close": round(self.close, 6),
            "volume": float(self.volume),
            "spread": round(self.spread, 4) if self.spread is not None else None,
        }


class LiveMarketAdapter:
    """
    Read-only MT5 candle provider.

    Allowed: copy_rates, symbol_info_tick
  Forbidden: order_send, positions_get, trade requests (not used here)
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        config: dict[str, Any],
        *,
        candles: pd.DataFrame | None = None,
    ) -> None:
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.config = config
        self.broker_symbol = resolve_broker_symbol(self.symbol, config)
        self._candles = self._normalize(candles) if candles is not None else pd.DataFrame()
        self._seen_ts: set[str] = set()
        self._bar_index = -1
        self._last_spread: float | None = None

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        out = normalize_ohlcv(df.copy())
        if not isinstance(out.index, pd.DatetimeIndex):
            out.index = pd.to_datetime(out.index, utc=True)
        return out.sort_index()

    def load_history(self, *, days: int = 7, bars: int | None = None) -> int:
        """Fetch closed candles from MT5 for shadow walk-forward."""
        if self._candles is not None and not self._candles.empty and bars is None:
            closed = exclude_forming_bar(self._candles, min_rows=60)
            self._candles = closed if closed is not None else self._candles
            return len(self._candles)

        count = bars or min(100_000, max(500, days * 288))
        df = fetch_candles(self.config, self.symbol, self.timeframe, bars=count)
        if df is None or df.empty:
            raise RuntimeError(f"MT5 copy_rates returned no data for {self.broker_symbol}")

        if days > 0:
            mx = df.index.max()
            cutoff = mx - timedelta(days=days)
            df = df.loc[df.index >= cutoff]

        closed = exclude_forming_bar(df, min_rows=60)
        if closed is None or closed.empty:
            raise RuntimeError("Insufficient closed candles after excluding forming bar")
        self._candles = closed
        self._seen_ts.clear()
        self._bar_index = -1
        return len(self._candles)

    def refresh_tick_spread(self) -> float | None:
        """Read-only spread via symbol_info_tick."""
        try:
            import MetaTrader5 as mt5

            tick = mt5.symbol_info_tick(self.broker_symbol)
            if tick is None:
                return self._last_spread
            spread = spread_pips_from_prices(float(tick.ask), float(tick.bid), self.symbol)
            self._last_spread = spread
            return spread
        except Exception as exc:
            logger.warning("symbol_info_tick failed: %s", exc)
            return self._last_spread

    def iter_closed_bars(self, *, start_index: int = 80) -> Iterator[tuple[int, ClosedCandle]]:
        """Yield new closed candles chronologically without duplicates."""
        if self._last_spread is None:
            self.refresh_tick_spread()
        spread = self._last_spread
        for i in range(start_index, len(self._candles)):
            ts = pd.Timestamp(self._candles.index[i]).isoformat()
            if ts in self._seen_ts:
                continue
            self._seen_ts.add(ts)
            row = self._candles.iloc[i]
            yield i, ClosedCandle(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
                spread=spread,
            )

    def set_bar_index(self, index: int) -> None:
        self._bar_index = max(0, min(index, len(self._candles) - 1))

    @property
    def bar_index(self) -> int:
        return self._bar_index

    @property
    def candles(self) -> pd.DataFrame:
        return self._candles

    def slice_to_index(self, index: int) -> pd.DataFrame:
        return self._candles.iloc[: index + 1].copy()

    def poll_latest_closed(self) -> ClosedCandle | None:
        """Poll MT5 for latest closed bar (live mode)."""
        df = fetch_candles(self.config, self.symbol, self.timeframe, bars=500)
        if df is None or df.empty:
            return None
        closed = exclude_forming_bar(df, min_rows=60)
        if closed is None or closed.empty:
            return None
        self._candles = closed
        ts = pd.Timestamp(closed.index[-1]).isoformat()
        if ts in self._seen_ts:
            return None
        self._seen_ts.add(ts)
        self._bar_index = len(closed) - 1
        row = closed.iloc[-1]
        spread = self.refresh_tick_spread()
        return ClosedCandle(
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            spread=spread,
        )


class LiveMarketKernelAdapter:
    """Kernel IMarketDataProvider wrapper over LiveMarketAdapter."""

    def __init__(self, live: LiveMarketAdapter) -> None:
        self._live = live

    async def update_all(self, symbols: list[str], timeframes: list[str]) -> None:
        pass

    async def ensure_connected(self) -> bool:
        return True

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        if self._live.bar_index < 0:
            return None
        end = self._live.bar_index + 1
        start = max(0, end - bars)
        return self._live.candles.iloc[start:end].copy()

    def set_bar_index(self, index: int) -> None:
        self._live.set_bar_index(index)
