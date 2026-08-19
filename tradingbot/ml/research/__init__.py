"""ML research intelligence layer — Phase 7.3."""

from __future__ import annotations

from tradingbot.ml.research.experiment_runner import ExperimentConfig, ResearchExperimentRunner
from tradingbot.ml.research.experiment_tracker import ExperimentTracker, experiments_path
from tradingbot.ml.research.feature_research import FeatureResearchAnalyzer
from tradingbot.ml.research.hypothesis import HypothesisManager
from tradingbot.ml.research.model_comparison import ModelComparisonEngine
from tradingbot.ml.research.ranking import ResearchRanker
from tradingbot.ml.research.reports import ResearchReportGenerator, experiment_report_path
from tradingbot.ml.research.reproducibility import build_reproducibility_bundle, dataset_fingerprint, verify_reproducibility
from tradingbot.ml.research.schema import ExperimentRecord, Hypothesis

__all__ = [
    "ExperimentConfig",
    "ExperimentRecord",
    "ExperimentTracker",
    "FeatureResearchAnalyzer",
    "Hypothesis",
    "HypothesisManager",
    "ModelComparisonEngine",
    "ResearchExperimentRunner",
    "ResearchRanker",
    "ResearchReportGenerator",
    "build_reproducibility_bundle",
    "dataset_fingerprint",
    "experiment_report_path",
    "experiments_path",
    "verify_reproducibility",
]
