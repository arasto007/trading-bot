"""Phase 11 — virtual portfolio manager."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.paper.paper_execution import VirtualOrder
from tradingbot.ml.paper.trade_lifecycle import PaperTrade, TradeLifecycle
from tradingbot.ml.paper.virtual_account import VirtualAccount


class PortfolioManager:
    """Manage one open virtual position at a time."""

    def __init__(self, account: VirtualAccount, lifecycle: TradeLifecycle) -> None:
        self.account = account
        self.lifecycle = lifecycle
        self.open_trade: PaperTrade | None = None
        self.closed_trades: list[PaperTrade] = []
        self.equity_curve: list[dict[str, Any]] = []

    def can_open(self) -> bool:
        return self.open_trade is None

    def open_position(self, order: VirtualOrder) -> PaperTrade:
        if not self.can_open():
            raise RuntimeError("Position already open")
        risk_amount = self.account.equity * order.risk_percent
        trade = self.lifecycle.open_trade(order, risk_amount=risk_amount)
        self.open_trade = trade
        self.account.register_open({**order.to_dict(), "risk_amount": risk_amount})
        return trade

    def monitor_bar(self, bar: pd.Series) -> PaperTrade | None:
        if self.open_trade is None:
            return None
        closed = self.lifecycle.monitor(self.open_trade, bar)
        if closed is None:
            return None
        self.account.apply_pnl(closed.pnl)
        self.account.register_close(closed.to_dict())
        self.closed_trades.append(closed)
        self.equity_curve.append(
            {
                "timestamp": closed.order.timestamp,
                "equity": round(self.account.equity, 4),
                "drawdown": round(self.account.drawdown, 4),
            }
        )
        self.open_trade = None
        return closed
