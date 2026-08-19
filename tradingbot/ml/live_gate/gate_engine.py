"""Live gate engine — maps Phase 6.4 readiness to safe permission flags."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.deployment.schema import LiveReadinessReport, ReadinessStatus
from tradingbot.ml.live_gate.schema import (
    AllowedMode,
    LiveGateState,
    LivePermission,
    RiskFlagLevel,
    utc_now_iso,
)


def _risk_level(report: LiveReadinessReport) -> str:
    flags = len(report.risk_flags)
    if report.kill_switch_active or report.block_deployment or flags >= 3:
        return RiskFlagLevel.HIGH.value
    if flags >= 1 or report.score < 0.70:
        return RiskFlagLevel.MEDIUM.value
    return RiskFlagLevel.LOW.value


def _build_reason(report: LiveReadinessReport, state: str) -> str:
    if report.recommendation_text:
        base = report.recommendation_text
    elif report.reasons:
        base = report.reasons[0]
    else:
        base = f"Readiness score {report.score:.2f} maps to {state}"

    if report.risk_flags and "monitoring" in base.lower():
        return base
    if report.risk_flags and report.score >= 0.60:
        return f"Monitoring unstable but paper trading acceptable - {base}"
    return base


@dataclass
class LiveGateEngine:
    """
    Consume LiveReadinessReport and produce LivePermission.

    NO auto trading. NO execution. Manual activation only at READY_FOR_MANUAL.
    """

    conditional_threshold: float = 0.60
    manual_threshold: float = 0.80

    def evaluate(self, report: LiveReadinessReport) -> LivePermission:
        score = float(report.score)

        if report.kill_switch_active or report.block_deployment:
            if score < self.conditional_threshold:
                state = LiveGateState.BLOCKED.value
            else:
                state = LiveGateState.SHADOW_ONLY.value
        elif score < self.conditional_threshold:
            state = LiveGateState.BLOCKED.value
        elif score < self.manual_threshold:
            state = LiveGateState.CONDITIONAL_SHADOW.value
        else:
            state = LiveGateState.READY_FOR_MANUAL.value

        if report.status == ReadinessStatus.NOT_READY.value and state != LiveGateState.BLOCKED.value:
            state = LiveGateState.SHADOW_ONLY.value

        allowed_mode = AllowedMode.SHADOW_ONLY.value
        if state == LiveGateState.BLOCKED.value:
            allowed_mode = AllowedMode.BLOCKED.value

        manual_allowed = state == LiveGateState.READY_FOR_MANUAL.value and not report.block_deployment
        shadow_allowed = state != LiveGateState.BLOCKED.value or score >= 0.40

        return LivePermission(
            state=state,
            readiness_score=round(score, 4),
            allowed_mode=allowed_mode,
            risk_flag=_risk_level(report),
            reason=_build_reason(report, state),
            symbol=report.symbol,
            timeframe=report.timeframe,
            readiness_status=report.status,
            auto_trading_allowed=False,
            manual_activation_allowed=manual_allowed,
            shadow_routing_allowed=shadow_allowed,
            timestamp=utc_now_iso(),
            trace={
                "readiness_status": report.status,
                "kill_switch_active": report.kill_switch_active,
                "block_deployment": report.block_deployment,
                "risk_flags": list(report.risk_flags),
                "thresholds": {
                    "conditional": self.conditional_threshold,
                    "manual": self.manual_threshold,
                },
            },
        )
