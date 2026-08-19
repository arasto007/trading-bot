"""Live readiness engine — evaluate deployment readiness without execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.deployment.deployment_policy import DeploymentPolicy
from tradingbot.ml.deployment.kill_switch import KillSwitch
from tradingbot.ml.deployment.logger import DeploymentLogger
from tradingbot.ml.deployment.readiness_scoring import ReadinessScorer
from tradingbot.ml.deployment.risk_gates import DeploymentRiskGates
from tradingbot.ml.deployment.schema import (
    DeploymentPolicyConfig,
    LiveReadinessReport,
    ReadinessMetrics,
    ReadinessStatus,
    utc_now_iso,
)
from tradingbot.ml.deployment.shadow_validation import ShadowValidator
from tradingbot.ml.deployment.stability_checker import StabilityChecker
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.monitoring.schema import PerformanceState


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _health_to_score(health: str | None) -> float:
    mapping = {
        PerformanceState.HEALTHY.value: 0.9,
        PerformanceState.WARNING.value: 0.6,
        PerformanceState.DEGRADED.value: 0.35,
        PerformanceState.FAILED.value: 0.1,
        "HEALTHY": 0.9,
        "WARNING": 0.6,
        "DEGRADED": 0.35,
        "FAILED": 0.1,
    }
    return mapping.get(str(health or "HEALTHY").upper(), 0.5)


@dataclass
class LiveReadinessEngine:
    """
    Evaluate whether the system is ready for live trading.

    Shadow-only evaluation — NO execution, NO MT5, NO kernel changes.
    """

    policy: DeploymentPolicyConfig | None = None
    base_dir: str | Path | None = None

    def __post_init__(self) -> None:
        self.policy = self.policy or DeploymentPolicyConfig()
        self.scorer = ReadinessScorer(self.policy)
        self.risk_gates = DeploymentRiskGates(self.policy)
        self.shadow_validator = ShadowValidator()
        self.stability_checker = StabilityChecker()
        self.kill_switch = KillSwitch()
        self.deployment_policy = DeploymentPolicy(self.policy)

    def evaluate_readiness(
        self,
        symbol: str,
        timeframe: str = "M5",
        *,
        metrics: ReadinessMetrics | None = None,
        write_report: bool = True,
    ) -> LiveReadinessReport:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        if metrics is None:
            metrics = self._collect_metrics(symbol, timeframe)

        scoring = self.scorer.score(metrics)
        status = self.scorer.classify(scoring.composite_score)
        risk = self.risk_gates.evaluate(metrics)

        reasons: list[str] = []
        if risk.reasons:
            reasons.extend(risk.reasons)

        if risk.hard_fail and risk.forced_status:
            status = risk.forced_status
        elif risk.soft_downgrade and status == ReadinessStatus.LIVE_READY.value:
            status = ReadinessStatus.CONDITIONAL_READY.value
            reasons.append("Soft risk gates triggered — downgraded to CONDITIONAL_READY")

        kill = self.kill_switch.evaluate(status, risk.flags, hard_fail=risk.hard_fail)
        policy_eval = self.deployment_policy.evaluate(
            status=status,
            score=scoring.composite_score,
            paper_trades=metrics.paper_trade_count,
            ab_samples=metrics.ab_sample_size,
            win_rate=metrics.paper_win_rate,
        )
        if policy_eval.violations:
            reasons.extend(policy_eval.violations)

        recommendation = self.deployment_policy.recommendation(status, risk.flags)

        trace = {
            "scoring_breakdown": scoring.to_dict(),
            "risk_gates": {
                "hard_fail": risk.hard_fail,
                "soft_downgrade": risk.soft_downgrade,
                "flags": risk.flags,
            },
            "shadow_validation": {
                "validation_score": metrics.shadow_validation_score,
                "stability_score": metrics.shadow_stability_score,
                "noise_ratio": metrics.shadow_noise_ratio,
            },
            "stability_state": metrics.stability_state,
            "policy": {
                "approved": policy_eval.approved,
                "requires_manual_override": policy_eval.requires_manual_override,
                "auto_deployment_allowed": policy_eval.auto_deployment_allowed,
                "notes": policy_eval.notes,
            },
            "kill_switch": {
                "active": kill.active,
                "flag": kill.flag,
                "reasons": kill.reasons,
            },
        }

        report = LiveReadinessReport(
            timestamp=utc_now_iso(),
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            score=scoring.composite_score,
            reasons=reasons,
            risk_flags=risk.flags,
            recommendation_text=recommendation,
            scoring=scoring,
            metrics=metrics,
            kill_switch_active=kill.active,
            block_deployment=kill.block_deployment,
            trace=trace,
        )

        if write_report:
            DeploymentLogger(self.base_dir).write(report)
        return report

    def _collect_metrics(self, symbol: str, timeframe: str) -> ReadinessMetrics:
        base = self.base_dir
        paper = _load_json(reports_dir(base) / "paper_trading_report.json")
        monitoring = _load_json(reports_dir(base) / "monitoring_summary.json")
        ab = _load_json(reports_dir(base) / "ab_test_report.json")
        drift = _load_json(reports_dir(base) / "feature_drift_report.json")

        store = DecisionMemoryStore(symbol, base)
        decisions = store.load_decisions()
        outcomes = store.load_outcomes_by_id()

        shadow = self.shadow_validator.validate(decisions, outcomes)
        stability = self.stability_checker.analyze(decisions)

        paper_metrics = paper.get("metrics", {})
        degradation = monitoring.get("degradation", {})

        return ReadinessMetrics(
            paper_win_rate=float(paper_metrics.get("win_rate", 0.0)),
            paper_expectancy_r=float(paper_metrics.get("expectancy_r", 0.0)),
            paper_max_drawdown_r=float(paper_metrics.get("max_drawdown_r", 0.0)),
            paper_sharpe=float(paper_metrics.get("sharpe_like", 0.0)),
            paper_trade_count=int(paper_metrics.get("trade_frequency", 0)),
            monitoring_health=_health_to_score(monitoring.get("model_health")),
            expected_r=float(monitoring.get("expected_R", paper_metrics.get("expectancy_r", 0.0))),
            performance_state=str(degradation.get("status", monitoring.get("model_health", "HEALTHY"))),
            feature_drift_score=float(
                monitoring.get("feature_drift_score", drift.get("aggregate_score", 0.0))
            ),
            calibration_error=float(
                drift.get("calibration_error", monitoring.get("calibration_error", 0.0))
            ),
            ab_winner=str(ab.get("winner", "NO_DIFFERENCE")),
            ab_confidence=str(ab.get("confidence", "LOW")),
            ab_sample_size=int(ab.get("sample_size", len(decisions))),
            ab_improvement=float(ab.get("improvement", 0.0)),
            degradation_status=str(degradation.get("status", "HEALTHY")),
            degradation_drop_pct=float(degradation.get("drop_percentage", 0.0)) / 100.0,
            shadow_validation_score=shadow.validation_score,
            shadow_stability_score=shadow.stability_score,
            shadow_noise_ratio=shadow.noise_ratio,
            stability_state=stability.stability_state,
        )
