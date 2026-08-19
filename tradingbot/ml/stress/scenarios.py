"""Failure scenario definitions — isolated and reversible."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureScenario(str, Enum):
    MISSING_FEATURE_DATA = "MISSING_FEATURE_DATA"
    STALE_FEATURE_DATA = "STALE_FEATURE_DATA"
    CORRUPTED_MODEL_FILE = "CORRUPTED_MODEL_FILE"
    INVALID_MODEL_METADATA = "INVALID_MODEL_METADATA"
    DATASET_HASH_MISMATCH = "DATASET_HASH_MISMATCH"
    FEATURE_DRIFT_SPIKE = "FEATURE_DRIFT_SPIKE"
    PERFORMANCE_DEGRADATION = "PERFORMANCE_DEGRADATION"
    LOW_SAMPLE_SIZE = "LOW_SAMPLE_SIZE"
    SPREAD_SPIKE = "SPREAD_SPIKE"
    NEWS_VOLATILITY_SPIKE = "NEWS_VOLATILITY_SPIKE"
    REPORT_CORRUPTION = "REPORT_CORRUPTION"
    CONFIG_CORRUPTION = "CONFIG_CORRUPTION"


ALL_SCENARIOS: tuple[FailureScenario, ...] = tuple(FailureScenario)


@dataclass(frozen=True)
class ScenarioSpec:
    scenario: FailureScenario
    description: str
    expected_components: tuple[str, ...]
    expected_recovery_modes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario.value,
            "description": self.description,
            "expected_components": list(self.expected_components),
            "expected_recovery_modes": list(self.expected_recovery_modes),
        }


SCENARIO_CATALOG: dict[FailureScenario, ScenarioSpec] = {
    FailureScenario.MISSING_FEATURE_DATA: ScenarioSpec(
        FailureScenario.MISSING_FEATURE_DATA,
        "Feature parquet removed from sandbox",
        ("features",),
        ("DEGRADED", "SAFE_MODE", "FAILED"),
    ),
    FailureScenario.STALE_FEATURE_DATA: ScenarioSpec(
        FailureScenario.STALE_FEATURE_DATA,
        "Feature file timestamp set to stale age",
        ("features",),
        ("DEGRADED", "WARNING", "SAFE_MODE"),
    ),
    FailureScenario.CORRUPTED_MODEL_FILE: ScenarioSpec(
        FailureScenario.CORRUPTED_MODEL_FILE,
        "Model pickle replaced with invalid bytes",
        ("model",),
        ("DEGRADED", "FAILED"),
    ),
    FailureScenario.INVALID_MODEL_METADATA: ScenarioSpec(
        FailureScenario.INVALID_MODEL_METADATA,
        "Model metadata JSON invalid",
        ("model",),
        ("DEGRADED", "FAILED"),
    ),
    FailureScenario.DATASET_HASH_MISMATCH: ScenarioSpec(
        FailureScenario.DATASET_HASH_MISMATCH,
        "Version registry reports mismatched dataset hash",
        ("dataset",),
        ("DEGRADED", "SAFE_MODE"),
    ),
    FailureScenario.FEATURE_DRIFT_SPIKE: ScenarioSpec(
        FailureScenario.FEATURE_DRIFT_SPIKE,
        "Feature drift report shows HIGH severity spike",
        ("monitoring", "features"),
        ("DEGRADED", "FAILED", "SAFE_MODE"),
    ),
    FailureScenario.PERFORMANCE_DEGRADATION: ScenarioSpec(
        FailureScenario.PERFORMANCE_DEGRADATION,
        "Monitoring summary reports degraded performance",
        ("monitoring",),
        ("DEGRADED", "SAFE_MODE"),
    ),
    FailureScenario.LOW_SAMPLE_SIZE: ScenarioSpec(
        FailureScenario.LOW_SAMPLE_SIZE,
        "A/B report with insufficient sample size",
        ("shadow_pipeline", "monitoring"),
        ("DEGRADED", "WARNING", "SAFE_MODE"),
    ),
    FailureScenario.SPREAD_SPIKE: ScenarioSpec(
        FailureScenario.SPREAD_SPIKE,
        "Spread regime spike recorded in monitoring alerts",
        ("monitoring", "deployment_gate"),
        ("DEGRADED", "WARNING"),
    ),
    FailureScenario.NEWS_VOLATILITY_SPIKE: ScenarioSpec(
        FailureScenario.NEWS_VOLATILITY_SPIKE,
        "News volatility spike in monitoring summary",
        ("monitoring",),
        ("DEGRADED", "WARNING"),
    ),
    FailureScenario.REPORT_CORRUPTION: ScenarioSpec(
        FailureScenario.REPORT_CORRUPTION,
        "Critical JSON report corrupted",
        ("monitoring", "deployment_gate"),
        ("FAILED", "SAFE_MODE", "DEGRADED"),
    ),
    FailureScenario.CONFIG_CORRUPTION: ScenarioSpec(
        FailureScenario.CONFIG_CORRUPTION,
        "Runtime config JSON corrupted",
        ("deployment_gate",),
        ("DEGRADED", "FAILED", "SAFE_MODE"),
    ),
}


def get_scenario(scenario: FailureScenario | str) -> ScenarioSpec:
    key = FailureScenario(scenario) if isinstance(scenario, str) else scenario
    return SCENARIO_CATALOG[key]
