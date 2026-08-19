"""Stress testing and failure simulation — Phase 7.1."""

from __future__ import annotations

from tradingbot.ml.stress.chaos_tests import (
    StressSandbox,
    simulate_extreme_drift,
    simulate_missing_features,
    simulate_model_failure,
    simulate_report_corruption,
)
from tradingbot.ml.stress.resilience import ResilienceEvaluator, resilience_report_path
from tradingbot.ml.stress.scenarios import ALL_SCENARIOS, FailureScenario
from tradingbot.ml.stress.simulator import StressResult, StressScenarioRunner

__all__ = [
    "ALL_SCENARIOS",
    "FailureScenario",
    "ResilienceEvaluator",
    "StressResult",
    "StressSandbox",
    "StressScenarioRunner",
    "resilience_report_path",
    "simulate_extreme_drift",
    "simulate_missing_features",
    "simulate_model_failure",
    "simulate_report_corruption",
]
