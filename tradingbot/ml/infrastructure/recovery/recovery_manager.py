"""Recovery manager — corrupted reports, missing files, stale data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root, reports_dir


class RecoveryMode(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    SAFE_MODE = "SAFE_MODE"
    FAILED = "FAILED"


@dataclass
class RecoveryIssue:
    category: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category, "path": self.path, "message": self.message}


@dataclass
class RecoveryReport:
    mode: str
    issues: list[RecoveryIssue] = field(default_factory=list)
    fallback_actions: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "issues": [i.to_dict() for i in self.issues],
            "fallback_actions": self.fallback_actions,
            "timestamp": self.timestamp,
        }


@dataclass
class RecoveryManager:
    """
    Detect infrastructure issues and select graceful fallback mode.

    No automatic trading actions.
    """

    base_dir: str | Path | None = None
    stale_hours: float = 168.0

    def assess(self, symbol: str, timeframe: str = "M5") -> RecoveryReport:
        issues: list[RecoveryIssue] = []
        checks = [
            self._check_report("readiness", ml_root(self.base_dir) / "deployment" / "readiness_report.json"),
            self._check_report("live_gate", ml_root(self.base_dir) / "live_gate" / "live_gate_report.json"),
            self._check_report("monitoring", reports_dir(self.base_dir) / "monitoring_summary.json"),
            self._check_report("paper_trading", reports_dir(self.base_dir) / "paper_trading_report.json"),
            self._check_report("diagnostic", reports_dir(self.base_dir) / "system_diagnostic_report.json"),
        ]
        for issue in checks:
            if issue:
                issues.append(issue)

        stale = self._check_stale(reports_dir(self.base_dir) / "monitoring_summary.json")
        if stale:
            issues.append(stale)

        mode = self._select_mode(issues)
        actions = self._fallback_actions(mode)
        return RecoveryReport(
            mode=mode,
            issues=issues,
            fallback_actions=actions,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _check_report(self, category: str, path: Path) -> RecoveryIssue | None:
        if not path.is_file():
            return RecoveryIssue(category, str(path), "File missing")
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return RecoveryIssue(category, str(path), "Corrupted JSON report")
        return None

    def _check_stale(self, path: Path) -> RecoveryIssue | None:
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600.0
        if age > self.stale_hours:
            return RecoveryIssue("stale_data", str(path), f"Data stale ({age:.0f}h old)")
        return None

    @staticmethod
    def _select_mode(issues: list[RecoveryIssue]) -> str:
        if any(i.message == "Corrupted JSON report" for i in issues):
            return RecoveryMode.FAILED.value
        missing = sum(1 for i in issues if i.message == "File missing")
        if missing >= 3:
            return RecoveryMode.SAFE_MODE.value
        if issues:
            return RecoveryMode.DEGRADED.value
        return RecoveryMode.NORMAL.value

    @staticmethod
    def _fallback_actions(mode: str) -> list[str]:
        if mode == RecoveryMode.NORMAL.value:
            return ["Continue shadow operations"]
        if mode == RecoveryMode.DEGRADED.value:
            return ["Use cached reports where available", "Remain in shadow mode"]
        if mode == RecoveryMode.SAFE_MODE.value:
            return ["Shadow-only mode enforced", "Regenerate missing reports", "No live activation"]
        return ["Halt non-essential ML pipelines", "Manual recovery required", "Shadow-only enforced"]
