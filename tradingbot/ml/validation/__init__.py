"""Offline model validation framework — Phase 4.1 (research only)."""

from __future__ import annotations

from tradingbot.ml.validation.calibration import CalibrationReport, run_calibration
from tradingbot.ml.validation.cross_validation import CrossValidationReport, run_cross_validation
from tradingbot.ml.validation.feature_ablation import FeatureAblationReport, run_feature_ablation
from tradingbot.ml.validation.regime_test import RegimeReport, run_regime_analysis
from tradingbot.ml.validation.report import ValidationSummary, run_full_validation
from tradingbot.ml.validation.robustness import RobustnessReport, run_robustness_tests
from tradingbot.ml.validation.threshold_optimizer import ThresholdOptimizer, optimize_threshold
from tradingbot.ml.validation.trading_simulator import TradingSimulation, run_trading_simulation
from tradingbot.ml.validation.walk_forward import WalkForwardReport, run_walk_forward

__all__ = [
    "CalibrationReport",
    "CrossValidationReport",
    "FeatureAblationReport",
    "RegimeReport",
    "RobustnessReport",
    "ThresholdOptimizer",
    "TradingSimulation",
    "ValidationSummary",
    "WalkForwardReport",
    "optimize_threshold",
    "run_calibration",
    "run_cross_validation",
    "run_feature_ablation",
    "run_full_validation",
    "run_regime_analysis",
    "run_robustness_tests",
    "run_trading_simulation",
    "run_walk_forward",
]
