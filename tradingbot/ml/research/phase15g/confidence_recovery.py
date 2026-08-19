"""Phase 15G — single recovery recommendation (no implementation)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15g.config import RISK_GATE_THRESHOLD


def _classify_root_cause(
    *,
    ceiling: dict[str, Any],
    bundle_audit: dict[str, Any],
    research_vs: dict[str, Any],
    platt: dict[str, Any],
    equivalence: dict[str, Any],
    risk_sim: dict[str, Any],
) -> str:
    if bundle_audit.get("frozen_outputs_compressed"):
        if research_vs.get("primary_difference_source") == "trend_engine_model_mismatch":
            return "D"
    if ceiling.get("ceiling_below_risk_gate"):
        max_cal = float(ceiling.get("maximum_calibrated_confidence", 0))
        if max_cal > 0 and equivalence.get("empirical_frozen_threshold_when_research_passes"):
            return "A"
        return "D"
    return "D"


_OUTCOMES: dict[str, dict[str, str]] = {
    "A": {
        "outcome": "A",
        "title": "Threshold mapping only",
        "description": (
            "Frozen bundle Platt ceiling is below RiskGate 0.55 but research 0.30 "
            "maps to an equivalent frozen threshold. Adjust calibration gate reference "
            "or risk-input mapping — not model weights."
        ),
        "implementation": "none_in_15g",
    },
    "B": {
        "outcome": "B",
        "title": "Adapter rescales calibrated confidence",
        "description": (
            "Apply a monotone post-Platt rescale in integration adapter so frozen "
            "calibrated output aligns with research scale without retraining."
        ),
        "implementation": "none_in_15g",
    },
    "C": {
        "outcome": "C",
        "title": "Bundle serialization issue",
        "description": "Frozen bundle artifact may not match research fit checkpoint.",
        "implementation": "none_in_15g",
    },
    "D": {
        "outcome": "D",
        "title": "Platt fit mismatch",
        "description": (
            "Platt was fit on compressed decision raw values from frozen bundle; "
            "research refit engine produces different probability scale, yielding "
            "higher calibrated values (~0.77) vs frozen ceiling (~0.50)."
        ),
        "implementation": "none_in_15g",
    },
    "E": {
        "outcome": "E",
        "title": "Feature mismatch",
        "description": "Unified feature row differs between research refit path and frozen bundle inference.",
        "implementation": "none_in_15g",
    },
}


def build_recovery_recommendation(
    *,
    ceiling: dict[str, Any],
    bundle_audit: dict[str, Any],
    research_vs: dict[str, Any],
    platt: dict[str, Any],
    equivalence: dict[str, Any],
    risk_sim: dict[str, Any],
    production_replay: dict[str, Any],
) -> dict[str, Any]:
    outcome_key = _classify_root_cause(
        ceiling=ceiling,
        bundle_audit=bundle_audit,
        research_vs=research_vs,
        platt=platt,
        equivalence=equivalence,
        risk_sim=risk_sim,
    )
    rec = _OUTCOMES.get(outcome_key, _OUTCOMES["D"])

    max_cal = float(ceiling.get("maximum_calibrated_confidence", 0))
    risk_th = float(ceiling.get("risk_gate_requirement", RISK_GATE_THRESHOLD))
    first_accept = risk_sim.get("first_accepting_threshold")

    why_blocked = (
        f"Frozen bundle maximum calibrated confidence ({max_cal:.4f}) "
        f"is below RiskGate MIN_CONFIDENCE_FOR_RISK ({risk_th}). "
        f"Calibration emits {production_replay.get('calibration_actionable', 0)} actionable signals "
        f"but risk passes {production_replay.get('risk_quality_pass', 0)}."
    )

    if bundle_audit.get("frozen_outputs_compressed"):
        why_blocked += (
            " Frozen trend probabilities are compressed vs research refit engine "
            f"(mean diff {bundle_audit.get('comparison', {}).get('mean_diff', 0):.4f})."
        )

    return {
        "phase": "15G",
        "recommendation_only": True,
        "no_production_changes": True,
        "single_recommendation": rec,
        "why_frozen_never_reaches_riskgate": why_blocked,
        "mathematical_summary": {
            "max_frozen_calibrated": max_cal,
            "risk_gate_floor": risk_th,
            "gap": round(risk_th - max_cal, 6) if max_cal < risk_th else 0.0,
            "research_equiv_frozen_threshold": equivalence.get(
                "empirical_frozen_threshold_when_research_passes"
            ),
            "first_simulated_accepting_risk_threshold": first_accept,
        },
        "smallest_future_fix": rec["description"],
    }
