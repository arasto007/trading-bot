"""Phase 20A — execution guard with full live logging."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tradingbot.domain.models import ExecutionResult, TradingSignal
from tradingbot.ml.live_pilot.execution_guard import PilotExecutionGuard, create_mt5_executor
from tradingbot.ml.phase20a.config import is_live_execution_enabled
from tradingbot.ml.phase20a.reporter import Phase20aReporter
from tradingbot.ml.phase20a.safety_monitor import Phase20aSafetyMonitor
from tradingbot.ports.execution import IOrderExecutor


class Phase20aExecutionGuard(IOrderExecutor):
    """Wraps MT5 execution with pilot safety + Phase 20A monitoring."""

    def __init__(
        self,
        inner: IOrderExecutor,
        *,
        safety: Phase20aSafetyMonitor,
        reporter: Phase20aReporter,
        spread_provider: Any = None,
        regime_provider: Any = None,
    ) -> None:
        self._pilot = PilotExecutionGuard(
            inner,
            safety=safety.pilot_safety,
            journal=None,
            spread_provider=spread_provider,
            regime_provider=regime_provider,
        )
        self._safety = safety
        self._reporter = reporter

    @property
    def stats(self) -> dict[str, Any]:
        return self._pilot.stats

    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        if not is_live_execution_enabled():
            self._reporter.log_execution({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": signal.symbol,
                "direction": signal.direction.name,
                "blocked": True,
                "reason": "live_not_enabled",
            })
            return ExecutionResult(success=False, message="phase20a_live_not_enabled")

        if self._safety.should_stop:
            return ExecutionResult(success=False, message="phase20a_safety_stop")

        result = self._pilot.execute(signal, lot)
        self._reporter.log_execution({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.symbol,
            "direction": signal.direction.name,
            "volume": lot,
            "success": result.success,
            "message": result.message,
            "ticket": result.ticket,
        })
        if result.success:
            self._reporter.log_trade({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": signal.symbol,
                "direction": signal.direction.name,
                "volume": lot,
                "ticket": result.ticket,
            })
            self._safety.record_execution_success()
        else:
            self._safety.record_execution_failure()

        return result

    def manage_open_positions(self, market_key: str) -> None:
        self._pilot.manage_open_positions(market_key)


def build_phase20a_executor(
    legacy_config: dict[str, Any],
    *,
    safety: Phase20aSafetyMonitor,
    reporter: Phase20aReporter,
) -> Phase20aExecutionGuard:
    inner = create_mt5_executor(legacy_config)
    return Phase20aExecutionGuard(inner, safety=safety, reporter=reporter)
