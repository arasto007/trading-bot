"""Phase 15K — configuration and shared metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_SEED = 42
DEFAULT_STRIDE = 15
TRAIN_PROB_SAMPLE_SIZE = 5000
TREND_THRESHOLD = 0.40
OBSERVED_CEILING = 0.379
PSI_CRITICAL = 0.25
DRIFT_CEILING_CORR = 0.5

VALID_ROOT_CAUSES = frozenset({
    "FEATURE_DRIFT",
    "TRAIN_INFERENCE_MISMATCH",
    "MODEL_SATURATION",
    "LABEL_SHIFT",
    "PIPELINE_CORRUPTION",
    "PROBABILITY_CALIBRATION_LIMIT",
    "COMBINED_CAUSE",
})

VALID_RECOMMENDATIONS = frozenset({
    "RETRAIN_MODEL",
    "FIX_FEATURE_PIPELINE",
    "RECALIBRATE_PROBABILITIES",
    "FREEZE_AND_ACCEPT_LIMIT",
    "HYBRID_MODEL_ENSEMBLE",
})

HYPOTHESES = (
    "H1_feature_scaling_mismatch",
    "H2_feature_drift",
    "H3_label_distribution_shift",
    "H4_model_saturation",
    "H5_probability_calibration_mismatch",
    "H6_train_inference_preprocessing_mismatch",
    "H7_class_imbalance",
    "H8_feature_interaction_loss",
    "H9_silent_nan_injection",
    "H10_threshold_misalignment",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase15k"


def dist_stats(values: list[float] | np.ndarray) -> dict[str, float]:
    if len(values) == 0:
        return {"count": 0, "mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0,
                "max": 0.0, "p95": 0.0, "p99": 0.0}
    arr = np.asarray(values, dtype=float)
    return {
        "count": int(len(arr)),
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "std": round(float(np.std(arr)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
        "p99": round(float(np.percentile(arr, 99)), 6),
    }


def psi_score(expected: np.ndarray, actual: np.ndarray, *, bins: int = 10) -> float:
    eps = 1e-6
    if len(expected) < 2 or len(actual) < 2:
        return 0.0
    lo = min(float(np.min(expected)), float(np.min(actual)))
    hi = max(float(np.max(expected)), float(np.max(actual))) + eps
    breaks = np.linspace(lo, hi, bins + 1)
    e_hist, _ = np.histogram(expected, bins=breaks)
    a_hist, _ = np.histogram(actual, bins=breaks)
    e_pct = e_hist / max(e_hist.sum(), 1) + eps
    a_pct = a_hist / max(a_hist.sum(), 1) + eps
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(y) < 2:
        return 0.0
    if float(np.std(x)) < 1e-12 or float(np.std(y)) < 1e-12:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])
