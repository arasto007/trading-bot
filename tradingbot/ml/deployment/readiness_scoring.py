"""Composite readiness scoring — weighted metric blend."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.deployment.schema import DeploymentPolicyConfig, ReadinessMetrics, ReadinessStatus, ScoringBreakdown


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _paper_score(metrics: ReadinessMetrics) -> float:
    if metrics.paper_trade_count <= 0:
        return 0.0
    win = _clamp(metrics.paper_win_rate)
    sharpe = _clamp((metrics.paper_sharpe + 1.0) / 3.0)
    expectancy = _clamp((metrics.paper_expectancy_r + 1.0) / 3.0)
    dd_penalty = _clamp(1.0 - metrics.paper_max_drawdown_r / 30.0)
    return round((win * 0.4 + sharpe * 0.25 + expectancy * 0.2 + dd_penalty * 0.15), 6)


def _monitoring_score(metrics: ReadinessMetrics) -> float:
    base = _clamp(metrics.monitoring_health)
    if metrics.performance_state == "HEALTHY":
        base = max(base, 0.75)
    elif metrics.performance_state == "WARNING":
        base = min(base, 0.65)
    elif metrics.performance_state == "DEGRADED":
        base = min(base, 0.45)
    elif metrics.performance_state == "FAILED":
        base = min(base, 0.20)
    if metrics.expected_r < 0:
        base *= 0.5
    return round(_clamp(base), 6)


def _feature_stability_score(metrics: ReadinessMetrics) -> float:
    return round(_clamp(1.0 - metrics.feature_drift_score), 6)


def _ab_consistency_score(metrics: ReadinessMetrics) -> float:
    if metrics.ab_sample_size < 50:
        return 0.3
    conf_map = {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.4}
    base = conf_map.get(metrics.ab_confidence.upper(), 0.4)
    if metrics.ab_winner == "NO_DIFFERENCE":
        base *= 0.6
    elif metrics.ab_improvement > 0:
        base = min(1.0, base + metrics.ab_improvement)
    return round(_clamp(base), 6)


def _calibration_score(metrics: ReadinessMetrics) -> float:
    return round(_clamp(1.0 - metrics.calibration_error), 6)


def _degradation_component(metrics: ReadinessMetrics) -> float:
    status = metrics.degradation_status.upper()
    if status == "HEALTHY":
        return 1.0
    if status == "WARNING":
        return 0.65
    if status == "DEGRADED":
        return 0.35
    if status == "FAILED":
        return 0.0
    drop = metrics.degradation_drop_pct
    return round(_clamp(1.0 - drop), 6)


@dataclass
class ReadinessScorer:
    """Compute weighted readiness score in [0, 1]."""

    policy: DeploymentPolicyConfig | None = None

    def __post_init__(self) -> None:
        self.policy = self.policy or DeploymentPolicyConfig()

    def score(self, metrics: ReadinessMetrics) -> ScoringBreakdown:
        paper = _paper_score(metrics)
        monitoring = _monitoring_score(metrics)
        feature = _feature_stability_score(metrics)
        ab = _ab_consistency_score(metrics)
        calibration = _calibration_score(metrics)
        degradation = _degradation_component(metrics)

        composite = (
            0.25 * paper
            + 0.20 * monitoring
            + 0.20 * feature
            + 0.15 * ab
            + 0.10 * calibration
            + 0.10 * degradation
        )
        return ScoringBreakdown(
            paper_trading_performance=paper,
            monitoring_health=monitoring,
            feature_stability=feature,
            ab_consistency=ab,
            calibration_quality=calibration,
            degradation_component=degradation,
            composite_score=round(_clamp(composite), 6),
        )

    def classify(self, composite_score: float) -> str:
        policy = self.policy
        assert policy is not None
        if composite_score >= policy.live_ready_threshold:
            return ReadinessStatus.LIVE_READY.value
        if composite_score >= policy.conditional_threshold:
            return ReadinessStatus.CONDITIONAL_READY.value
        return ReadinessStatus.NOT_READY.value
