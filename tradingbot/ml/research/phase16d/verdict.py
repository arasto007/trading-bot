"""Phase 16D — final verdict and next-phase recommendation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase16d.config import VERDICTS


def determine_verdict(
    model_limitation: dict[str, Any],
    info_gain: dict[str, Any],
    ceiling_sim: dict[str, Any],
    ceiling: dict[str, Any],
) -> str:
    scores = model_limitation.get("hypothesis_scores", {})
    a = scores.get("A_missing_information", 0.0)
    b = scores.get("B_rf_architecture", 0.0)
    c = scores.get("C_training_labels", 0.0)
    d = scores.get("D_combination", 0.0)

    high = [k for k, v in scores.items() if v >= 0.55]
    if len(high) >= 2 or d >= 0.6:
        return "MULTIPLE_LIMITATIONS"
    if a >= 0.65 and a > b and a > c:
        return "FEATURE_SET_LIMITED"
    if b >= 0.55 and b > a:
        return "MODEL_LIMITED"
    if c >= 0.55 and c > a:
        return "LABEL_LIMITED"
    if info_gain.get("candidates_outperform_existing") and ceiling_sim.get("candidates_add_information"):
        return "FEATURE_SET_LIMITED"
    if ceiling.get("confidence_saturates_due_to_lack_of_information"):
        return "FEATURE_SET_LIMITED"
    if max(scores.values(), default=0) < 0.35:
        return "UNKNOWN"
    return "MULTIPLE_LIMITATIONS"


def recommend_next_phase(verdict: str) -> str:
    mapping = {
        "FEATURE_SET_LIMITED": "Phase 17A — Offline Candidate Feature Validation Lab (shadow compute + A/B replay, still no production commit)",
        "MODEL_LIMITED": "Phase 17A — Alternative Model Architecture Shadow Study (gradient boosting / calibrated ensemble, offline only)",
        "LABEL_LIMITED": "Phase 17A — TREND Label Definition Audit (compare label variants v2 A–D impact on ceiling, read-only)",
        "MULTIPLE_LIMITATIONS": "Phase 17A — Integrated TREND Recovery Blueprint (feature + label + model shadow matrix, read-only)",
        "UNKNOWN": "Phase 17A — Extended Multi-Window TREND Ceiling Trace (730d + multi-symbol, read-only)",
    }
    return mapping.get(verdict, mapping["UNKNOWN"])


def build_final_report(
    *,
    verdict: str,
    symbol: str,
    timeframe: str,
    days: int,
    stride: int,
    ceiling: dict[str, Any],
    info_gain: dict[str, Any],
    ceiling_sim: dict[str, Any],
    model_limitation: dict[str, Any],
    gap: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "16D",
        "verdict": verdict,
        "recommended_next_phase": recommend_next_phase(verdict),
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "stride": stride,
        "read_only": True,
        "production_modified": False,
        "summary": {
            "frozen_max_probability": ceiling_sim.get("frozen_bundle", {}).get("max"),
            "surrogate_max_probability": ceiling_sim.get("theoretical_ceiling_with_candidates"),
            "expected_throughput_delta": ceiling_sim.get("expected_improvement", {}).get("throughput_delta_actionable"),
            "high_mi_candidates": info_gain.get("high_mi_candidate_count"),
            "information_gap_confirmed": gap.get("information_gap_confirmed"),
            "primary_limitation_hypothesis": model_limitation.get("primary_limitation"),
            "confidence_saturates": ceiling.get("confidence_saturates_due_to_lack_of_information"),
        },
        "no_fixes_applied": True,
    }
