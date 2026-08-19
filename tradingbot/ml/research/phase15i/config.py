"""Phase 15I — configuration."""

from __future__ import annotations

from pathlib import Path

REGIME_PARITY_TARGET = 0.01
TREND_STABILITY_TOLERANCE = 0.05
MIN_RANGE_CONTRIBUTION = 0.05
DEFAULT_DAYS = 180
DEFAULT_SEED = 42
DEFAULT_STRIDE = 15
DEFAULT_WARMUP = 350
RANGE_ENGINE_ID = "phase9_9"
TREND_ENGINE_ID = "trend_rf_v40"


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase15i"
