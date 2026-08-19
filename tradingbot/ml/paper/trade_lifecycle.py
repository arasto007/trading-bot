"""Phase 11 — paper trade lifecycle with MAE/MFE."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.paper.paper_execution import VirtualOrder
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker


@dataclass
class PaperTrade:
    trade_id: int
    order: VirtualOrder
    direction: int
    risk_amount: float
    bars_held: int = 0
    mae: float = 0.0
    mfe: float = 0.0
    status: str = "OPEN"
    exit_price: float | None = None
    result: str | None = None
    r_multiple: float = 0.0
    pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            **self.order.to_dict(),
            "direction_int": self.direction,
            "exit": round(self.exit_price, 6) if self.exit_price is not None else None,
            "result": self.result,
            "R_multiple": round(self.r_multiple, 4),
            "pnl": round(self.pnl, 4),
            "duration": self.bars_held,
            "mae": round(self.mae, 6),
            "mfe": round(self.mfe, 6),
            "status": self.status,
        }


class TradeLifecycle:
    """OPEN → MONITOR → CLOSE virtual paper trades."""

    def __init__(self, *, tp_r: float = 2.0, sl_r: float = 1.0, max_hold_bars: int = 72) -> None:
        self.tp_r = tp_r
        self.sl_r = sl_r
        self.max_hold_bars = max_hold_bars
        self._broker = PaperBroker(BrokerConfig(tp_r=tp_r, sl_r=sl_r))
        self._counter = 0

    def open_trade(self, order: VirtualOrder, *, risk_amount: float) -> PaperTrade:
        self._counter += 1
        direction = 1 if order.direction == "BUY" else -1
        return PaperTrade(
            trade_id=self._counter,
            order=order,
            direction=direction,
            risk_amount=risk_amount,
        )

    def monitor(self, trade: PaperTrade, bar: pd.Series) -> PaperTrade | None:
        trade.bars_held += 1
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        if trade.direction > 0:
            trade.mae = max(trade.mae, max(0.0, trade.order.entry - low))
            trade.mfe = max(trade.mfe, max(0.0, high - trade.order.entry))
        else:
            trade.mae = max(trade.mae, max(0.0, high - trade.order.entry))
            trade.mfe = max(trade.mfe, max(0.0, trade.order.entry - low))

        hit = self._broker.resolve_bar(
            bar,
            direction=trade.direction,
            stop_loss=trade.order.sl,
            take_profit=trade.order.tp,
        )
        if hit:
            result, exit_px = hit
            return self._close(trade, result, exit_px)

        if trade.bars_held >= self.max_hold_bars:
            return self._close(trade, "TIMEOUT", close)
        return None

    def _close(self, trade: PaperTrade, result: str, exit_px: float) -> PaperTrade:
        trade.status = "CLOSED"
        trade.result = result
        trade.exit_price = exit_px
        trade.r_multiple = self.tp_r if result == "TP" else (-self.sl_r if result == "SL" else 0.0)
        trade.pnl = trade.r_multiple * trade.risk_amount
        return trade
