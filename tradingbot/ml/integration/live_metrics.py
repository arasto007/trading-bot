"""Phase 10.2 — live shadow performance metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


@dataclass
class LiveShadowMetrics:
    kernel_cycles: int = 0
    ml_predictions: int = 0
    ml_buy: int = 0
    ml_sell: int = 0
    ml_hold: int = 0
    ml_confidence_mean: float = 0.0
    kernel_accepted: int = 0
    kernel_rejected: int = 0
    risk_allowed: int = 0
    risk_blocked: int = 0
    risk_block_reasons: dict[str, int] = field(default_factory=dict)
    avg_spread: float = 0.0
    spread_p50: float = 0.0
    virtual_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    max_drawdown: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    execution_blocked: int = 0
    ml_in_kernel: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LiveMetricsTracker:
    initial_equity: float = 10_000.0
    equity: float = 10_000.0
    peak_equity: float = 10_000.0
    confidence_samples: list[float] = field(default_factory=list)
    spread_samples: list[float] = field(default_factory=list)
    ml_buy: int = 0
    ml_sell: int = 0
    ml_hold: int = 0
    kernel_accepted: int = 0
    kernel_rejected: int = 0
    risk_allowed: int = 0
    risk_blocked: int = 0
    risk_reasons: dict[str, int] = field(default_factory=dict)
    execution_blocked: int = 0
    ml_in_kernel: int = 0
    cycles: int = 0
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def record_cycle(
        self,
        *,
        ml_direction: str,
        confidence: float,
        spread: float | None,
        kernel_has_signal: bool,
        ml_in_kernel: bool,
        risk_allowed: bool | None,
        risk_reason: str | None,
        execution_blocked: bool,
    ) -> None:
        self.cycles += 1
        d = ml_direction.upper()
        if d == "BUY":
            self.ml_buy += 1
        elif d == "SELL":
            self.ml_sell += 1
        else:
            self.ml_hold += 1
        self.confidence_samples.append(confidence)
        if spread is not None:
            self.spread_samples.append(spread)
        if kernel_has_signal:
            self.kernel_accepted += 1
        else:
            self.kernel_rejected += 1
        if ml_in_kernel:
            self.ml_in_kernel += 1
        if risk_allowed is not None:
            if risk_allowed:
                self.risk_allowed += 1
            else:
                self.risk_blocked += 1
                key = (risk_reason or "unknown").split("(")[0].strip()
                self.risk_reasons[key] = self.risk_reasons.get(key, 0) + 1
        if execution_blocked:
            self.execution_blocked += 1

    def record_trade(self, trade: dict[str, Any]) -> None:
        pnl = float(trade.get("pnl", 0.0))
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        self.equity_curve.append(
            {
                "timestamp": trade.get("timestamp"),
                "equity": round(self.equity, 4),
                "drawdown": round(dd, 4),
            }
        )
        self.closed_trades.append(trade)

    def compute(self) -> LiveShadowMetrics:
        m = LiveShadowMetrics()
        m.kernel_cycles = self.cycles
        m.ml_predictions = self.ml_buy + self.ml_sell + self.ml_hold
        m.ml_buy = self.ml_buy
        m.ml_sell = self.ml_sell
        m.ml_hold = self.ml_hold
        m.kernel_accepted = self.kernel_accepted
        m.kernel_rejected = self.kernel_rejected
        m.risk_allowed = self.risk_allowed
        m.risk_blocked = self.risk_blocked
        m.risk_block_reasons = dict(self.risk_reasons)
        m.execution_blocked = self.execution_blocked
        m.ml_in_kernel = self.ml_in_kernel
        m.virtual_trades = len(self.closed_trades)

        if self.confidence_samples:
            arr = np.array(self.confidence_samples, dtype=np.float64)
            m.ml_confidence_mean = round(float(arr.mean()), 4)
        if self.spread_samples:
            sp = np.array(self.spread_samples, dtype=np.float64)
            m.avg_spread = round(float(sp.mean()), 4)
            m.spread_p50 = round(float(np.percentile(sp, 50)), 4)

        if not self.closed_trades:
            return m

        pnls = np.array([float(t.get("pnl", 0.0)) for t in self.closed_trades], dtype=np.float64)
        rs = np.array([float(t.get("R_multiple", 0.0)) for t in self.closed_trades], dtype=np.float64)
        wins = pnls > 0
        m.win_rate = round(float(wins.mean()), 4)
        gross_profit = float(pnls[wins].sum()) if wins.any() else 0.0
        gross_loss = float(-pnls[~wins].sum()) if (~wins).any() else 0.0
        m.profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else round(gross_profit, 4)
        m.expectancy_r = round(float(rs.mean()), 4)

        peak = self.initial_equity
        max_dd = 0.0
        eq = self.initial_equity
        for p in pnls:
            eq += float(p)
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)
        m.max_drawdown = round(max_dd, 4)

        streak_w = streak_l = max_w = max_l = 0
        for p in pnls:
            if p > 0:
                streak_w += 1
                streak_l = 0
            elif p < 0:
                streak_l += 1
                streak_w = 0
            max_w = max(max_w, streak_w)
            max_l = max(max_l, streak_l)
        m.max_consecutive_wins = max_w
        m.max_consecutive_losses = max_l
        return m
