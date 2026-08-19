"""Phase 19B — research-only profitability optimization config."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
BACKTEST_DAYS = 1095
MONTE_CARLO_SIMS = 1000
DEFAULT_SEED = 42
WALK_FORWARD_FOLDS = 4

TARGET_PF = 1.30
TARGET_EXPECTANCY = 0.15
TARGET_MAX_DD = 20.0

VERDICTS = (
    "NO_SAFE_IMPROVEMENT_FOUND",
    "SAFE_IMPROVEMENTS_AVAILABLE",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase19b"
