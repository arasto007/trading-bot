"""Phase 16B — kernel validation configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_WINDOWS = (90, 180, 365)
DEFAULT_STRIDES = (5, 10)
DEFAULT_SEED = 42
DEFAULT_WARMUP = 350
RF_THRESHOLD = 0.40
RANGE_ENGINE_ID = "phase9_9"
TREND_ENGINE_ID = "trend_rf_v40"
MAX_PSI_AFTER_ALIGN = 1.0
MAX_SIGNAL_INFLATION_PCT = 20.0


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase16b"
