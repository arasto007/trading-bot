"""System diagnostic report generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.infrastructure.config.runtime_config import RuntimeConfigLoader
from tradingbot.ml.infrastructure.health.health_checker import HealthChecker
from tradingbot.ml.infrastructure.recovery.recovery_manager import RecoveryManager
from tradingbot.ml.infrastructure.versioning.model_version import ModelVersionTracker
from tradingbot.ml.live_gate.logger import live_gate_report_path


def system_diagnostic_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "system_diagnostic_report.json"


@dataclass
class DiagnosticReportGenerator:
    """Generate consolidated system diagnostic report."""

    base_dir: str | Path | None = None

    def generate(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        health = HealthChecker(self.base_dir).check_all(symbol, timeframe)
        recovery = RecoveryManager(self.base_dir).assess(symbol, timeframe)
        config = RuntimeConfigLoader(self.base_dir).load()
        versions = ModelVersionTracker(self.base_dir).read_registry()

        gate_state = "UNKNOWN"
        gate_data = {}
        gate_path = live_gate_report_path(self.base_dir)
        if gate_path.is_file():
            gate_data = json.loads(gate_path.read_text(encoding="utf-8"))
            gate_state = gate_data.get("permission", {}).get("state", "UNKNOWN")

        model_name = config.active_model_name
        models = versions.get("models", [])
        if models:
            model_name = models[-1].get("model_name", model_name)

        feature_status = "OK"
        model_status = "OK"
        monitoring_status = "OK"
        for comp in health.components:
            if comp.name == "features" and comp.status != "HEALTHY":
                feature_status = comp.status
            if comp.name == "model" and comp.status != "HEALTHY":
                model_status = comp.status
            if comp.name == "monitoring" and comp.status != "HEALTHY":
                monitoring_status = comp.status

        payload = {
            "timestamp": health.timestamp,
            "symbol": symbol,
            "timeframe": timeframe,
            "system": health.overall_status,
            "model": f"{model_name}_v1",
            "feature_status": feature_status,
            "monitoring": monitoring_status,
            "gate": gate_state,
            "live_enabled": config.live_enabled,
            "shadow_mode": config.shadow_mode,
            "recovery_mode": recovery.mode,
            "warnings": health.warnings,
            "packages": {
                "health": health.to_dict(),
                "recovery": recovery.to_dict(),
                "runtime_config": config.to_dict(),
                "model_versions": versions,
                "gate": gate_data,
            },
        }

        path = system_diagnostic_report_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload
