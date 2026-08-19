"""Phase 9.10 — paper trading performance metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from tradingbot.ml.paper_trading.position_manager import PaperPosition, PositionManager


@dataclass
class PerformanceMetrics:
    total_return: float = 0.0
    net_profit: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0
    num_signals: int = 0
    avg_holding_bars: float = 0.0
    sharpe_proxy: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceTracker:
    initial_equity: float = 10_000.0
    equity: float = 10_000.0
    peak_equity: float = 10_000.0
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    signal_count: int = 0

    def record_signal(self) -> None:
        self.signal_count += 1

    def apply_pnl(self, pnl: float, timestamp: str) -> None:
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        self.equity_curve.append(
            {"timestamp": timestamp, "equity": round(self.equity, 4), "drawdown": round(dd, 4)}
        )

    def snapshot(self, timestamp: str) -> None:
        dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if self.equity_curve and self.equity_curve[-1]["timestamp"] == timestamp:
            return
        self.equity_curve.append(
            {"timestamp": timestamp, "equity": round(self.equity, 4), "drawdown": round(dd, 4)}
        )

    def compute(self, manager: PositionManager) -> PerformanceMetrics:
        trades = manager.closed_trades
        m = PerformanceMetrics()
        m.num_trades = len(trades)
        m.num_signals = self.signal_count
        m.net_profit = round(self.equity - self.initial_equity, 4)
        m.total_return = round(m.net_profit / self.initial_equity, 4) if self.initial_equity else 0.0

        if not trades:
            m.max_drawdown = max((p["drawdown"] for p in self.equity_curve), default=0.0)
            return m

        pnls = np.array([t.pnl for t in trades], dtype=np.float64)
        rs = np.array([t.r_multiple for t in trades], dtype=np.float64)
        wins = pnls > 0
        m.win_rate = round(float(wins.mean()), 4)
        gross_profit = float(pnls[wins].sum()) if wins.any() else 0.0
        gross_loss = float(-pnls[~wins].sum()) if (~wins).any() else 0.0
        m.profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else round(gross_profit, 4)
        m.expectancy_r = round(float(rs.mean()), 4)
        m.avg_holding_bars = round(float(np.mean([t.bars_held for t in trades])), 2)
        std = float(np.std(pnls, ddof=1)) if len(pnls) > 1 else 0.0
        m.sharpe_proxy = round(float(np.mean(pnls) / std * np.sqrt(len(pnls))), 4) if std > 1e-12 else 0.0
        m.max_drawdown = round(max((p["drawdown"] for p in self.equity_curve), default=0.0), 4)
        return m
