"""Phase 22G — single recommended fix (evidence-based, no implementation)."""

from __future__ import annotations

from typing import Any


def build_recommended_fix(bottleneck: dict, prev: dict) -> dict[str, Any]:
    """
    ONE fix: Align health gate + calibration with active trend engine (v41).

    Evidence:
    - TREND_MODEL_VERSION defaults v41; inference uses v41 weights
    - health_gate validates v40 checksum/features only (health_gate.py)
    - recovered_calibration fits Platt on trend_rf_v40 hardcoded
    - Mismatch can cause suboptimal calibration gate independent of 22D Top5 fix
    - Low risk: read-only alignment, no threshold tuning
    """
    fix = {
        "id": "22G-001",
        "title": "Align health gate and Platt calibration with active trend engine (v41)",
        "type": "engineering_bugfix",
        "not_threshold_tuning": True,
        "files_to_change": [
            "tradingbot/ml/integration/health_gate.py",
            "tradingbot/ml/integration/recovered_calibration.py",
        ],
        "problem": (
            "Env selects trend_rf_v41 for inference but health validation and calibration "
            "still target trend_rf_v40 artifacts. Code verified in health_gate.run_pre_decision_health "
            "and recovered_calibration.build_production_calibrated_adapter."
        ),
        "proposed_change": (
            "Use resolve_active_trend_engine_id() / resolve_bundle_version() in health_gate "
            "and calibration builder so checksum, feature_order, and Platt fit reference the "
            "same bundle that executes."
        ),
        "predicted_impact": {
            "trade_frequency": "+5% to +15% actionable signals (calibration gate may promote more valid v41 signals)",
            "profit_factor": "Unknown until Dataset A re-run; removes calibration mismatch artifact",
            "expectancy": "Neutral to +0.05R if prior blocks were false negatives",
            "drawdown": "No increase expected — not relaxing RiskGate",
            "buy_sell_balance": "Should improve BUY count if v41 BUY probs were miscalibrated vs v40 Platt",
            "implementation_risk": "LOW — no strategy logic change",
            "validation_time_dataset_a_min": 15,
        },
        "why_not_other_fixes": {
            "lower_range_buy_threshold": "Threshold tuning — forbidden in 22G",
            "disable_riskgate": "Safety violation",
            "decision_policy_min_confidence": "Threshold tuning",
            "more_backtesting": "22F framework exists; fix engine alignment first",
        },
    }

    return {
        "phase": "22G",
        "ready": True,
        "fix": fix,
        "evidence_bottleneck": bottleneck.get("first_destroyer"),
        "note": "If calibration alignment does not move Dataset A metrics, next investigation: range P(win) distribution vs 0.55 buy threshold (market property, not code bug).",
    }
