"""Dashboard JSON export for shadow monitoring."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.abtest.schema import WINNER_HYBRID
from tradingbot.ml.monitoring.alerts import AlertEngine
from tradingbot.ml.monitoring.degradation import DegradationDetector
from tradingbot.ml.monitoring.drift import FeatureDriftDetector
from tradingbot.ml.monitoring.health import drift_severity_label
from tradingbot.ml.monitoring.performance_monitor import PerformanceMonitor, snapshot_profit_factor
from tradingbot.ml.monitoring.schema import MonitoringSnapshot, utc_now_iso
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord


def build_dashboard_payload(
    *,
    symbol: str,
    timeframe: str,
    model_name: str,
    model_version: str,
    decisions: list[DecisionRecord],
    outcomes: dict[str, OutcomeRecord],
    ab_report: dict[str, Any] | None = None,
    base_dir: str | None = None,
) -> dict[str, Any]:
    monitor = PerformanceMonitor()
    latest = monitor.latest_metrics(decisions, outcomes, window=500)
    degradation = DegradationDetector().analyze(decisions, outcomes)
    drift = FeatureDriftDetector().analyze(decisions, symbol=symbol, timeframe=timeframe, base_dir=base_dir)

    hybrid_delta = 0.0
    ab_winner = None
    hybrid_status = "UNKNOWN"
    if ab_report:
        hybrid_delta = float(ab_report.get("improvement", 0.0))
        ab_winner = ab_report.get("winner")
        if ab_winner == WINNER_HYBRID:
            hybrid_status = "BETTER"
        elif ab_winner == "RULE_BETTER":
            hybrid_status = "WORSE"
        else:
            hybrid_status = "NEUTRAL"

    alerts = AlertEngine().generate(
        window_metrics=latest,
        degradation=degradation,
        drift=drift,
        hybrid_vs_rule_delta=hybrid_delta,
        ab_winner=ab_winner,
    )

    snapshot = MonitoringSnapshot(
        timestamp=utc_now_iso(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        model_name=model_name,
        model_version=model_version,
        sample_count=latest.samples,
        expected_R=latest.expected_R,
        win_rate=latest.win_rate,
        profit_factor=snapshot_profit_factor(decisions, outcomes, window=500),
        max_drawdown=latest.max_drawdown,
        prediction_accuracy=latest.prediction_accuracy,
        calibration_error=latest.calibration_error,
        hybrid_vs_rule_delta=round(hybrid_delta, 4),
        feature_drift_score=drift.aggregate_score,
        performance_state=latest.state,
        window=latest.window,
    )

    return {
        "generated_at": snapshot.timestamp,
        "model_health": snapshot.performance_state,
        "hybrid_status": hybrid_status,
        "expected_R": snapshot.expected_R,
        "win_rate": snapshot.win_rate,
        "profit_factor": snapshot.profit_factor,
        "latest_ab_winner": ab_winner,
        "feature_drift_summary": drift_severity_label(drift.aggregate_score),
        "feature_drift_score": drift.aggregate_score,
        "alerts": [a.to_dict() for a in alerts],
        "snapshot": snapshot.to_dict(),
        "rolling_windows": [w.to_dict() for w in monitor.compute_windows(decisions, outcomes)],
    }
