"""Phase 15J — configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_SEED = 42
DEFAULT_STRIDE = 15
TREND_ENGINE_ID = "trend_rf_v40"
ENGINE_COLLAPSE_THRESHOLD = 0.05
FEATURE_DRIFT_PSI_THRESHOLD = 0.25
VALID_STOP_STAGES = frozenset({
    "ENGINE", "DECISION", "CALIBRATION", "MAPPING", "RISK", "QUALITY", "KERNEL", "NONE",
})
VALID_ROOT_CAUSES = frozenset({
    "ENGINE_COLLAPSE", "FEATURE_DRIFT", "PROBABILITY_COLLAPSE", "DECISION_GATE",
    "CALIBRATION", "CONFIDENCE_MAPPING", "RISK_GATE", "QUALITY_GATE",
    "KERNEL_MAPPING", "MULTIPLE",
})


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase15j"
