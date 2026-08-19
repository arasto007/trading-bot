"""Phase 15C — monitoring configuration and paths."""

from __future__ import annotations

from pathlib import Path

EXPECTED_DATASET_FINGERPRINT = "70b38325ee1c7e1e"
HEALTH_CHECK_EVERY_N_BARS = 50
LATENCY_ALERT_MS = 100.0
FALLBACK_RATE_ALERT = 0.05
CONFIDENCE_COLLAPSE_THRESHOLD = 0.35


def live_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import ml_root
    return ml_root(base_dir) / "live"


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _reports
    return _reports(base_dir) / "phase15c"
