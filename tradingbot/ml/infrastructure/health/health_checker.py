"""System health checks for ML shadow ecosystem."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    dataset_path,
    feature_path,
    reports_dir,
)
from tradingbot.ml.infrastructure.health.schema import (
    ComponentHealth,
    HealthStatus,
    SystemHealthReport,
    utc_now_iso,
)
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.models.artifacts import model_metadata_path, model_pkl_path, read_metadata


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _file_age_hours(path: Path) -> float | None:
    if not path.is_file():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 3600.0


@dataclass
class HealthChecker:
    """Check dataset, features, model, shadow, monitoring, and gate health."""

    base_dir: str | Path | None = None
    stale_hours: float = 168.0

    def check_all(self, symbol: str, timeframe: str = "M5") -> SystemHealthReport:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        components = [
            self.check_dataset(symbol, timeframe),
            self.check_feature_freshness(symbol, timeframe),
            self.check_model_availability(symbol, timeframe),
            self.check_shadow_pipeline(symbol),
            self.check_monitoring_status(),
            self.check_deployment_gate(),
        ]
        warnings = [c.message for c in components if c.status not in (HealthStatus.HEALTHY.value, HealthStatus.UNKNOWN.value)]
        overall = self._aggregate(components)
        return SystemHealthReport(
            timestamp=utc_now_iso(),
            symbol=symbol,
            timeframe=timeframe,
            overall_status=overall,
            components=components,
            warnings=warnings,
        )

    def check_dataset(self, symbol: str, timeframe: str) -> ComponentHealth:
        path = dataset_path(symbol, timeframe, self.base_dir)
        if not path.is_file():
            return ComponentHealth("dataset", HealthStatus.FAILED.value, "Dataset file missing", {"path": str(path)})
        age = _file_age_hours(path)
        if age is not None and age > self.stale_hours:
            return ComponentHealth(
                "dataset",
                HealthStatus.WARNING.value,
                f"Dataset stale ({age:.0f}h old)",
                {"path": str(path), "age_hours": round(age, 2)},
            )
        return ComponentHealth("dataset", HealthStatus.HEALTHY.value, "Dataset available", {"path": str(path)})

    def check_feature_freshness(self, symbol: str, timeframe: str) -> ComponentHealth:
        path = feature_path(symbol, timeframe, self.base_dir)
        if not path.is_file():
            return ComponentHealth("features", HealthStatus.FAILED.value, "Feature file missing", {"path": str(path)})
        age = _file_age_hours(path)
        status = HealthStatus.HEALTHY.value
        message = "Features fresh"
        if age is not None and age > self.stale_hours:
            status = HealthStatus.WARNING.value
            message = f"Features stale ({age:.0f}h old)"
        return ComponentHealth("features", status, message, {"path": str(path), "age_hours": age})

    def check_model_availability(self, symbol: str, timeframe: str) -> ComponentHealth:
        for name in ("xgboost", "lightgbm", "logistic"):
            meta = read_metadata(model_metadata_path(name, self.base_dir))
            pkl = model_pkl_path(name, self.base_dir)
            if meta and pkl.is_file():
                sym = str(meta.get("symbol", "")).upper()
                if not sym or sym == symbol.upper():
                    return ComponentHealth(
                        "model",
                        HealthStatus.HEALTHY.value,
                        f"Model {name} available",
                        {"model": name, "version": meta.get("version", "unknown")},
                    )
        return ComponentHealth("model", HealthStatus.DEGRADED.value, "No trained model artifact found")

    def check_shadow_pipeline(self, symbol: str) -> ComponentHealth:
        store = DecisionMemoryStore(symbol, self.base_dir)
        decisions = store.load_decisions()
        if not decisions:
            return ComponentHealth("shadow_pipeline", HealthStatus.WARNING.value, "No shadow decisions recorded")
        return ComponentHealth(
            "shadow_pipeline",
            HealthStatus.HEALTHY.value,
            f"Shadow pipeline active ({len(decisions)} decisions)",
            {"decision_count": len(decisions)},
        )

    def check_monitoring_status(self) -> ComponentHealth:
        summary = _load_json(reports_dir(self.base_dir) / "monitoring_summary.json")
        if summary is None:
            return ComponentHealth("monitoring", HealthStatus.WARNING.value, "Monitoring summary missing")
        health = str(summary.get("model_health", "UNKNOWN")).upper()
        status = HealthStatus.HEALTHY.value if health == "HEALTHY" else HealthStatus.DEGRADED.value
        return ComponentHealth("monitoring", status, f"Monitoring status: {health}", summary)

    def check_deployment_gate(self) -> ComponentHealth:
        from tradingbot.ml.deployment.logger import readiness_report_path
        from tradingbot.ml.live_gate.logger import live_gate_report_path

        readiness = _load_json(readiness_report_path(self.base_dir)) or {}
        gate = _load_json(live_gate_report_path(self.base_dir)) or {}
        if not readiness and not gate:
            return ComponentHealth("deployment_gate", HealthStatus.UNKNOWN.value, "Gate reports not generated yet")
        perm = gate.get("permission", {})
        state = perm.get("state", readiness.get("status", "UNKNOWN"))
        status = HealthStatus.DEGRADED.value if state in ("NOT_READY", "BLOCKED") else HealthStatus.HEALTHY.value
        return ComponentHealth(
            "deployment_gate",
            status,
            f"Gate state: {state}",
            {"readiness_status": readiness.get("status"), "gate_state": state},
        )

    @staticmethod
    def _aggregate(components: list[ComponentHealth]) -> str:
        statuses = [c.status for c in components]
        if HealthStatus.FAILED.value in statuses:
            return HealthStatus.FAILED.value
        if HealthStatus.DEGRADED.value in statuses:
            return HealthStatus.DEGRADED.value
        if HealthStatus.WARNING.value in statuses:
            return HealthStatus.WARNING.value
        if all(s == HealthStatus.UNKNOWN.value for s in statuses):
            return HealthStatus.UNKNOWN.value
        return HealthStatus.HEALTHY.value
