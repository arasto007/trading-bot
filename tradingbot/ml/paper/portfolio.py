"""Portfolio tracking for paper trading simulation."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from tradingbot.ml.paper._types import PaperTrade, TradeStatus


@dataclass
class Portfolio:
    """Track balance, equity, trades, drawdown, streaks (R units)."""

    initial_balance_r: float = 100.0
    compounding: bool = False
    balance_r: float = 100.0
    equity_r: float = 100.0
    peak_equity_r: float = 100.0
    max_drawdown_r: float = 0.0
    open_trades: list[PaperTrade] = field(default_factory=list)
    closed_trades: list[PaperTrade] = field(default_factory=list)
    win_streak: int = 0
    loss_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    equity_curve: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.balance_r = self.initial_balance_r
        self.equity_r = self.initial_balance_r
        self.peak_equity_r = self.initial_balance_r
        self.equity_curve = [self.initial_balance_r]

    def add_open(self, trade: PaperTrade) -> None:
        self.open_trades.append(trade)

    def close_trade(self, trade: PaperTrade) -> None:
        if trade in self.open_trades:
            self.open_trades.remove(trade)
        trade.status = TradeStatus.CLOSED.value
        self.closed_trades.append(trade)
        self._apply_r(trade.r_multiple)
        self._update_streaks(trade.r_multiple)
        self._mark_equity()

    def _apply_r(self, r_multiple: float) -> None:
        if self.compounding:
            self.balance_r += r_multiple
        else:
            self.balance_r = self.initial_balance_r + sum(t.r_multiple for t in self.closed_trades)
        self.equity_r = self.balance_r

    def _update_streaks(self, r_multiple: float) -> None:
        if r_multiple > 0:
            self.win_streak += 1
            self.loss_streak = 0
        elif r_multiple < 0:
            self.loss_streak += 1
            self.win_streak = 0
        self.max_win_streak = max(self.max_win_streak, self.win_streak)
        self.max_loss_streak = max(self.max_loss_streak, self.loss_streak)

    def _mark_equity(self) -> None:
        self.peak_equity_r = max(self.peak_equity_r, self.equity_r)
        dd = self.peak_equity_r - self.equity_r
        self.max_drawdown_r = max(self.max_drawdown_r, dd)
        self.equity_curve.append(round(self.equity_r, 4))

    @property
    def total_return_r(self) -> float:
        return round(self.equity_r - self.initial_balance_r, 4)

    def r_multiples(self) -> list[float]:
        return [t.r_multiple for t in self.closed_trades if t.status == TradeStatus.CLOSED.value]
