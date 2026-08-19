"""Monitoring report generation and orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root, reports_dir
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.models.artifacts import read_metadata, model_metadata_path
from tradingbot.ml.monitoring.alerts import AlertEngine
from tradingbot.ml.monitoring.dashboard_data import build_dashboard_payload
from tradingbot.ml.monitoring.degradation import DegradationDetector
from tradingbot.ml.monitoring.drift import FeatureDriftDetector
from tradingbot.ml.monitoring.performance_monitor import PerformanceMonitor
from tradingbot.ml.monitoring.schema import utc_now_iso


def monitoring_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "monitoring"


def dashboard_path(base_dir: str | Path | None = None) -> Path:
    return monitoring_dir(base_dir) / "dashboard.json"


def monitoring_summary_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "monitoring_summary.json"


def performance_history_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "performance_history.json"


def feature_drift_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "feature_drift_report.json"


def alerts_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "alerts.json"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_model_info(symbol: str, timeframe: str, base_dir: str | Path | None) -> tuple[str, str]:
    for name in ("xgboost", "lightgbm", "logistic"):
        meta = read_metadata(model_metadata_path(name, base_dir))
        if meta.get("symbol", "").upper() == symbol.upper():
            return name, str(meta.get("version", "1.0"))
    return "unknown", "1.0"


class MonitoringReportGenerator:
    """Run full shadow intelligence monitoring pipeline."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    def run(
        self,
        store: DecisionMemoryStore,
        *,
        timeframe: str = "M5",
        model_name: str | None = None,
    ) -> dict[str, Any]:
        decisions = store.load_decisions()
        outcomes = store.load_outcomes_by_id()
        resolved_model, model_version = _resolve_model_info(store.symbol, timeframe, self.base_dir)
        model_name = model_name or resolved_model

        ab_report = _load_json(reports_dir(self.base_dir) / "ab_test_report.json")

        dashboard = build_dashboard_payload(
            symbol=store.symbol,
            timeframe=timeframe,
            model_name=model_name,
            model_version=model_version,
            decisions=decisions,
            outcomes=outcomes,
            ab_report=ab_report,
            base_dir=str(self.base_dir) if self.base_dir else None,
        )

        monitor = PerformanceMonitor()
        degradation = DegradationDetector().analyze(decisions, outcomes)
        drift = FeatureDriftDetector().analyze(
            decisions,
            symbol=store.symbol,
            timeframe=timeframe,
            base_dir=str(self.base_dir) if self.base_dir else None,
        )
        latest = monitor.latest_metrics(decisions, outcomes)
        alerts = AlertEngine().generate(
            window_metrics=latest,
            degradation=degradation,
            drift=drift,
            hybrid_vs_rule_delta=float(dashboard.get("snapshot", {}).get("hybrid_vs_rule_delta", 0.0)),
            ab_winner=ab_report.get("winner"),
        )

        summary = {
            "timestamp": utc_now_iso(),
            "symbol": store.symbol,
            "timeframe": timeframe.upper(),
            "model_name": model_name,
            "model_version": model_version,
            "model_health": dashboard.get("model_health"),
            "expected_R": dashboard.get("expected_R"),
            "hybrid_vs_rule_delta": dashboard.get("snapshot", {}).get("hybrid_vs_rule_delta"),
            "feature_drift_score": drift.aggregate_score,
            "degradation": degradation.to_dict(),
            "alert_count": len(alerts),
        }

        _write_json(dashboard_path(self.base_dir), dashboard)
        _write_json(monitoring_summary_path(self.base_dir), summary)
        _write_json(
            performance_history_path(self.base_dir),
            {"windows": dashboard.get("rolling_windows", []), "generated_at": summary["timestamp"]},
        )
        _write_json(feature_drift_report_path(self.base_dir), drift.to_dict())
        _write_json(alerts_report_path(self.base_dir), {"alerts": [a.to_dict() for a in alerts]})

        return {
            "summary": summary,
            "dashboard": dashboard,
            "alerts": [a.to_dict() for a in alerts],
        }
