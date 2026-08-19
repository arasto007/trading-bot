"""Phase 10.1 — blocks real execution in ML shadow mode."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from tradingbot.domain.models import ExecutionResult, TradingSignal
from tradingbot.ml.integration.config import is_ml_shadow_mode
from tradingbot.ports.execution import IOrderExecutor

logger = logging.getLogger(__name__)


@dataclass
class VirtualOrder:
    timestamp: str
    symbol: str
    timeframe: str
    direction: str
    lot: float
    entry: float | None
    sl: float | None
    tp: float | None
    probability: float | None
    status: str = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "lot": self.lot,
            "entry": self.entry,
            "sl": self.sl,
            "tp": self.tp,
            "ml_probability": self.probability,
            "status": self.status,
        }


class ShadowExecutionGuard:
    """
    IOrderExecutor wrapper: logs virtual orders, never sends real orders when ML_SHADOW_MODE=true.
    """

    def __init__(self, inner: IOrderExecutor | None = None) -> None:
        self._inner = inner
        self.blocked_orders: list[VirtualOrder] = []
        self.virtual_trades: list[dict[str, Any]] = []

    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        meta = signal.metadata or {}
        virtual = VirtualOrder(
            timestamp=str(meta.get("bar_timestamp", "")),
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=signal.direction.name,
            lot=lot,
            entry=float(meta.get("entry", 0.0) or 0.0) or None,
            sl=signal.stop_loss,
            tp=signal.take_profit,
            probability=meta.get("ml_probability"),
            status="blocked",
        )
        self.blocked_orders.append(virtual)

        if is_ml_shadow_mode():
            logger.info(
                "SHADOW_BLOCKED: %s %s lot=%s prob=%s",
                signal.symbol,
                signal.direction.name,
                lot,
                meta.get("ml_probability"),
            )
            self.virtual_trades.append(
                {
                    **virtual.to_dict(),
                    "execution_status": "shadow_blocked",
                    "message": "real order not sent",
                }
            )
            return ExecutionResult(success=False, message="shadow_blocked — real order not sent")

        if self._inner is not None:
            return self._inner.execute(signal, lot)

        return ExecutionResult(success=False, message="no executor configured")

    def manage_open_positions(self, market_key: str) -> None:
        if self._inner is not None:
            self._inner.manage_open_positions(market_key)
