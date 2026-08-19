"""Phase 15G — frozen-bundle confidence analysis configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 180
DEFAULT_SEED = 42
DEFAULT_STRIDE = 5

RESEARCH_CALIB_THRESHOLD = 0.30
RISK_GATE_THRESHOLD = 0.55
SIMULATION_THRESHOLDS: tuple[float, ...] = (0.45, 0.50, 0.55, 0.60)

PLATT_CURVE_POINTS = 50


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase15g"
