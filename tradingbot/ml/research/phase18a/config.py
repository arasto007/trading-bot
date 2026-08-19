"""Phase 18A — shadow validation configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
STRIDES = (1, 5)

MIN_AGREEMENT_RATE = 0.80
MAX_LATENCY_OVERHEAD = 0.10
MAX_RANDOM_DIVERGENCE = 0.30
RF_THRESHOLD = 0.40

VERDICTS = (
    "SHADOW_FAILED",
    "SHADOW_NEEDS_REVIEW",
    "READY_FOR_CONTROLLED_LIVE",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase18a"
