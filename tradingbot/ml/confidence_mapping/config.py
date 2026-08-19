"""Phase 15H — configuration."""

from __future__ import annotations

from pathlib import Path

PARITY_TARGET = 0.98
MAX_LATENCY_INCREASE = 0.05
RISK_GATE_THRESHOLD = 0.55
DEFAULT_DAYS = 180
DEFAULT_SEED = 42
DEFAULT_STRIDE = 10
DEFAULT_WARMUP = 350


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase15h"
