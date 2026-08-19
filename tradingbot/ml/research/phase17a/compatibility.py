"""Phase 17A — compatibility with production stack (estimate only)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.architecture_matrix import ARCHITECTURES
from tradingbot.ml.research.phase17a.config import COMPAT_LEVELS, SYSTEM_COMPONENTS

# Component compatibility by model family.
# fully_compatible | minor_work | major_work
_FAMILY_COMPAT: dict[str, dict[str, str]] = {
    "random_forest": {
        "TradingKernel": "fully_compatible",
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "fully_compatible",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "minor_work",  # may need recalibration after retrain
        "ConfidenceMapping": "minor_work",
        "FeatureAlignment": "minor_work",  # extend aligner for new features if used
    },
    "sklearn_gbm": {
        "TradingKernel": "fully_compatible",
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "fully_compatible",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "minor_work",
        "ConfidenceMapping": "minor_work",
        "FeatureAlignment": "minor_work",
    },
    "lightgbm": {
        "TradingKernel": "minor_work",  # new dependency + adapter
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "fully_compatible",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "minor_work",
        "ConfidenceMapping": "minor_work",
        "FeatureAlignment": "minor_work",
    },
    "xgboost": {
        "TradingKernel": "minor_work",
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "fully_compatible",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "minor_work",
        "ConfidenceMapping": "minor_work",
        "FeatureAlignment": "minor_work",
    },
    "stack_rf_gbm": {
        "TradingKernel": "major_work",
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "minor_work",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "major_work",
        "ConfidenceMapping": "major_work",
        "FeatureAlignment": "minor_work",
    },
    "stack_rf_lgbm": {
        "TradingKernel": "major_work",
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "minor_work",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "major_work",
        "ConfidenceMapping": "major_work",
        "FeatureAlignment": "minor_work",
    },
    "stack_rf_xgb": {
        "TradingKernel": "major_work",
        "RiskGate": "fully_compatible",
        "DecisionPolicy": "minor_work",
        "Phase9_9": "fully_compatible",
        "RangeEngine": "fully_compatible",
        "Calibration": "major_work",
        "ConfidenceMapping": "major_work",
        "FeatureAlignment": "minor_work",
    },
}


def _worst(levels: list[str]) -> str:
    order = {lvl: i for i, lvl in enumerate(COMPAT_LEVELS)}
    return max(levels, key=lambda x: order.get(x, 0))


def build_compatibility_matrix() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for arch in ARCHITECTURES:
        family = arch["model_family"]
        base = dict(_FAMILY_COMPAT.get(family, {c: "major_work" for c in SYSTEM_COMPONENTS}))
        # Frozen status quo: no calibration/mapping/aligner changes.
        if arch["id"] == "A":
            for c in SYSTEM_COMPONENTS:
                base[c] = "fully_compatible"
        # Option B non-viable: FeatureAlignment would need major inventiveness.
        if arch["id"] == "B":
            base["FeatureAlignment"] = "major_work"
            base["TradingKernel"] = "major_work"
        # New features always touch FeatureAlignment at least minor.
        if arch["features"] == "current_plus_top5" and arch["id"] not in ("A", "B"):
            if base["FeatureAlignment"] == "fully_compatible":
                base["FeatureAlignment"] = "minor_work"

        overall = _worst(list(base.values()))
        rows.append({
            "id": arch["id"],
            "name": arch["name"],
            "components": base,
            "overall": overall,
            "range_engine_isolated": True,
            "phase9_9_untouched": True,
        })

    return {
        "phase": "17A",
        "components": list(SYSTEM_COMPONENTS),
        "levels": list(COMPAT_LEVELS),
        "rows": rows,
        "summary": {
            "fully_compatible_options": [r["id"] for r in rows if r["overall"] == "fully_compatible"],
            "minor_work_options": [r["id"] for r in rows if r["overall"] == "minor_work"],
            "major_work_options": [r["id"] for r in rows if r["overall"] == "major_work"],
            "range_always_isolated": True,
        },
    }
