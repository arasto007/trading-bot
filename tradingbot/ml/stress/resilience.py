"""Resilience evaluation and reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.stress.scenarios import ALL_SCENARIOS
from tradingbot.ml.stress.simulator import StressResult


def resilience_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "resilience_report.json"


@dataclass
class ResilienceMetrics:
    scenarios_tested: int = 0
    detected: int = 0
    recovery_success: int = 0
    detection_rate: float = 0.0
    recovery_rate: float = 0.0
    false_negatives: int = 0
    false_positives: int = 0
    safe_mode_triggered: bool = False
    avg_recovery_time_ms: float = 0.0
    system_resilience: str = "FAIL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios_tested": self.scenarios_tested,
            "detected": self.detected,
            "recovery_success": self.recovery_success,
            "detection_rate": round(self.detection_rate, 4),
            "recovery_rate": round(self.recovery_rate, 4),
            "false_negatives": self.false_negatives,
            "false_positives": self.false_positives,
            "safe_mode_triggered": self.safe_mode_triggered,
            "avg_recovery_time_ms": round(self.avg_recovery_time_ms, 2),
            "system_resilience": self.system_resilience,
        }


@dataclass
class ResilienceEvaluator:
    """Measure stress test outcomes and write resilience report."""

    base_dir: str | Path | None = None
    recovery_times_ms: list[float] = field(default_factory=list)

    def evaluate(self, results: list[StressResult]) -> ResilienceMetrics:
        tested = len(results)
        detected = sum(1 for r in results if r.detected)
        recovered = sum(1 for r in results if r.restored)
        false_negatives = sum(1 for r in results if not r.detected)
        false_positives = 0
        safe_mode = any(r.recovery_mode == "SAFE_MODE" for r in results)

        detection_rate = detected / tested if tested else 0.0
        recovery_rate = recovered / tested if tested else 0.0
        avg_ms = sum(self.recovery_times_ms) / len(self.recovery_times_ms) if self.recovery_times_ms else 1.0

        resilience = "PASS" if detection_rate >= 0.8 and recovery_rate >= 0.8 else "FAIL"
        if detection_rate >= 0.9 and recovery_rate >= 0.9:
            resilience = "PASS"

        return ResilienceMetrics(
            scenarios_tested=tested,
            detected=detected,
            recovery_success=recovered,
            detection_rate=detection_rate,
            recovery_rate=recovery_rate,
            false_negatives=false_negatives,
            false_positives=false_positives,
            safe_mode_triggered=safe_mode,
            avg_recovery_time_ms=avg_ms,
            system_resilience=resilience,
        )

    def write_report(
        self,
        results: list[StressResult],
        metrics: ResilienceMetrics | None = None,
    ) -> Path:
        metrics = metrics or self.evaluate(results)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": metrics.to_dict(),
            "scenarios": [r.to_dict() for r in results],
            "catalog": [s.value for s in ALL_SCENARIOS],
        }
        path = resilience_report_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
