"""Dynamic strategy selection — RULE / ML / HYBRID / ENSEMBLE / SAFE."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.abtest.schema import WINNER_HYBRID, WINNER_RULE
from tradingbot.ml.monitoring.schema import PerformanceState
from tradingbot.ml.orchestrator.schema import OrchestratorSnapshot, StrategyMode


@dataclass
class StrategySelector:
    """Select active strategy from performance, A/B winner, and alerts."""

    def select(self, snapshot: OrchestratorSnapshot) -> str:
        if snapshot.performance_state == PerformanceState.FAILED.value:
            return StrategyMode.SAFE_MODE.value

        critical_alerts = {
            a for a in snapshot.alerts
            if any(k in a.upper() for k in ("CRITICAL", "FAILED", "DEGRADED"))
        }
        if critical_alerts and snapshot.max_drawdown_r >= 20.0:
            return StrategyMode.SAFE_MODE.value

        if snapshot.performance_state == PerformanceState.DEGRADED.value:
            if snapshot.ab_winner == WINNER_RULE:
                return StrategyMode.RULE_ONLY.value
            return StrategyMode.HYBRID.value

        if snapshot.ab_winner == WINNER_HYBRID and snapshot.paper_expectancy_r > 0:
            return StrategyMode.ENSEMBLE.value
        if snapshot.ab_winner == WINNER_RULE:
            return StrategyMode.RULE_ONLY.value
        if snapshot.ab_winner == WINNER_HYBRID:
            return StrategyMode.HYBRID.value

        if snapshot.performance_state == PerformanceState.HEALTHY.value:
            return StrategyMode.ENSEMBLE.value

        return StrategyMode.HYBRID.value
