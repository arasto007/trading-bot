"""Accounting ledger — balance, equity, drawdown, trade records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClosedTradeRecord:
    trade_id: str
    timestamp: str
    exit_timestamp: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    lot: float
    pnl: float
    pnl_r: float
    sl: float | None = None
    tp: float | None = None
    exit_reason: str = ""
    duration_bars: int = 0
    duration_sec: int = 0
    mae: float = 0.0
    mfe: float = 0.0
    spread: float = 0.0
    partial_close_applied: bool = False
    partial_pnl: float = 0.0
    rr: float | None = None
    regime: str = ""
    engine: str = ""
    confidence: float = 0.0
    risk_percent: float = 0.0
    actual_risk_percent: float = 0.0
    risk_deviation_percent: float = 0.0
    min_lot_limit_applied: bool = False
    sizing: dict[str, Any] = field(default_factory=dict)
    bar_index: int | None = None
    timeframe: str = "M5"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp,
            "exit_timestamp": self.exit_timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "regime": self.regime,
            "engine": self.engine,
            "confidence": self.confidence,
            "sl": self.sl,
            "tp": self.tp,
            "lot": self.lot,
            "entry_price": self.entry_price,
            "fill_price": self.entry_price,
            "exit_price": self.exit_price,
            "spread": self.spread,
            "risk_percent": self.risk_percent,
            "actual_risk_percent": self.actual_risk_percent,
            "risk_deviation_percent": self.risk_deviation_percent,
            "min_lot_limit_applied": self.min_lot_limit_applied,
            "sizing": self.sizing,
            "rr": self.rr,
            "pnl": self.pnl,
            "pnl_r": self.pnl_r,
            "duration_bars": self.duration_bars,
            "duration_sec": self.duration_sec,
            "mae": self.mae,
            "mfe": self.mfe,
            "exit_reason": self.exit_reason,
            "partial_close_applied": self.partial_close_applied,
            "partial_pnl": self.partial_pnl,
            "bar_index": self.bar_index,
        }


@dataclass
class AccountingLedger:
    """Single ledger for balance, equity, realized PnL, and drawdown."""

    initial_balance: float
    balance: float = 0.0
    equity: float = 0.0
    realized_pnl: float = 0.0
    floating_pnl: float = 0.0
    peak_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    closed_trades: list[ClosedTradeRecord] = field(default_factory=list)
    balance_curve: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    drawdown_curve: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self.peak_equity = self.initial_balance
        self.balance_curve = [{"timestamp": None, "balance": self.balance}]
        self.equity_curve = [{"timestamp": None, "equity": self.equity}]
        self.drawdown_curve = [{"timestamp": None, "drawdown_pct": 0.0}]

    def apply_close(self, trade: ClosedTradeRecord) -> None:
        pnl = float(trade.pnl)
        self.realized_pnl = round(self.realized_pnl + pnl, 4)
        self.balance = round(self.balance + pnl, 4)
        self.floating_pnl = 0.0
        self.equity = self.balance
        self.peak_equity = max(self.peak_equity, self.equity)
        dd_abs = self.peak_equity - self.equity
        dd_pct = (dd_abs / self.peak_equity * 100) if self.peak_equity > 0 else 0.0
        self.max_drawdown_abs = max(self.max_drawdown_abs, dd_abs)
        self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)
        self.closed_trades.append(trade)
        ts = trade.exit_timestamp
        self.balance_curve.append({"timestamp": ts, "balance": self.balance})
        self.equity_curve.append({"timestamp": ts, "equity": self.equity})
        self.drawdown_curve.append({"timestamp": ts, "drawdown_pct": round(dd_pct, 4)})

    def update_floating(self, floating_pnl: float) -> None:
        self.floating_pnl = round(floating_pnl, 4)
        self.equity = round(self.balance + self.floating_pnl, 4)
        self.peak_equity = max(self.peak_equity, self.equity)
        dd_abs = self.peak_equity - self.equity
        dd_pct = (dd_abs / self.peak_equity * 100) if self.peak_equity > 0 else 0.0
        self.max_drawdown_abs = max(self.max_drawdown_abs, dd_abs)
        self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)

    def snapshot(self) -> dict[str, Any]:
        return {
            "initial_balance": self.initial_balance,
            "balance": self.balance,
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "floating_pnl": self.floating_pnl,
            "peak_equity": self.peak_equity,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_abs": round(self.max_drawdown_abs, 4),
            "trade_count": len(self.closed_trades),
        }

    def export_trades(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.closed_trades]
