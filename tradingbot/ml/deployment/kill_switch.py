"""Kill switch — safety block flag only, no execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.ml.deployment.schema import ReadinessStatus


@dataclass
class KillSwitchResult:
    active: bool = False
    block_deployment: bool = False
    flag: str = "ALLOW"
    reasons: list[str] = field(default_factory=list)


@dataclass
class KillSwitch:
    """
    Safety layer — blocks deployment approval when NOT_READY.

    No order execution. No MT5. No kernel interaction.
    """

    def evaluate(self, status: str, risk_flags: list[str], hard_fail: bool = False) -> KillSwitchResult:
        if status == ReadinessStatus.NOT_READY.value or hard_fail:
            reasons = ["System NOT_READY — deployment blocked"]
            if risk_flags:
                reasons.extend(risk_flags)
            return KillSwitchResult(
                active=True,
                block_deployment=True,
                flag="BLOCK",
                reasons=reasons,
            )
        return KillSwitchResult(
            active=False,
            block_deployment=False,
            flag="ALLOW",
            reasons=["Kill switch inactive — evaluation only"],
        )
