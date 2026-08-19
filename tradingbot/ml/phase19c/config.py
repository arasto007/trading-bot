"""Phase 19C — safe profitability upgrade configuration."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
BACKTEST_WINDOWS_DAYS = (365, 730, 1095)
MONTE_CARLO_SIMS = 1000
DEFAULT_SEED = 42
WALK_FORWARD_FOLDS = 4

TARGET_PF = 1.30
TARGET_EXPECTANCY = 0.15
TARGET_MAX_DD = 20.0

# Environment variable names
ENV_ENABLE_RSI = "ENABLE_RSI_FILTER"
ENV_ENABLE_ADX = "ENABLE_ADX_FILTER"
ENV_RSI_MIN = "RSI_MIN"
ENV_RSI_MAX = "RSI_MAX"
ENV_ADX_MIN = "ADX_MIN"
ENV_ADX_MAX = "ADX_MAX"

VERDICTS = (
    "IMPROVEMENT_ACCEPTED",
    "ROLLBACK_REQUIRED",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase19c"
