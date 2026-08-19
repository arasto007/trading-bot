"""Phase 18C — pre-live verification configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"

VERDICTS = (
    "NOT_READY_FOR_MARKET_OPEN",
    "READY_FOR_MARKET_OPEN",
)

CHECK_STATUSES = ("PASS", "WARN", "FAIL")

REQUIRED_PACKAGES = (
    "numpy",
    "pandas",
    "sklearn",
    "joblib",
)

REQUIRED_DIRS = (
    "tradingbot",
    "tradingbot/ml",
    "tradingbot/ml/phase15a",
    "tradingbot/ml/phase17d",
    "data",
    "data/ml",
    "logs",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase18c"
