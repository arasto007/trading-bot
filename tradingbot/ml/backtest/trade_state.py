"""Trade state machine for Phase 9.7 backtesting."""

from __future__ import annotations

from enum import Enum

from tradingbot.ml.backtest.state import (
    BacktestState,
    EquityPoint,
    SignalAction,
    SimulatedTrade,
    TradeStatus,
)


class PositionState(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStateMachine:
    """Position lifecycle: FLAT -> LONG/SHORT -> FLAT."""

    def __init__(self) -> None:
        self.position: PositionState = PositionState.FLAT
        self.open_trade: SimulatedTrade | None = None

    @property
    def is_flat(self) -> bool:
        return self.position == PositionState.FLAT

    def can_enter(self, max_open: int = 1) -> bool:
        return self.is_flat and max_open >= 1

    def enter(self, trade: SimulatedTrade) -> None:
        if not self.is_flat:
            raise RuntimeError("Cannot enter while position is open")
        self.open_trade = trade
        self.position = PositionState.LONG if trade.direction > 0 else PositionState.SHORT

    def close(self, trade: SimulatedTrade) -> None:
        trade.status = TradeStatus.CLOSED
        self.open_trade = None
        self.position = PositionState.FLAT


__all__ = [
    "BacktestState",
    "EquityPoint",
    "PositionState",
    "SignalAction",
    "SimulatedTrade",
    "TradeStateMachine",
    "TradeStatus",
]
