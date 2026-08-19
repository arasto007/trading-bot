"""Phase 19D — final production certification configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_STRIDE = 5
BACKTEST_WINDOWS_DAYS = (365, 730, 1095)
CAPITAL_LEVELS = (200, 500, 1000, 5000)
MONTE_CARLO_SIMS = 2000
DEFAULT_SEED = 42
WALK_FORWARD_FOLDS = 4

VERDICTS = (
    "NOT_APPROVED_FOR_LIVE",
    "APPROVED_FOR_SMALL_CAPITAL",
    "APPROVED_FOR_FULL_PRODUCTION",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase19d"
