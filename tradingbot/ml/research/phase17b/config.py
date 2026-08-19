"""Phase 17B — offline RF+Top5 retrain lab configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_SEED = 42
DEFAULT_DAYS = 365
DEFAULT_TRAIN_DAYS = 1095  # 3y chronological research window (not full history)
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
RF_THRESHOLD = 0.40
LABEL_KEY = "label_a_tp_before_sl"

# Frozen trend_rf_v40 hyperparameters (conservative — no aggressive tuning).
RF_N_ESTIMATORS = 120
RF_MAX_DEPTH = 6
RF_MIN_SAMPLES_LEAF = 10

TOP5_FEATURES = (
    "adx_acceleration",
    "swing_efficiency",
    "fractal_dimension_proxy",
    "trend_age",
    "ema_curvature",
)

VERDICTS = (
    "REJECT_NEW_RF",
    "PROMISING_NEEDS_WORK",
    "READY_FOR_SHADOW_BUNDLE",
)

# Acceptance thresholds (quantitative).
MIN_CEILING_DELTA = 0.05
MIN_THROUGHPUT_RATIO = 2.0
MIN_NEW_ACTIONABLE = 3
MAX_PF_DETERIORATION = 0.15
MAX_LATENCY_P95_MS = 250.0
RANGE_IDENTICAL_TOLERANCE = 0


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase17b"
