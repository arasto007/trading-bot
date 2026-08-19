"""Offline model improvement recommendations — Phase 7.4."""

from __future__ import annotations

from tradingbot.ml.improvement.analyzer import ImprovementAnalyzer
from tradingbot.ml.improvement.experiment_queue import ExperimentQueue
from tradingbot.ml.improvement.feature_optimizer import FeatureOptimizer
from tradingbot.ml.improvement.model_optimizer import ModelOptimizer
from tradingbot.ml.improvement.recommendation import (
    ReportBundle,
    experiment_queue_path,
    feature_improvement_path,
    improvement_recommendations_path,
)
from tradingbot.ml.improvement.regime_optimizer import RegimeOptimizer
from tradingbot.ml.improvement.reports import ImprovementReportGenerator
from tradingbot.ml.improvement.schema import ImprovementOpportunity
from tradingbot.ml.improvement.threshold_optimizer import ThresholdRecommendationEngine

__all__ = [
    "ExperimentQueue",
    "FeatureOptimizer",
    "ImprovementAnalyzer",
    "ImprovementOpportunity",
    "ImprovementReportGenerator",
    "ModelOptimizer",
    "RegimeOptimizer",
    "ReportBundle",
    "ThresholdRecommendationEngine",
    "experiment_queue_path",
    "feature_improvement_path",
    "improvement_recommendations_path",
]
