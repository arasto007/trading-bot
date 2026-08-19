"""
آداپتر داده MT5 — خودکفا (MetaTrader5 مستقیم + کش parquet).

پیاده‌سازی: ports.IMarketDataProvider

این آداپتر دیگر به engine.data_pipeline / engine.storage وابسته نیست؛ خودش
داده را از MT5 می‌گیرد، نرمال می‌کند (domain.ohlcv) و در parquet کش می‌کند
(adapters.market_cache).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.market_cache import ParquetCache
from tradingbot.adapters.mt5_utils import (
    ensure_mt5_connected,
    is_mt5_already_connected,
    safe_release_mt5,
)
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.domain.models import MarketKey
from tradingbot.domain.ohlcv import normalize_ohlcv
from tradingbot.ports.market_data import IMarketDataProvider

logger = logging.getLogger(__name__)

#: نگاشت تایم‌فریم legacy ("15m") به ثابت MT5. (تنبل import می‌شود.)
_LEGACY_TF_NAMES = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}


def _mt5_timeframe(mt5: Any, legacy_tf: str) -> Any:
    name = _LEGACY_TF_NAMES.get(legacy_tf, "TIMEFRAME_M5")
    return getattr(mt5, name)


class Mt5MarketDataAdapter(IMarketDataProvider):
    """دریافت/کش OHLCV از MT5 — مستقل و بدون وابستگی به engine."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or load_legacy_config()
        data_dir = (
            self._config.get("data_dir")
            or self._config.get("DATA_DIR")
            or "data"
        )
        self._cache = ParquetCache(data_dir)
        self._fetch_bars = int(
            self._config.get("fetch_bars", self._config.get("FETCH_BARS", 3000))
        )
        self._mt5_ready = False
        self._holds_ipc_lock = False

    # ----------------------------------------------------------- connection
    async def ensure_connected(self) -> bool:
        """Attach-only MT5 connection — holds IPC lock for process lifetime."""
        if self._mt5_ready and is_mt5_already_connected():
            return True

        symbols = self._config.get("symbols") or self._config.get("SYMBOLS") or []
        hold_lock = not self._holds_ipc_lock

        connected = await asyncio.to_thread(
            ensure_mt5_connected,
            self._config,
            symbols=symbols,
            strict_account=False,
            attach_only=True,
            hold_lock=hold_lock,
        )
        if connected:
            self._mt5_ready = True
            self._holds_ipc_lock = True
            logger.info("MT5 attached (read-only, IPC lock held)")
        else:
            logger.error("MT5 attach failed — check terminal is open and logged in")
        return connected

    async def shutdown(self) -> None:
        """Release IPC lock without disconnecting the MT5 GUI session."""
        self._mt5_ready = False
        self._holds_ipc_lock = False
        await asyncio.to_thread(safe_release_mt5)

    # ------------------------------------------------------------- fetching
    @staticmethod
    def _bars_to_fetch(legacy_tf: str, requested: int, default: int) -> int:
        """برخی بروکرها برای D1/W1 با درخواست خیلی بزرگ خطا می‌دهند."""
        caps = {"1d": 400, "1w": 200, "mn1": 120}
        cap = caps.get(legacy_tf)
        base = min(default, max(requested, 80))
        return min(base, cap) if cap else base

    def _fetch_from_mt5(
        self, broker_symbol: str, legacy_tf: str, *, bars: int | None = None
    ) -> pd.DataFrame | None:
        """آخرین N کندل را از MT5 می‌گیرد و نرمال‌شده برمی‌گرداند."""
        import MetaTrader5 as mt5  # noqa: E402

        count = self._bars_to_fetch(
            legacy_tf, bars or self._fetch_bars, self._fetch_bars
        )
        rates = mt5.copy_rates_from_pos(
            broker_symbol, _mt5_timeframe(mt5, legacy_tf), 0, count
        )
        if rates is None or len(rates) == 0:
            logger.warning("MT5 returned no rates for %s:%s", broker_symbol, legacy_tf)
            return None
        from tradingbot.services.runtime_truth import mt5_rates_to_ohlcv_dataframe

        tf_min = 5 if legacy_tf.lower() in ("5m", "m5") else 60
        df = mt5_rates_to_ohlcv_dataframe(
            rates,
            timeframe_minutes=tf_min,
        )
        return df

    # ------------------------------------------------- IMarketDataProvider
    async def update_all(self, symbols: list[str], timeframes: list[str]) -> None:
        if not await self.ensure_connected():
            raise ConnectionError("MT5 not connected — cannot update market data")
        for symbol in symbols:
            broker_symbol = resolve_broker_symbol(symbol, self._config)
            for tf in timeframes:
                legacy_tf = to_legacy(tf)
                df = self._fetch_from_mt5(broker_symbol, legacy_tf)
                if df is not None and not df.empty:
                    self._cache.store(symbol, legacy_tf, df)

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        legacy_tf = to_legacy(market.timeframe)
        broker_symbol = resolve_broker_symbol(market.symbol, self._config)

        df = self._cache.load(market.symbol, legacy_tf)
        if df is None or df.empty:
            df = self._cache.load(broker_symbol, legacy_tf)

        if df is None or df.empty or len(df) < min(bars, 50):
            if not self._mt5_ready:
                logger.warning(
                    "MT5 not initialized — call ensure_connected() before get_ohlcv"
                )
                if df is None or df.empty:
                    return None
            else:
                fetched = self._fetch_from_mt5(broker_symbol, legacy_tf, bars=bars)
                if fetched is not None and not fetched.empty:
                    self._cache.store(market.symbol, legacy_tf, fetched)
                    df = fetched

        if df is None or df.empty:
            return None

        df = normalize_ohlcv(df)
        if len(df) > bars:
            df = df.iloc[-bars:]
        return df
