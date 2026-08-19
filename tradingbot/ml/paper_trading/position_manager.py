"""Phase 9.10 — hypothetical position lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperPosition:
    trade_id: int
    timestamp: str
    symbol: str
    direction: int
    entry: float
    fill_price: float
    stop_loss: float
    take_profit: float
    risk_unit: float
    risk_amount: float
    probability: float
    signal: str
    bars_held: int = 0
    exit: float | None = None
    result: str | None = None
    r_multiple: float = 0.0
    pnl: float = 0.0
    closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": round(self.entry, 4),
            "exit": round(self.exit, 4) if self.exit is not None else None,
            "sl": round(self.stop_loss, 4),
            "tp": round(self.take_profit, 4),
            "result": self.result,
            "R_multiple": round(self.r_multiple, 4),
            "duration": self.bars_held,
            "probability": round(self.probability, 6),
            "signal": self.signal,
            "pnl": round(self.pnl, 4),
        }


@dataclass
class PositionManager:
    max_open: int = 1
    open_position: PaperPosition | None = None
    closed_trades: list[PaperPosition] = field(default_factory=list)
    trade_counter: int = 0
    last_signal_ts: str | None = None
    signaled_timestamps: set[str] = field(default_factory=set)

    def can_open(self) -> bool:
        return self.open_position is None and self.max_open >= 1

    def can_signal(self, timestamp: str) -> bool:
        return timestamp not in self.signaled_timestamps

    def open(
        self,
        *,
        timestamp: str,
        symbol: str,
        direction: int,
        entry: float,
        fill_price: float,
        stop_loss: float,
        take_profit: float,
        risk_unit: float,
        risk_amount: float,
        probability: float,
        signal: str,
    ) -> PaperPosition:
        if not self.can_open():
            raise RuntimeError("Cannot open: position already active")
        if self.last_signal_ts == timestamp:
            raise RuntimeError("Duplicate signal on same timestamp")
        self.signaled_timestamps.add(timestamp)
        self.trade_counter += 1
        pos = PaperPosition(
            trade_id=self.trade_counter,
            timestamp=timestamp,
            symbol=symbol,
            direction=direction,
            entry=entry,
            fill_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_unit=risk_unit,
            risk_amount=risk_amount,
            probability=probability,
            signal=signal,
        )
        self.open_position = pos
        self.last_signal_ts = timestamp
        return pos

    def close(self, result: str, exit_price: float, r_multiple: float, pnl: float) -> None:
        if self.open_position is None:
            return
        pos = self.open_position
        pos.closed = True
        pos.result = result
        pos.exit = exit_price
        pos.r_multiple = r_multiple
        pos.pnl = pnl
        self.closed_trades.append(pos)
        self.open_position = None

    def update_bar(self) -> None:
        if self.open_position is not None:
            self.open_position.bars_held += 1
