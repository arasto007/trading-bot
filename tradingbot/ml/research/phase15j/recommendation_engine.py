"""Phase 15J — read-only next-phase recommendations."""

from __future__ import annotations

from typing import Any

_RECOMMENDATIONS = {
    "ENGINE_COLLAPSE": {
        "next_phase": "Phase15K",
        "title": "Engine Investigation",
        "focus": "Rule gate (evaluate_variant_a) and ML threshold on frozen trend_rf_v40 bundle",
    },
    "FEATURE_DRIFT": {
        "next_phase": "Phase15K",
        "title": "Feature Alignment",
        "focus": "Align live unified features with training feature_order; investigate PSI-flagged columns",
    },
    "PROBABILITY_COLLAPSE": {
        "next_phase": "Phase15K",
        "title": "Probability Distribution Review",
        "focus": "Frozen RF predict_proba ceiling vs TREND_ML_THRESHOLD 0.40",
    },
    "DECISION_GATE": {
        "next_phase": "Phase15K",
        "title": "Decision Policy Review",
        "focus": "ConfidenceEngine compression on TREND path at DecisionPolicy 14.1",
    },
    "CALIBRATION": {
        "next_phase": "Phase15K",
        "title": "Calibration Review",
        "focus": "Platt calibration gate on trend engine outputs",
    },
    "CONFIDENCE_MAPPING": {
        "next_phase": "Phase15K",
        "title": "Confidence Mapping Review",
        "focus": "Phase 15H mapper behavior on trend_rf_v40 calibrated confidence",
    },
    "RISK_GATE": {
        "next_phase": "Phase15K",
        "title": "Risk Review",
        "focus": "MIN_CONFIDENCE_FOR_RISK impact on trend mapped confidence",
    },
    "QUALITY_GATE": {
        "next_phase": "Phase15K",
        "title": "Quality Review",
        "focus": "TradeQualityEngine regime scoring for TREND bars",
    },
    "KERNEL_MAPPING": {
        "next_phase": "Phase15K",
        "title": "Kernel Mapping Review",
        "focus": "UnifiedSignal to TradingSignal coercion on trend path",
    },
    "MULTIPLE": {
        "next_phase": "Phase15K",
        "title": "Multi-Stage Trend Investigation",
        "focus": "Prioritize ENGINE and upstream stages before downstream gates",
    },
}


def build_recommendation(root_cause_report: dict[str, Any]) -> dict[str, Any]:
    root = str(root_cause_report.get("root_cause", "ENGINE_COLLAPSE"))
    rec = _RECOMMENDATIONS.get(root, _RECOMMENDATIONS["ENGINE_COLLAPSE"])
    return {
        "phase": "15J",
        "root_cause": root,
        "recommendation": rec,
        "modifies_production": False,
        "retrain_required": False,
        "phase15k_investigation": rec["focus"],
        "statement": (
            f"Phase15J is read-only. Next step: {rec['next_phase']} — {rec['title']}. "
            f"{rec['focus']}"
        ),
    }
