"""Phase 11 — virtual paper account (no MT5 account coupling)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VirtualAccount:
    initial_balance: float = 10_000.0
    balance: float = 10_000.0
    equity: float = 10_000.0
    margin_used: float = 0.0
    peak_equity: float = 10_000.0
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_positions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    def apply_pnl(self, pnl: float) -> None:
        self.balance += pnl
        self.equity = self.balance
        self.peak_equity = max(self.peak_equity, self.equity)

    def register_open(self, position: dict[str, Any]) -> None:
        self.open_positions = [position]
        self.margin_used = float(position.get("risk_amount", 0.0))

    def register_close(self, position: dict[str, Any]) -> None:
        self.open_positions = []
        self.margin_used = 0.0
        self.closed_positions.append(position)

    def snapshot(self) -> dict[str, Any]:
        return {
            "initial_balance": round(self.initial_balance, 4),
            "balance": round(self.balance, 4),
            "equity": round(self.equity, 4),
            "margin_used": round(self.margin_used, 4),
            "drawdown": round(self.drawdown, 4),
            "open_positions": len(self.open_positions),
            "closed_positions": len(self.closed_positions),
        }
