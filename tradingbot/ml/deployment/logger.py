"""Live readiness report persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.deployment.schema import LiveReadinessReport


def deployment_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "deployment"


def readiness_report_path(base_dir: str | Path | None = None) -> Path:
    return deployment_dir(base_dir) / "readiness_report.json"


class DeploymentLogger:
    """Write readiness_report.json with full evaluation trace."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir
        deployment_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return readiness_report_path(self.base_dir)

    def write(self, report: LiveReadinessReport | dict[str, Any]) -> Path:
        payload = report.to_dict() if isinstance(report, LiveReadinessReport) else dict(report)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.path

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))
