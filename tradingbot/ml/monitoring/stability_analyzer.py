"""Phase 10.4 — stability analysis and PASS/NEEDS REVIEW decision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingbot.ml.monitoring.anomaly_detector import AnomalyDetector, AnomalyReport


@dataclass
class StabilityVerdict:
    decision: str  # PASS | NEEDS REVIEW
    reasons: list[str]
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "reasons": self.reasons, "checks": self.checks}


class StabilityAnalyzer:
    """Evaluate long-run shadow stability against Phase 10.4 criteria."""

    def __init__(
        self,
        *,
        risk_percent: float = 0.005,
        max_drawdown_limit: float = 0.10,
        min_profit_factor: float = 1.0,
        base_dir: str | None = None,
    ) -> None:
        self.risk_percent = risk_percent
        self.max_drawdown_limit = max_drawdown_limit
        self.min_profit_factor = min_profit_factor
        self.detector = AnomalyDetector(risk_percent=risk_percent, base_dir=base_dir)

    def analyze(
        self,
        *,
        metrics: dict[str, Any],
        ml_buy: int,
        ml_sell: int,
        ml_hold: int,
        probabilities: list[float],
        feature_samples: dict[str, list[float]],
        virtual_trades: list[dict[str, Any]],
        invalid_trade_count: int,
        pipeline_errors: int,
        completion_rate: float = 1.0,
    ) -> tuple[AnomalyReport, StabilityVerdict]:
        report = AnomalyReport()
        self.detector.check_signal_collapse(ml_buy, ml_sell, ml_hold, report)
        self.detector.check_probability_drift(probabilities, report)
        self.detector.check_feature_drift(feature_samples, report)
        self.detector.check_trade_integrity(virtual_trades, invalid_trade_count, report)
        self.detector.check_execution_safety(
            execution_blocked=int(metrics.get("execution_blocked", 0)),
            risk_allowed=int(metrics.get("risk_allowed", 0)),
            report=report,
        )

        checks = {
            "zero_execution_violations": len([c for c in report.critical if c.get("code", "").startswith(("ast_", "execution_"))]) == 0,
            "zero_invalid_trades": invalid_trade_count == 0 and not any(c.get("code") == "entry_equals_sl" for c in report.critical),
            "profit_factor_ok": float(metrics.get("profit_factor", 0)) >= self.min_profit_factor,
            "expectancy_ok": float(metrics.get("expectancy_r", -1)) >= 0,
            "drawdown_ok": float(metrics.get("max_drawdown", 1)) < self.max_drawdown_limit,
            "stable_signals": not any(c.get("code") == "signal_collapse" for c in report.warnings),
            "no_pipeline_errors": pipeline_errors == 0,
            "cycle_completion_ok": completion_rate >= 0.99,
        }

        reasons: list[str] = []
        for key, ok in checks.items():
            if not ok:
                reasons.append(key)

        for c in report.critical:
            reasons.append(c.get("code", "critical"))

        decision = "PASS" if all(checks.values()) and not report.critical else "NEEDS REVIEW"
        return report, StabilityVerdict(decision=decision, reasons=reasons, checks=checks)
