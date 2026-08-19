"""Phase 20B — live stabilization configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_STRIDE = 5
OBSERVATION_DAYS = 365
MIN_LIVE_TRADES = 10

# Stability gates (observed metrics only)
GATE_MIN_PF = 1.0
GATE_MIN_EXPECTANCY = 0.0
GATE_MAX_DD_R = 20.0
GATE_MAX_REJECTION_RATE = 0.25
GATE_MIN_HEALTH_SCORE = 60.0
GATE_MAX_LATENCY_P95_MS = 100.0
GATE_MIN_FILTER_RETENTION = 0.15

CAPITAL_RISK_LEVELS = (0.01, 0.02, 0.03, 0.05)

VERDICTS = (
    "LIVE_SYSTEM_STABLE",
    "LIVE_SYSTEM_UNSTABLE",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase20b"


def phase20a_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase20a"
