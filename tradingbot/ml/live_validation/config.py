"""Phase 15D — configuration and paths."""

from __future__ import annotations

from pathlib import Path

EXPECTED_DATASET_FINGERPRINT = "70b38325ee1c7e1e"
DEFAULT_WARMUP_BARS = 350
DEFAULT_STRIDE = 10
LATENCY_MEAN_TARGET_MS = 20.0
LATENCY_P95_TARGET_MS = 50.0
HEALTH_EVERY_N_BARS = 50


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase15d"


def shadow_live_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import ml_root
    return ml_root(base_dir) / "live" / "phase15d"
