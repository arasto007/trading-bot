"""Phase 17A — integrated TREND recovery blueprint configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_SEED = 42

# Evidence anchors from prior phases (read-only references).
EVIDENCE = {
    "phase16a_max_p_before": 0.394,
    "phase16a_max_p_after": 0.438,
    "phase16b_trend_actionable_365d": 1,
    "phase16b_range_kernel_365d": 203,
    "phase16c_rule_pass_rate": 0.861789,
    "phase16c_rf_pass": 1,
    "phase16c_kernel_trend": 0,
    "phase16d_frozen_max_p": 0.4377,
    "phase16d_surrogate_existing_max_p": 0.693235,
    "phase16d_surrogate_combined_max_p": 0.841964,
    "phase16d_throughput_delta": 118,
    "phase16d_high_mi_candidates": 10,
    "phase16d_primary": "A_missing_information",
    "phase16d_arch_score": 0.7,
    "phase16d_feature_score": 1.0,
    "phase16d_label_score": 0.0,
}

TOP5_FEATURES = (
    "adx_acceleration",
    "swing_efficiency",
    "fractal_dimension_proxy",
    "trend_age",
    "ema_curvature",
)

VERDICTS = (
    "KEEP_RF",
    "RF_PLUS_FEATURES",
    "LIGHTGBM_RECOMMENDED",
    "XGBOOST_RECOMMENDED",
    "STACKED_MODEL_RECOMMENDED",
    "OTHER",
)

COMPAT_LEVELS = ("fully_compatible", "minor_work", "major_work")

SYSTEM_COMPONENTS = (
    "TradingKernel",
    "RiskGate",
    "DecisionPolicy",
    "Phase9_9",
    "RangeEngine",
    "Calibration",
    "ConfidenceMapping",
    "FeatureAlignment",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase17a"
