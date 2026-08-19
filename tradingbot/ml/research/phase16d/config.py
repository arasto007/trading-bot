"""Phase 16D — feature ceiling expansion study configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_STRIDE = 5
DEFAULT_SEED = 42
RF_THRESHOLD = 0.40
CORRELATION_REDUNDANT = 0.85
LOW_MI_THRESHOLD = 0.005

VERDICTS = (
    "FEATURE_SET_LIMITED",
    "MODEL_LIMITED",
    "LABEL_LIMITED",
    "MULTIPLE_LIMITATIONS",
    "UNKNOWN",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase16d"
