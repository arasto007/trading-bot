"""Phase 16A — alignment configuration."""

from __future__ import annotations

from pathlib import Path

# Phase 15Z shifted features — healthy features pass through unchanged.
SHIFTED_FEATURES: tuple[str, ...] = (
    "macd_histogram",
    "ema20_slope",
    "ema50_slope",
    "breakout_distance",
)

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_CALIBRATION_DAYS = 365
DEFAULT_QUANTILE_KNOTS = 101
DEFAULT_SEED = 42
RF_THRESHOLD = 0.40


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase16a"
