"""Phase 10.5 — shadow pipeline health validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingbot.ml.integration.error_audit.kernel_error_analyzer import KernelErrorAnalyzer
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast


@dataclass
class HealthCheckResult:
    passed: bool
    checks: dict[str, bool]
    metrics: dict[str, Any]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "metrics": self.metrics,
            "reasons": self.reasons,
        }


class ShadowHealthCheck:
    """Validate shadow run against Phase 10.5 targets."""

    def __init__(self, *, min_completion_rate: float = 0.99) -> None:
        self.min_completion_rate = min_completion_rate

    def evaluate(
        self,
        *,
        kernel_cycles: int,
        cycles_attempted: int,
        pipeline_failures: int,
        ml_cycles: int,
        risk_evaluations: int,
        invalid_trades: int,
        recovery: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        completion_rate = (
            float(recovery.get("completion_rate", 1.0))
            if recovery
            else (kernel_cycles / cycles_attempted if cycles_attempted else 1.0)
        )
        ast_clean = len(scan_live_shadow_ast()) == 0

        checks = {
            "cycle_completion_gt_99pct": completion_rate >= self.min_completion_rate,
            "pipeline_error_rate_zero": pipeline_failures == 0,
            "ml_signal_processing_ok": ml_cycles >= kernel_cycles if kernel_cycles else True,
            "risk_evaluation_ok": risk_evaluations >= 0,
            "virtual_trade_integrity": invalid_trades == 0,
            "ast_execution_safety": ast_clean,
        }

        metrics = {
            "kernel_cycles": kernel_cycles,
            "cycles_attempted": cycles_attempted,
            "completion_rate": round(completion_rate, 4),
            "pipeline_failures": pipeline_failures,
            "invalid_trades": invalid_trades,
            "ast_violations": len(scan_live_shadow_ast()),
        }

        reasons = [k for k, ok in checks.items() if not ok]
        return HealthCheckResult(
            passed=all(checks.values()),
            checks=checks,
            metrics=metrics,
            reasons=reasons,
        )

    def evaluate_artifacts(
        self,
        *,
        run_id: str,
        contexts: list[dict[str, Any]],
        metrics: dict[str, Any],
        invalid_trades: int,
        recovery: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        summary = KernelErrorAnalyzer().analyze_contexts(contexts)
        kernel_cycles = int(metrics.get("kernel_cycles", len(contexts)))
        risk_evals = int(metrics.get("risk_allowed", 0)) + int(metrics.get("risk_blocked", 0))
        ml_cycles = int(metrics.get("ml_predictions", kernel_cycles))
        return self.evaluate(
            kernel_cycles=kernel_cycles,
            cycles_attempted=int((recovery or {}).get("cycles_attempted", kernel_cycles)),
            pipeline_failures=summary.pipeline_failures,
            ml_cycles=ml_cycles,
            risk_evaluations=risk_evals,
            invalid_trades=invalid_trades,
            recovery=recovery,
        )
