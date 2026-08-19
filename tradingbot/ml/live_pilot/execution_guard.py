"""Phase 12 — live pilot execution guard (sole MT5 order path in pilot package)."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.domain.models import ExecutionResult, TradingSignal
from tradingbot.ml.live_pilot.latency_tracker import LatencyTracker
from tradingbot.ml.live_pilot.safety_manager import SafetyManager
from tradingbot.ml.live_pilot.slippage_tracker import SlippageTracker
from tradingbot.ml.live_pilot.trade_journal import TradeJournal
from tradingbot.ports.execution import IOrderExecutor

logger = logging.getLogger(__name__)


class PilotExecutionGuard:
    """
    IOrderExecutor wrapper — only component in live_pilot allowed to delegate to Mt5ExecutionAdapter.
    """

    def __init__(
        self,
        inner: IOrderExecutor,
        *,
        safety: SafetyManager,
        journal: TradeJournal | None = None,
        latency: LatencyTracker | None = None,
        slippage: SlippageTracker | None = None,
        spread_provider: Any = None,
        regime_provider: Any = None,
    ) -> None:
        self._inner = inner
        self._safety = safety
        self._journal = journal
        self._latency = latency or LatencyTracker()
        self._slippage = slippage or SlippageTracker()
        self._spread_provider = spread_provider
        self._regime_provider = regime_provider
        self._stats = {"attempts": 0, "success": 0, "rejected": 0}

    @property
    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "latency": self._latency.summary(),
            "slippage": self._slippage.summary(),
        }

    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        self._stats["attempts"] += 1
        spread = self._spread_provider() if callable(self._spread_provider) else None
        regime = self._regime_provider() if callable(self._regime_provider) else None

        check = self._safety.validate_pre_order(
            signal,
            lot=lot,
            spread_pips=spread,
            regime=regime,
        )
        if self._journal:
            self._journal.log_order(
                {
                    "timestamp": (signal.metadata or {}).get("bar_timestamp"),
                    "symbol": signal.symbol,
                    "direction": signal.direction.name,
                    "volume": lot,
                    "entry": (signal.metadata or {}).get("entry"),
                    "sl": signal.stop_loss,
                    "tp": signal.take_profit,
                    "model_probability": (signal.metadata or {}).get("ml_probability"),
                    "safety_allowed": check.allowed,
                    "safety_reason": check.reason,
                }
            )

        if not check.allowed:
            self._stats["rejected"] += 1
            return ExecutionResult(success=False, message=f"safety_blocked:{check.reason}")

        self._latency.begin()
        result = self._inner.execute(signal, lot)
        latency_ms = self._latency.end(success=result.success, symbol=signal.symbol)

        if result.success:
            self._stats["success"] += 1
            self._safety.record_execution_success()
            self._safety.position_limiter.record_entry()
        else:
            self._safety.record_execution_failure()

        exec_row = {
            "timestamp": (signal.metadata or {}).get("bar_timestamp"),
            "symbol": signal.symbol,
            "direction": signal.direction.name,
            "volume": lot,
            "success": result.success,
            "message": result.message,
            "ticket": result.ticket,
            "execution_latency_ms": round(latency_ms, 2),
            "spread": spread,
        }
        if self._journal:
            self._journal.log_execution(exec_row)

        return result

    def manage_open_positions(self, market_key: str) -> None:
        if self._inner is not None:
            self._inner.manage_open_positions(market_key)


def create_mt5_executor(config: dict[str, Any]) -> IOrderExecutor:
    """Lazy factory — isolates Mt5ExecutionAdapter import to this module."""
    from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter

    return Mt5ExecutionAdapter(config)
