"""Hard and soft risk gates — readiness constraints only."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.ml.deployment.schema import DeploymentPolicyConfig, ReadinessMetrics, ReadinessStatus


@dataclass
class RiskGateResult:
    hard_fail: bool = False
    soft_downgrade: bool = False
    forced_status: str | None = None
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class DeploymentRiskGates:
    """Apply hard/soft constraints — no execution side effects."""

    policy: DeploymentPolicyConfig | None = None

    def __post_init__(self) -> None:
        self.policy = self.policy or DeploymentPolicyConfig()

    def evaluate(self, metrics: ReadinessMetrics) -> RiskGateResult:
        policy = self.policy
        assert policy is not None
        result = RiskGateResult()

        if metrics.paper_max_drawdown_r > policy.max_drawdown_r:
            result.hard_fail = True
            result.forced_status = ReadinessStatus.NOT_READY.value
            result.flags.append("High drawdown")
            result.reasons.append(
                f"Max drawdown {metrics.paper_max_drawdown_r:.1f}R exceeds {policy.max_drawdown_r:.1f}R limit"
            )

        dd_pct = metrics.paper_max_drawdown_r / max(metrics.paper_trade_count, 1) / 100.0
        if metrics.paper_max_drawdown_r > 0 and metrics.paper_max_drawdown_r / 100.0 > policy.max_drawdown_pct:
            if "High drawdown" not in result.flags:
                result.flags.append("High drawdown")

        if metrics.feature_drift_score >= policy.max_drift_score:
            result.hard_fail = True
            result.forced_status = ReadinessStatus.NOT_READY.value
            result.flags.append("Feature drift HIGH")
            result.reasons.append(
                f"Feature drift {metrics.feature_drift_score:.3f} exceeds {policy.max_drift_score:.3f}"
            )
        elif metrics.feature_drift_score >= policy.max_drift_score * 0.6:
            result.soft_downgrade = True
            result.flags.append("Moderate drift")

        if metrics.calibration_error > policy.max_calibration_error:
            result.hard_fail = True
            result.forced_status = ReadinessStatus.NOT_READY.value
            result.flags.append("Calibration error elevated")
            result.reasons.append(
                f"Calibration error {metrics.calibration_error:.3f} exceeds {policy.max_calibration_error:.3f}"
            )

        if metrics.ab_sample_size >= 50 and metrics.ab_confidence == "LOW" and metrics.ab_winner == "NO_DIFFERENCE":
            result.hard_fail = True
            result.forced_status = ReadinessStatus.NOT_READY.value
            result.flags.append("Unstable A/B results")
            result.reasons.append("A/B winner inconclusive with low confidence")

        if metrics.expected_r < 0:
            result.hard_fail = True
            result.forced_status = ReadinessStatus.NOT_READY.value
            result.flags.append("Negative expected R")
            result.reasons.append(f"Expected R {metrics.expected_r:.3f} is negative")

        if metrics.paper_win_rate < policy.min_win_rate and metrics.paper_trade_count >= 20:
            result.soft_downgrade = True
            result.flags.append("Win rate below 50%")
            result.reasons.append(f"Win rate {metrics.paper_win_rate:.2%} below minimum")

        if metrics.performance_state in ("DEGRADED", "FAILED"):
            result.soft_downgrade = True
            if "Performance degraded" not in result.flags:
                result.flags.append("Performance degraded")

        if metrics.stability_state == "CRITICAL":
            result.hard_fail = True
            result.forced_status = ReadinessStatus.NOT_READY.value
            result.flags.append("Critical instability")
            result.reasons.append("Stability checker reported CRITICAL state")

        return result
