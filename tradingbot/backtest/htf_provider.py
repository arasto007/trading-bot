"""
تأمین HTF bias برای بک‌تست — بدون look-ahead.

bias از H4 ساختار بازار (بدون معامله H1)؛ فقط کندل‌های بسته‌شده قبل از entry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.data_source import BacktestMarketData
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.htf_bias import compute_htf_bias, htf_timeframe_for

_TF_BAR_DELTA = {
    "H1": pd.Timedelta(hours=1),
    "H4": pd.Timedelta(hours=4),
    "D1": pd.Timedelta(days=1),
}


class BacktestHtfBiasProvider:
    def __init__(
        self,
        config: BacktestConfig,
        legacy_config: dict[str, Any],
        *,
        symbol: str,
        entry_timeframe: str,
    ) -> None:
        self._cfg = config
        self._legacy = legacy_config
        self._symbol = symbol
        self._entry_tf = (entry_timeframe or "").upper()
        self._htf_tf = htf_timeframe_for(entry_timeframe)
        self._htf_df: pd.DataFrame | None = None
        self._pa_cfg = get_price_action_config(symbol, self._htf_tf)

    def needs_htf(self) -> bool:
        return self._entry_tf in ("M5", "M15", "H4")

    def load(self) -> None:
        if not self.needs_htf():
            return
        htf_cfg = BacktestConfig(
            symbols=[self._symbol],
            timeframe=self._htf_tf,
            days=self._cfg.days,
            start_offset_days=self._cfg.start_offset_days,
            use_cache=self._cfg.use_cache,
            cache_dir=self._cfg.cache_dir,
            warmup=60,
            signal_window=300,
        )
        ds = BacktestMarketData(htf_cfg, self._legacy)
        ds.load()
        self._htf_df = ds.frame(self._symbol)

    def bias_at(self, current_time: datetime | pd.Timestamp | None) -> int:
        if not self.needs_htf() or self._htf_df is None or self._htf_df.empty:
            return 0
        if current_time is None:
            return 0
        ts = current_time
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()

        htf = self._htf_df
        bar_delta = _TF_BAR_DELTA.get(self._htf_tf, pd.Timedelta(hours=4))
        close_times = htf.index + bar_delta
        mask = close_times <= pd.Timestamp(ts)
        closed = htf.loc[mask]
        if len(closed) < 60:
            return 0
        return compute_htf_bias(closed, self._pa_cfg)
