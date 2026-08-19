"""Live gate report persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.deployment.logger import readiness_report_path
from tradingbot.ml.deployment.schema import LiveReadinessReport
from tradingbot.ml.live_gate.gate_engine import LiveGateEngine
from tradingbot.ml.live_gate.schema import LiveGateReport, LivePermission, utc_now_iso


def live_gate_report_path(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "live_gate" / "live_gate_report.json"


class LiveGateLogger:
    """Write live_gate_report.json from Phase 6.4 readiness output."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir
        live_gate_report_path(base_dir).parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return live_gate_report_path(self.base_dir)

    def write(self, report: LiveGateReport | dict[str, Any]) -> Path:
        payload = report.to_dict() if isinstance(report, LiveGateReport) else dict(report)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.path

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write_from_readiness(
        self,
        readiness: LiveReadinessReport,
        *,
        permission: LivePermission | None = None,
    ) -> Path:
        engine = LiveGateEngine()
        perm = permission or engine.evaluate(readiness)
        gate_report = LiveGateReport(
            timestamp=utc_now_iso(),
            symbol=readiness.symbol,
            timeframe=readiness.timeframe,
            permission=perm,
            execution_enabled=False,
        )
        return self.write(gate_report)

    def load_readiness_report(self) -> LiveReadinessReport | None:
        path = readiness_report_path(self.base_dir)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LiveReadinessReport.from_dict(data)

    def run_from_phase_6_4(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        readiness = self.load_readiness_report()
        if readiness is None:
            from tradingbot.ml.deployment.live_readiness_engine import LiveReadinessEngine

            readiness = LiveReadinessEngine(base_dir=self.base_dir).evaluate_readiness(
                symbol,
                timeframe,
                write_report=True,
            )
        self.write_from_readiness(readiness)
        permission = LiveGateEngine().evaluate(readiness)
        return {
            "permission": permission.to_dict(),
            "readiness_score": readiness.score,
            "report_path": str(self.path),
        }
