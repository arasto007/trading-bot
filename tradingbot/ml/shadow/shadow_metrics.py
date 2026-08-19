"""Phase 10 — shadow replay metrics tracker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ShadowMetricsSnapshot:
    ml_buy_count: int = 0
    ml_sell_count: int = 0
    ml_hold_count: int = 0
    ml_total_signals: int = 0
    kernel_would_trade_count: int = 0
    risk_allowed_count: int = 0
    virtual_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    initial_equity: float = 0.0
    final_equity: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_r: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowMetricsTracker:
    """Accumulates Phase 10 virtual shadow run statistics."""

    def __init__(self, *, initial_equity: float, equity: float) -> None:
        self.initial_equity = float(initial_equity)
        self.equity = float(equity)
        self._ml_buy = 0
        self._ml_sell = 0
        self._ml_hold = 0
        self._kernel_yes = 0
        self._risk_yes = 0
        self._trades: list[dict[str, Any]] = []

    def record_ml_signal(self, direction: str, confidence: float) -> None:
        _ = confidence
        d = (direction or "HOLD").upper()
        if d == "BUY":
            self._ml_buy += 1
        elif d == "SELL":
            self._ml_sell += 1
        else:
            self._ml_hold += 1

    def record_kernel(self, would_kernel_trade: bool) -> None:
        if would_kernel_trade:
            self._kernel_yes += 1

    def record_risk(self, allowed: bool) -> None:
        if allowed:
            self._risk_yes += 1

    def record_trade_close(self, trade: dict[str, Any]) -> None:
        self._trades.append(dict(trade))
        self.equity += float(trade.get("pnl", 0.0))

    def compute(self) -> ShadowMetricsSnapshot:
        wins = sum(1 for t in self._trades if float(t.get("pnl", 0)) > 0)
        losses = sum(1 for t in self._trades if float(t.get("pnl", 0)) < 0)
        win_pnl = sum(float(t.get("pnl", 0)) for t in self._trades if float(t.get("pnl", 0)) > 0)
        loss_pnl = abs(sum(float(t.get("pnl", 0)) for t in self._trades if float(t.get("pnl", 0)) < 0))
        if loss_pnl > 0:
            pf = win_pnl / loss_pnl
        elif win_pnl > 0:
            pf = float("inf")
        else:
            pf = 0.0
        rs = [float(t.get("R_multiple", t.get("pnl_r", 0))) for t in self._trades]
        n = len(self._trades)
        return ShadowMetricsSnapshot(
            ml_buy_count=self._ml_buy,
            ml_sell_count=self._ml_sell,
            ml_hold_count=self._ml_hold,
            ml_total_signals=self._ml_buy + self._ml_sell + self._ml_hold,
            kernel_would_trade_count=self._kernel_yes,
            risk_allowed_count=self._risk_yes,
            virtual_trades=n,
            wins=wins,
            losses=losses,
            total_r=round(sum(rs), 4),
            initial_equity=self.initial_equity,
            final_equity=round(self.equity, 4),
            win_rate=round(wins / n, 4) if n else 0.0,
            profit_factor=round(pf, 4) if pf != float("inf") else pf,
            avg_r=round(sum(rs) / n, 4) if n else 0.0,
        )
