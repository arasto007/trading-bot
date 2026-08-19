"""
کش parquet برای داده بازار — جایگزین سبک Storage.load_data/store_data.

قالب فایل دقیقاً مانند قبل است: `{data_dir}/{symbol}_{timeframe}.parquet`
تا کش‌های موجود همچنان خوانده شوند.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)


class ParquetCache:
    """ذخیره/بازیابی DataFrame بازار در فایل‌های parquet."""

    def __init__(self, data_dir: str = "data") -> None:
        self._dir = data_dir

    def path(self, symbol: str, timeframe: str) -> str:
        return os.path.join(self._dir, f"{symbol}_{timeframe}.parquet")

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """در صورت وجود کش، DataFrame را برمی‌گرداند؛ وگرنه None."""
        file_path = self.path(symbol, timeframe)
        if not os.path.exists(file_path):
            return None
        try:
            df = pd.read_parquet(file_path)
            logger.debug("Cache hit %s:%s (%d rows)", symbol, timeframe, len(df))
            return df
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cache read failed %s:%s — %s", symbol, timeframe, exc)
            return None

    def store(self, symbol: str, timeframe: str, df: pd.DataFrame | None) -> None:
        """DataFrame را در کش می‌نویسد (خالی/None نادیده گرفته می‌شود)."""
        if df is None or df.empty:
            return
        try:
            os.makedirs(self._dir, exist_ok=True)
            df.to_parquet(self.path(symbol, timeframe), index=True)
            logger.debug("Cache store %s:%s (%d rows)", symbol, timeframe, len(df))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cache write failed %s:%s — %s", symbol, timeframe, exc)
