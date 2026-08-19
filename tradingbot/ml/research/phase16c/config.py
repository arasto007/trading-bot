"""Phase 16C — TREND throughput root analysis configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_STRIDE = 5
DEFAULT_SEED = 42
RF_THRESHOLD = 0.40
DECISION_MIN_CONFIDENCE = 0.55
SIMULATION_THRESHOLDS = (0.38, 0.39, 0.40)
TREND_ENGINE_ID = "trend_rf_v40"

# Confidence geometry clusters (rejected bars only)
CLUSTER_VERY_CLOSE = (0.38, 0.399)
CLUSTER_MEDIUM = (0.30, 0.38)
CLUSTER_FAR = (0.0, 0.30)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase16c"
