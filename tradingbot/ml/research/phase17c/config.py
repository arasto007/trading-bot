"""Phase 17C — shadow bundle validation configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_SEED = 42
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
HORIZONS = (90, 180, 365)
WALK_FORWARD_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
MONTE_CARLO_SIMS = 5000
RF_THRESHOLD = 0.40

MIN_THROUGHPUT_RATIO = 2.0
MIN_CEILING_DELTA = 0.03
MAX_PF_DETERIORATION = 0.15
MAX_LATENCY_MEDIAN_MS = 50.0

VERDICTS = (
    "REJECT_CANDIDATE",
    "NEEDS_MORE_RESEARCH",
    "READY_FOR_PRODUCTION_BUNDLE",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase17c"
