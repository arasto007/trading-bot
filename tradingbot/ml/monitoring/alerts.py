"""Informational alert engine — no automatic actions."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.abtest.schema import WINNER_HYBRID, WINNER_RULE
from tradingbot.ml.monitoring.degradation import DegradationDetector
from tradingbot.ml.monitoring.drift import FeatureDriftReport
from tradingbot.ml.monitoring.schema import Alert, AlertSeverity, DegradationReport, PerformanceState, utc_now_iso
from tradingbot.ml.monitoring.performance_monitor import WindowMetrics


ALERT_MODEL_PERFORMANCE_DROP = "MODEL_PERFORMANCE_DROP"
ALERT_FEATURE_DRIFT_HIGH = "FEATURE_DRIFT_HIGH"
ALERT_LOW_SAMPLE_SIZE = "LOW_SAMPLE_SIZE"
ALERT_CALIBRATION_FAILURE = "CALIBRATION_FAILURE"
ALERT_HYBRID_UNDERPERFORMING = "HYBRID_UNDERPERFORMING"


@dataclass
class AlertEngine:
    """Generate informational monitoring alerts."""

    min_samples: int = 100
    calibration_error_threshold: float = 0.15
    drift_high_threshold: float = 0.25

    def generate(
        self,
        *,
        window_metrics: WindowMetrics,
        degradation: DegradationReport,
        drift: FeatureDriftReport,
        hybrid_vs_rule_delta: float,
        ab_winner: str | None = None,
    ) -> list[Alert]:
        alerts: list[Alert] = []
        ts = utc_now_iso()

        if window_metrics.samples < self.min_samples:
            alerts.append(
                Alert(
                    timestamp=ts,
                    type=ALERT_LOW_SAMPLE_SIZE,
                    severity=AlertSeverity.INFO.value,
                    message=f"Sample size {window_metrics.samples} below minimum {self.min_samples}",
                    metrics={"samples": window_metrics.samples},
                )
            )

        if degradation.status in (PerformanceState.WARNING.value, PerformanceState.DEGRADED.value):
            sev = AlertSeverity.CRITICAL.value if degradation.status == PerformanceState.DEGRADED.value else AlertSeverity.WARNING.value
            alerts.append(
                Alert(
                    timestamp=ts,
                    type=ALERT_MODEL_PERFORMANCE_DROP,
                    severity=sev,
                    message="; ".join(degradation.reasons),
                    metrics=degradation.to_dict(),
                )
            )

        if window_metrics.calibration_error >= self.calibration_error_threshold:
            alerts.append(
                Alert(
                    timestamp=ts,
                    type=ALERT_CALIBRATION_FAILURE,
                    severity=AlertSeverity.WARNING.value,
                    message="Confidence calibration error elevated",
                    metrics={"calibration_error": window_metrics.calibration_error},
                )
            )

        if drift.aggregate_score >= self.drift_high_threshold or drift.severity == "HIGH":
            alerts.append(
                Alert(
                    timestamp=ts,
                    type=ALERT_FEATURE_DRIFT_HIGH,
                    severity=AlertSeverity.WARNING.value,
                    message=f"Feature drift score {drift.aggregate_score}",
                    metrics={"aggregate_score": drift.aggregate_score},
                )
            )

        if hybrid_vs_rule_delta < 0 or ab_winner == WINNER_RULE:
            alerts.append(
                Alert(
                    timestamp=ts,
                    type=ALERT_HYBRID_UNDERPERFORMING,
                    severity=AlertSeverity.INFO.value,
                    message="Hybrid underperforming vs rule baseline",
                    metrics={"hybrid_vs_rule_delta": hybrid_vs_rule_delta, "ab_winner": ab_winner},
                )
            )
        elif ab_winner == WINNER_HYBRID and hybrid_vs_rule_delta > 0:
            alerts.append(
                Alert(
                    timestamp=ts,
                    type="HYBRID_OUTPERFORMING",
                    severity=AlertSeverity.INFO.value,
                    message="Hybrid outperforming rule baseline in shadow A/B",
                    metrics={"hybrid_vs_rule_delta": hybrid_vs_rule_delta},
                )
            )

        return alerts
