"""Phase 15K — ceiling remediation recommendation (no actions)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15k.config import VALID_RECOMMENDATIONS


_MAP = {
    "FEATURE_DRIFT": "FIX_FEATURE_PIPELINE",
    "TRAIN_INFERENCE_MISMATCH": "FIX_FEATURE_PIPELINE",
    "PIPELINE_CORRUPTION": "FIX_FEATURE_PIPELINE",
    "MODEL_SATURATION": "RETRAIN_MODEL",
    "LABEL_SHIFT": "RETRAIN_MODEL",
    "PROBABILITY_CALIBRATION_LIMIT": "RECALIBRATE_PROBABILITIES",
    "COMBINED_CAUSE": "HYBRID_MODEL_ENSEMBLE",
}


def build_ceiling_recommendation(root_cause_report: dict[str, Any]) -> dict[str, Any]:
    root = str(root_cause_report.get("root_cause", "PROBABILITY_CALIBRATION_LIMIT"))
    action = _MAP.get(root, "FREEZE_AND_ACCEPT_LIMIT")
    if root == "COMBINED_CAUSE":
        proof = root_cause_report.get("quantitative_proof", {})
        if proof.get("live_max_probability", 0) < 0.40 and proof.get("training_max_probability", 0) > 0.5:
            action = "HYBRID_MODEL_ENSEMBLE"

    assert action in VALID_RECOMMENDATIONS

    alternatives: list[str] = []
    if action != "RECALIBRATE_PROBABILITIES":
        alternatives.append("RECALIBRATE_PROBABILITIES")
    if action != "FIX_FEATURE_PIPELINE":
        alternatives.append("FIX_FEATURE_PIPELINE")
    if action != "RETRAIN_MODEL":
        alternatives.append("RETRAIN_MODEL")

    return {
        "phase": "15K",
        "root_cause": root,
        "recommended_action": action,
        "alternatives_considered": alternatives,
        "implements_change": False,
        "rationale": _rationale(root, action, root_cause_report),
    }


def _rationale(root: str, action: str, report: dict[str, Any]) -> str:
    proof = report.get("quantitative_proof", {})
    return (
        f"Root cause {root} with live max {proof.get('live_max_probability')} vs threshold "
        f"{proof.get('threshold')}. Evidence score {report.get('evidence_score')}. "
        f"Recommended next phase action: {action} (recommendation only, no implementation)."
    )
