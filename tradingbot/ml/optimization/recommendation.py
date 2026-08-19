"""Build optimization recommendations from sweep results."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.optimization.filters import FilterRecommendation
from tradingbot.ml.optimization.schema import OptimizationResult, PolicyConfig
from tradingbot.ml.optimization.threshold import ThresholdCandidate
from tradingbot.ml.optimization.weights import WeightCandidate


def build_recommendation_payload(
    result: OptimizationResult,
    *,
    threshold_candidate: ThresholdCandidate | None = None,
    weight_candidate: WeightCandidate | None = None,
    filters: FilterRecommendation | None = None,
    status: str = "READY FOR REVIEW",
) -> dict[str, Any]:
    rec = result.recommended_config
    improvement = round(result.expected_R_after - result.expected_R_before, 4)
    disabled = list(rec.disabled_sessions) + list(rec.disabled_regimes)
    return {
        "timestamp": result.timestamp,
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "status": status,
        "best_threshold": rec.threshold,
        "best_ml_weight": rec.ml_weight,
        "best_rule_weight": rec.rule_weight,
        "disabled_filters": disabled,
        "disabled_sessions": rec.disabled_sessions,
        "disabled_regimes": rec.disabled_regimes,
        "expected_R_improvement": improvement,
        "expected_R_before": result.expected_R_before,
        "expected_R_after": result.expected_R_after,
        "confidence_change": result.confidence_change,
        "sample_size": result.sample_size,
        "current_config": result.current_config.to_dict(),
        "recommended_config": rec.to_dict(),
        "warnings": result.warnings,
        "threshold_sweep_best": threshold_candidate.__dict__ if threshold_candidate else None,
        "weight_sweep_best": weight_candidate.__dict__ if weight_candidate else None,
        "filter_analysis": filters.to_dict() if filters else {},
    }
