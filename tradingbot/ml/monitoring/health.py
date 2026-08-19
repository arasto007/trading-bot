"""Model health state derivation."""

from __future__ import annotations

from tradingbot.ml.monitoring.schema import PerformanceState


def derive_health_state(
    *,
    expected_R: float,
    win_rate: float,
    calibration_error: float,
    sample_count: int,
    min_samples: int = 30,
    degradation_status: str = "HEALTHY",
) -> str:
    if sample_count < min_samples:
        return PerformanceState.WARNING.value
    if degradation_status == PerformanceState.FAILED.value:
        return PerformanceState.FAILED.value
    if degradation_status == PerformanceState.DEGRADED.value:
        return PerformanceState.DEGRADED.value
    if expected_R < 0:
        return PerformanceState.DEGRADED.value
    if calibration_error > 0.15 or win_rate < 0.45:
        return PerformanceState.WARNING.value
    if degradation_status == PerformanceState.WARNING.value:
        return PerformanceState.WARNING.value
    return PerformanceState.HEALTHY.value


def drift_severity_label(score: float) -> str:
    if score >= 0.25:
        return "HIGH"
    if score >= 0.10:
        return "MEDIUM"
    return "LOW"
