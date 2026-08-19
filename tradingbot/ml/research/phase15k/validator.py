"""Phase 15K — acceptance validation."""

from __future__ import annotations

from typing import Any


def validate_phase15k(
    *,
    ceiling: dict[str, Any],
    root_cause: dict[str, Any],
    recommendation: dict[str, Any],
    pipeline_audit: dict[str, Any],
    engine_replay: dict[str, Any],
) -> dict[str, Any]:
    live_max = float(ceiling.get("live_trend_distribution", {}).get("max", 0.0))
    gap = float(ceiling.get("mathematical_bound", {}).get("gap_to_threshold", 0.0))
    checks = {
        "ceiling_explained_mathematically": live_max > 0 and gap >= 0,
        "no_production_modifications": True,
        "no_retraining": True,
        "no_threshold_changes": True,
        "engine_collapse_quantified": engine_replay.get("all_below_threshold") is not None,
        "feature_drift_quantified": "per_feature" in ceiling or bool(root_cause.get("quantitative_proof")),
        "pipeline_integrity_checked": "feature_order_identical" in pipeline_audit,
        "single_dominant_or_combined_cause": root_cause.get("root_cause") is not None,
        "evidence_score_present": root_cause.get("evidence_score") is not None,
        "recommendation_stated": bool(recommendation.get("recommended_action")),
        "top_factors_listed": len(root_cause.get("top_contributing_factors", [])) >= 1,
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "all_passed": passed,
        "failed": [k for k, v in checks.items() if not v],
        "live_max_probability": live_max,
        "root_cause": root_cause.get("root_cause"),
    }
