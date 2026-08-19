"""Phase 15F — DecisionPolicy and calibration gate audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.confidence_engine.calibration_policy import DEFAULT_CALIBRATION_POLICY
from tradingbot.ml.decision_engine.decision_policy import DEFAULT_MIN_CONFIDENCE, DecisionPolicy
from tradingbot.ml.integration.recovered_calibration import calibration_status
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy


def audit_decision_policy(*, base_dir: str | None = None) -> dict[str, Any]:
    policy_14_6 = load_phase14_6_policy(base_dir)
    cal_status = calibration_status(base_dir)

    return {
        "decision_policy_14_1": {
            "min_confidence": DEFAULT_MIN_CONFIDENCE,
            "applies_to": "compressed decision.confidence (model * regime_strength * market_quality)",
            "comparison_field": "final_confidence after compression",
        },
        "calibration_policy_14_2a_default": {
            "min_calibrated_confidence": DEFAULT_CALIBRATION_POLICY.min_calibrated_confidence,
            "applies_to": "calibrated_value after ConfidenceCalibrator",
        },
        "phase14_6_recommended": {
            "calibration_method": policy_14_6.get("calibration_method"),
            "confidence_threshold": policy_14_6.get("confidence_threshold"),
            "applies_to": "Platt calibrated_value",
        },
        "production_prior_bug": {
            "used_heuristic_14_2a": True,
            "missing_platt": True,
            "threshold_mismatch": (
                DEFAULT_CALIBRATION_POLICY.min_calibrated_confidence
                != float(policy_14_6.get("confidence_threshold", 0.30))
            ),
            "mixed_raw_vs_calibrated": (
                "DecisionPolicy gates compressed raw at 0.55; "
                "CalibratedDecisionAdapter gates calibrated at 0.55 — "
                "production skipped Platt recovery from Phase 14.6"
            ),
        },
        "recovery": cal_status,
        "verdict": (
            "Reconnect Phase 14.6 Platt via build_production_calibrated_adapter; "
            f"use threshold {policy_14_6.get('confidence_threshold')} on calibrated output"
        ),
    }
