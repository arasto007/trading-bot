"""
منبع داده‌ی بک‌تست — پیاده‌سازی IMarketDataProvider روی داده‌ی تاریخی.

- داده را از کش parquet می‌خواند؛ اگر نبود، از MT5 دریافت و کش می‌کند.
- اندیکاتورها **یک‌بار** روی کل سری محاسبه می‌شوند (causal — بدون look-ahead).
- یک cursor دارد که موتور بک‌تست آن را جلو می‌برد؛ get_ohlcv فقط داده تا cursor را برمی‌گرداند.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
from tradingbot.adapters.legacy_loader import ensure_legacy_path
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.backtest.config import BacktestConfig
from tradingbot.domain.models import MarketKey

logger = logging.getLogger(__name__)


def _mt5_timeframe(tf: str):
    import MetaTrader5 as mt5  # noqa: E402

    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping.get(tf.upper(), mt5.TIMEFRAME_M5)


class BacktestMarketData:
    """IMarketDataProvider برای بک‌تست (replay تاریخی)."""

    def __init__(
        self,
        config: BacktestConfig,
        legacy_config: dict[str, Any] | None = None,
    ) -> None:
        self._cfg = config
        self._legacy_config = legacy_config or {}
        self._indicators = TechnicalIndicatorEngine(legacy_config)
        self._frames: dict[str, pd.DataFrame] = {}
        self._broker_symbols: dict[str, str] = {}
        self._cursor = 0
        self._length = 0

    # ------------------------------------------------------------- data load
    def load(self) -> int:
        """دریافت/کش داده + محاسبه اندیکاتور. طول مشترک سری را برمی‌گرداند."""
        lengths = []
        for symbol in self._cfg.symbols:
            df = self._load_symbol(symbol)
            if df is None or df.empty:
                logger.warning("No data for %s — skipped", symbol)
                continue
            enriched = self._indicators.enrich_for_market(
                df, self._cfg.timeframe, self._broker_symbols.get(symbol, symbol)
            )
            enriched = enriched.dropna(subset=["open", "high", "low", "close"])
            enriched = self._apply_window_slice(enriched)
            self._frames[symbol] = enriched
            lengths.append(len(enriched))
            logger.info("Loaded %s: %d bars", symbol, len(enriched))
        self._length = min(lengths) if lengths else 0
        return self._length

    def _cache_path(self, symbol: str) -> str:
        os.makedirs(self._cfg.cache_dir, exist_ok=True)
        if self._cfg.days:
            off = int(getattr(self._cfg, "start_offset_days", 0) or 0)
            suffix = f"{symbol}_{self._cfg.timeframe}_{self._cfg.days}d"
            if off:
                suffix += f"_off{off}d"
            return os.path.join(self._cfg.cache_dir, f"{suffix}.parquet")
        return os.path.join(self._cfg.cache_dir, f"{symbol}_{self._cfg.timeframe}.parquet")

    def _load_symbol(self, symbol: str) -> pd.DataFrame | None:
        path = self._cache_path(symbol)
        if self._cfg.use_cache and os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                min_bars = self._min_bars_required()
                if len(df) >= min_bars * 0.9:
                    logger.info("Cache hit %s (%d bars)", symbol, len(df))
                    self._broker_symbols[symbol] = self._broker_symbols.get(symbol, symbol)
                    return df
            except Exception as e:
                logger.debug("Cache read failed %s: %s", symbol, e)
        return self._fetch_mt5(symbol, path)

    def _min_bars_required(self) -> int:
        if self._cfg.days:
            return max(self._cfg.warmup + 100, self._cfg.days * self._bars_per_day())
        return self._cfg.bars

    def _bars_per_day(self) -> int:
        tf = self._cfg.timeframe.upper()
        return {"M1": 1440, "M5": 288, "M15": 96, "M30": 48, "H1": 24, "H4": 6, "D1": 1}.get(tf, 96)

    def _apply_window_slice(self, df: pd.DataFrame) -> pd.DataFrame:
        """برش پنجره walk-forward: offset از انتهای سری + طول days."""
        if not self._cfg.days or df is None or df.empty:
            return df
        bpd = self._bars_per_day()
        window = int(self._cfg.days) * bpd
        offset = int(getattr(self._cfg, "start_offset_days", 0) or 0) * bpd
        if offset > 0:
            end = max(0, len(df) - offset)
            start = max(0, end - window)
            return df.iloc[start:end].copy()
        if len(df) > window:
            return df.iloc[-window:].copy()
        return df

    def _fetch_mt5(self, symbol: str, cache_path: str) -> pd.DataFrame | None:
        ensure_legacy_path()
        import MetaTrader5 as mt5  # noqa: E402
        from tradingbot.adapters.mt5_utils import ensure_mt5_connected

        if not ensure_mt5_connected(self._legacy_config, symbols=[symbol]):
            logger.error("MT5 not connected — cannot fetch %s", symbol)
            return None

        broker_symbol = resolve_broker_symbol(symbol, self._legacy_config)
        self._broker_symbols[symbol] = broker_symbol
        mt5.symbol_select(broker_symbol, True)
        tf = _mt5_timeframe(self._cfg.timeframe)
        if self._cfg.days:
            total_days = int(self._cfg.days) + int(getattr(self._cfg, "start_offset_days", 0) or 0)
            rates = self._fetch_mt5_chunked(mt5, broker_symbol, tf, total_days)
        else:
            rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, self._cfg.bars)
        if rates is None or len(rates) == 0:
            logger.error("MT5 returned no rates for %s (%s)", symbol, broker_symbol)
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        if "tick_volume" in df.columns and "volume" not in df.columns:
            df["volume"] = df["tick_volume"]
        df = df[["open", "high", "low", "close", "volume"]].copy()
        try:
            df.to_parquet(cache_path, index=True)
        except Exception as e:
            logger.debug("Cache write failed %s: %s", symbol, e)
        return df

    def _fetch_mt5_chunked(self, mt5, broker_symbol: str, tf: int, days: int):
        """دریافت تاریخچه طولانی M1 با چند درخواست پشت‌سرهم (سقف ~۹۰k هر بار)."""
        import numpy as np

        chunk_size = 90_000
        target = days * self._bars_per_day() + 500
        parts: list = []
        pos = 0
        while pos < target:
            count = min(chunk_size, target - pos)
            chunk = mt5.copy_rates_from_pos(broker_symbol, tf, pos, count)
            if chunk is None or len(chunk) == 0:
                break
            parts.append(chunk)
            got = len(chunk)
            logger.info("MT5 chunk pos=%d got=%d", pos, got)
            if got < count:
                break
            pos += got
        if not parts:
            return None
        merged = np.concatenate(parts)
        _, idx = np.unique(merged["time"], return_index=True)
        merged = merged[np.sort(idx)]
        bpd = max(self._bars_per_day(), 1)
        logger.info("MT5 chunked total %d bars (~%d days)", len(merged), len(merged) // bpd)
        return merged

    # --------------------------------------------------------------- cursor
    @property
    def length(self) -> int:
        return self._length

    def set_cursor(self, i: int) -> None:
        self._cursor = i

    @property
    def cursor(self) -> int:
        return self._cursor

    def current_bar(self, symbol: str) -> pd.Series | None:
        df = self._frames.get(symbol)
        if df is None or self._cursor >= len(df):
            return None
        return df.iloc[self._cursor]

    def current_time(self) -> Any:
        for df in self._frames.values():
            if self._cursor < len(df):
                return df.index[self._cursor]
        return None

    def frame(self, symbol: str) -> pd.DataFrame | None:
        return self._frames.get(symbol)

    def all_frames(self) -> dict[str, pd.DataFrame]:
        return dict(self._frames)

    def inject(self, frames: dict[str, pd.DataFrame]) -> int:
        """تزریق مستقیم فریم‌ها (برای تست) — بدون دریافت از MT5."""
        self._frames = dict(frames)
        self._length = min((len(df) for df in frames.values()), default=0)
        for sym in frames:
            self._broker_symbols.setdefault(sym, sym)
        return self._length

    # ----------------------------------------------- IMarketDataProvider API
    async def update_all(self, symbols: list[str], timeframes: list[str]) -> None:
        # موتور بک‌تست خودش cursor را کنترل می‌کند.
        return None

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        symbol = market.symbol if hasattr(market, "symbol") else str(market)
        return self.get_ohlcv_window(symbol, bars)

    def get_ohlcv_window(self, symbol: str, bars: int = 500) -> pd.DataFrame | None:
        df = self._frames.get(symbol)
        if df is None:
            return None
        end = min(self._cursor + 1, len(df))
        window = df.iloc[:end]
        limit = min(bars, self._cfg.signal_window) if bars else self._cfg.signal_window
        if len(window) > limit:
            window = window.tail(limit)
        return window
