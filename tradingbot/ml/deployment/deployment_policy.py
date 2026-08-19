"""Deployment policy — thresholds and manual-only rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.ml.deployment.schema import DeploymentPolicyConfig, ReadinessStatus


@dataclass
class PolicyEvaluation:
    approved: bool = False
    auto_deployment_allowed: bool = False
    requires_manual_override: bool = True
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class DeploymentPolicy:
    """
    Define minimum metrics and safe thresholds.

    Auto deployment is NEVER allowed — manual override only.
    """

    config: DeploymentPolicyConfig | None = None

    def __post_init__(self) -> None:
        self.config = self.config or DeploymentPolicyConfig()

    def evaluate(
        self,
        *,
        status: str,
        score: float,
        paper_trades: int,
        ab_samples: int,
        win_rate: float,
    ) -> PolicyEvaluation:
        cfg = self.config
        assert cfg is not None
        result = PolicyEvaluation(
            auto_deployment_allowed=cfg.allow_auto_deployment,
            requires_manual_override=cfg.manual_override_only,
        )

        if cfg.allow_auto_deployment:
            result.violations.append("Auto deployment must remain disabled")
        result.notes.append("Manual operator approval required for any live transition")

        if paper_trades < cfg.min_paper_trades:
            result.violations.append(
                f"Paper trades {paper_trades} below minimum {cfg.min_paper_trades}"
            )

        if ab_samples < cfg.min_ab_samples:
            result.violations.append(
                f"A/B samples {ab_samples} below minimum {cfg.min_ab_samples}"
            )

        if win_rate < cfg.min_win_rate:
            result.violations.append(f"Win rate {win_rate:.2%} below {cfg.min_win_rate:.0%}")

        if score < cfg.conditional_threshold:
            result.violations.append(f"Score {score:.2f} below conditional threshold")

        if status == ReadinessStatus.LIVE_READY.value and score >= cfg.live_ready_threshold:
            result.approved = len(result.violations) == 0
            result.notes.append("Metrics meet LIVE_READY thresholds — manual review still required")
        elif status == ReadinessStatus.CONDITIONAL_READY.value:
            result.approved = False
            result.notes.append("Conditional readiness - continue shadow testing")
        else:
            result.approved = False
            result.notes.append("Not ready for live transition")

        return result

    def recommendation(self, status: str, risk_flags: list[str]) -> str:
        if status == ReadinessStatus.LIVE_READY.value and not risk_flags:
            return "System metrics strong - proceed only after manual safety review"
        if status == ReadinessStatus.CONDITIONAL_READY.value:
            if risk_flags:
                return "Continue shadow testing - address risk flags before review"
            return "Approaching readiness - extend shadow validation period"
        return "Not ready for live transition - remain in shadow mode"
