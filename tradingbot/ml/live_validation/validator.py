"""Phase 15D — pass/fail validation criteria."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.live_validation.report_generator import REQUIRED_REPORTS, reports_complete
from tradingbot.ml.live_validation.shadow_mode import ShadowModeResult


@dataclass
class ValidationResult:
    status: str
    recommendation: str
    criteria: dict[str, bool] = field(default_factory=dict)
    blockers: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15D",
            "status": self.status,
            "recommendation": self.recommendation,
            "criteria": self.criteria,
            "blockers": self.blockers,
        }


def validate_shadow_result(
    result: ShadowModeResult,
    *,
    base_dir: str | None = None,
    require_full_reports: bool = True,
) -> ValidationResult:
    equity_report = result.equity.build_report(result.stats.shadow_trades)
    stats_report = result.stats.build_report()
    latency = result.latency.build_report()

    criteria = {
        "zero_real_orders": result.order_send_calls == 0,
        "shadow_equity_generated": bool(equity_report.get("equity_curve")),
        "latency_mean_target": latency.get("warm_total", {}).get("mean", 999) < 20.0,
        "latency_p95_target": latency.get("warm_p95_ms", 999) < 50.0,
        "replay_deterministic": result.consistency.is_deterministic(),
        "no_checksum_drift": result.checksum_stable,
        "health_checks_pass": result.health.passes(),
        "agreement_statistics": stats_report.get("total", 0) > 0 or stats_report.get("bars_processed", 0) > 0,
        "reports_complete": reports_complete(base_dir) if require_full_reports else True,
    }

    blockers: list[dict[str, str]] = []
    labels = {
        "zero_real_orders": "Real order_send invoked",
        "shadow_equity_generated": "Shadow equity not generated",
        "latency_mean_target": "Mean latency >= 20ms",
        "latency_p95_target": "P95 latency >= 50ms",
        "replay_deterministic": "Replay non-deterministic",
        "no_checksum_drift": "Bundle checksum drift detected",
        "health_checks_pass": "Health checks failed",
        "agreement_statistics": "Agreement statistics missing",
        "reports_complete": "Reports incomplete",
    }
    for key, ok in criteria.items():
        if not ok:
            blockers.append({"id": f"D-{key.upper()}", "detail": labels[key]})

    if not blockers:
        return ValidationResult(status="PASS", recommendation="READY_FOR_PHASE15E", criteria=criteria)
    return ValidationResult(status="NEEDS_REVIEW", recommendation="NEEDS_REVIEW", criteria=criteria, blockers=blockers)
