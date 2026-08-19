"""Phase 20C — real broker execution validation configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"

# Minimum successful broker fills required for LIVE_VALIDATED
MIN_REAL_TRADES = 5

VERDICTS = (
    "WAITING_FOR_REAL_TRADES",
    "LIVE_VALIDATED",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase20c"


def phase20a_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase20a"
