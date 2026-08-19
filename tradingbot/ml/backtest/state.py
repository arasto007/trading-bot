"""Trade state machine for Phase 8.7 backtesting."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TradeStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    SKIPPED = "skipped"


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class EquityPoint:
    timestamp: str
    equity: float
    drawdown: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "equity": self.equity, "drawdown": self.drawdown}


@dataclass
class SimulatedTrade:
    trade_id: int
    event_id: str
    timestamp: str
    symbol: str
    signal: SignalAction
    direction: int
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_unit: float
    risk_amount: float
    fill_price: float
    probability: float
    predicted_class: int
    label: int
    status: TradeStatus = TradeStatus.OPEN
    exit_price: float | None = None
    pnl: float = 0.0
    pnl_r: float = 0.0
    costs: float = 0.0
    bars_held: int = 0
    split: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "signal": self.signal.value,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_unit": self.risk_unit,
            "risk_amount": self.risk_amount,
            "fill_price": self.fill_price,
            "probability": self.probability,
            "predicted_class": self.predicted_class,
            "label": self.label,
            "status": self.status.value,
            "exit_price": self.exit_price,
            "pnl": round(self.pnl, 4),
            "pnl_r": round(self.pnl_r, 4),
            "costs": round(self.costs, 4),
            "bars_held": self.bars_held,
            "split": self.split,
        }


@dataclass
class BacktestState:
    """Mutable simulation state during chronological iteration."""

    initial_equity: float
    equity: float
    peak_equity: float
    open_trade: SimulatedTrade | None = None
    closed_trades: list[SimulatedTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    trade_counter: int = 0

    def record_equity(self, timestamp: str) -> None:
        peak = max(self.peak_equity, self.equity)
        self.peak_equity = peak
        dd = (peak - self.equity) / peak if peak > 0 else 0.0
        self.equity_curve.append(EquityPoint(timestamp=timestamp, equity=self.equity, drawdown=dd))

    def can_open_trade(self, max_open: int = 1) -> bool:
        return self.open_trade is None and max_open >= 1

    def close_open_trade(self, trade: SimulatedTrade) -> None:
        trade.status = TradeStatus.CLOSED
        self.equity += trade.pnl
        self.closed_trades.append(trade)
        self.open_trade = None
