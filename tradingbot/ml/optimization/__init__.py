"""Shadow policy optimization — Phase 5.3 (offline recommendations only)."""

from __future__ import annotations

from tradingbot.ml.optimization.filters import AdaptiveFilterAnalyzer, FilterRecommendation
from tradingbot.ml.optimization.optimizer import ShadowPolicyOptimizer, load_current_policy
from tradingbot.ml.optimization.recommendation import build_recommendation_payload
from tradingbot.ml.optimization.reports import (
    load_shadow_optimization_report,
    shadow_optimization_path,
    write_shadow_optimization_report,
)
from tradingbot.ml.optimization.schema import OptimizationResult, PolicyConfig
from tradingbot.ml.optimization.threshold import ThresholdCandidate, ThresholdOptimizer
from tradingbot.ml.optimization.weights import WeightCandidate, WeightOptimizer

__all__ = [
    "AdaptiveFilterAnalyzer",
    "FilterRecommendation",
    "OptimizationResult",
    "PolicyConfig",
    "ShadowPolicyOptimizer",
    "ThresholdCandidate",
    "ThresholdOptimizer",
    "WeightCandidate",
    "WeightOptimizer",
    "build_recommendation_payload",
    "load_current_policy",
    "load_shadow_optimization_report",
    "shadow_optimization_path",
    "write_shadow_optimization_report",
]
