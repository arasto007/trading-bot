"""Stress scenario runner — apply, diagnose, restore."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.infrastructure.diagnostics.diagnostic_report import DiagnosticReportGenerator
from tradingbot.ml.infrastructure.health.health_checker import HealthChecker
from tradingbot.ml.infrastructure.health.schema import ComponentHealth, HealthStatus, SystemHealthReport, utc_now_iso
from tradingbot.ml.infrastructure.recovery.recovery_manager import RecoveryManager
from tradingbot.ml.stress.chaos_tests import StressSandbox
from tradingbot.ml.stress.scenarios import ALL_SCENARIOS, FailureScenario, get_scenario


@dataclass
class StressResult:
    scenario: str
    detected: bool
    recovery_mode: str
    alerts_generated: list[str] = field(default_factory=list)
    failed_components: list[str] = field(default_factory=list)
    timestamp: str = ""
    system_status: str = ""
    restored: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StressScenarioRunner:
    """Apply simulated failure, run diagnostics, collect response, restore."""

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    stale_hours: float = 1.0

    def run_scenario(self, sandbox: StressSandbox, scenario: FailureScenario) -> StressResult:
        spec = get_scenario(scenario)
        sandbox.seed_baseline()
        sandbox.apply_scenario(scenario)

        health, diagnostic, recovery = self._run_checks(sandbox)

        failed = [
            c.name
            for c in health.components
            if c.status in ("FAILED", "DEGRADED", "WARNING")
        ]
        alerts = list(diagnostic.get("warnings", []))
        if recovery.mode != "NORMAL":
            alerts.append(f"recovery:{recovery.mode}")
        if health.overall_status != HealthStatus.HEALTHY.value:
            alerts.append(f"system:{health.overall_status}")

        detected = self._was_detected(spec.expected_components, failed, recovery.mode, spec.expected_recovery_modes)

        sandbox.restore_all()
        sandbox.seed_baseline()
        post = RecoveryManager(sandbox.base_dir, stale_hours=self.stale_hours).assess(
            self.symbol, self.timeframe
        )
        restored = post.mode in ("NORMAL", "DEGRADED")

        return StressResult(
            scenario=scenario.value,
            detected=detected,
            recovery_mode=recovery.mode,
            alerts_generated=alerts,
            failed_components=failed,
            timestamp=datetime.now(timezone.utc).isoformat(),
            system_status=health.overall_status,
            restored=restored,
            details={
                "expected_components": list(spec.expected_components),
                "diagnostic_system": diagnostic.get("system"),
                "recovery_issues": [i.to_dict() for i in recovery.issues],
            },
        )

    def run_all(self, sandbox: StressSandbox) -> list[StressResult]:
        results: list[StressResult] = []
        for scenario in ALL_SCENARIOS:
            sandbox.restore_all()
            results.append(self.run_scenario(sandbox, scenario))
        return results

    def _run_checks(self, sandbox: StressSandbox) -> tuple[SystemHealthReport, dict[str, Any], Any]:
        try:
            health = HealthChecker(sandbox.base_dir, stale_hours=self.stale_hours).check_all(
                self.symbol, self.timeframe
            )
        except json.JSONDecodeError as exc:
            health = SystemHealthReport(
                timestamp=utc_now_iso(),
                symbol=self.symbol,
                timeframe=self.timeframe,
                overall_status=HealthStatus.FAILED.value,
                components=[
                    ComponentHealth("model", HealthStatus.FAILED.value, f"Corrupted metadata: {exc}")
                ],
                warnings=["Corrupted JSON detected during health check"],
            )

        recovery = RecoveryManager(sandbox.base_dir, stale_hours=self.stale_hours).assess(
            self.symbol, self.timeframe
        )

        try:
            diagnostic = DiagnosticReportGenerator(sandbox.base_dir).generate(self.symbol, self.timeframe)
        except json.JSONDecodeError:
            diagnostic = {
                "system": HealthStatus.FAILED.value,
                "warnings": ["Corrupted JSON detected during diagnostics"],
                "recovery_mode": recovery.mode,
            }

        return health, diagnostic, recovery

    @staticmethod
    def _was_detected(
        expected_components: tuple[str, ...],
        failed_components: list[str],
        recovery_mode: str,
        expected_recovery_modes: tuple[str, ...],
    ) -> bool:
        component_hit = any(c in failed_components for c in expected_components)
        recovery_hit = recovery_mode in expected_recovery_modes
        return component_hit or recovery_hit or len(failed_components) > 0
