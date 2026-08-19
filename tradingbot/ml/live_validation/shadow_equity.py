"""Phase 15D — virtual equity curve from shadow trades."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.live_validation.shadow_trade import ShadowTrade


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


@dataclass
class ShadowEquityTracker:
    initial_equity: float = 10_000.0
    risk_per_trade: float = 100.0
    equity_curve: list[float] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    daily_pnl: dict[str, float] = field(default_factory=dict)
    weekly_pnl: dict[str, float] = field(default_factory=dict)
    monthly_pnl: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.equity_curve:
            self.equity_curve.append(self.initial_equity)

    def apply_trade(self, trade: ShadowTrade) -> float:
        pnl = float(trade.pnl)
        if pnl == 0.0 and trade.entry and trade.exit and trade.sl:
            risk_dist = abs(trade.entry - trade.sl)
            if risk_dist > 0:
                move = (trade.exit - trade.entry) if trade.signal == "BUY" else (trade.entry - trade.exit)
                r_mult = move / risk_dist
                pnl = r_mult * self.risk_per_trade
                trade.pnl = pnl

        new_eq = self.equity_curve[-1] + pnl
        self.equity_curve.append(new_eq)
        self.timestamps.append(trade.time)

        day = trade.time[:10] if len(trade.time) >= 10 else trade.time
        week = day[:7] + "-W" + str(int(day[8:10]) // 7 + 1) if len(day) >= 10 else day
        month = day[:7] if len(day) >= 7 else day
        self.daily_pnl[day] = self.daily_pnl.get(day, 0.0) + pnl
        self.weekly_pnl[week] = self.weekly_pnl.get(week, 0.0) + pnl
        self.monthly_pnl[month] = self.monthly_pnl.get(month, 0.0) + pnl
        return pnl

    def max_drawdown(self) -> float:
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak else 0.0
            max_dd = max(max_dd, dd)
        return max_dd

    def returns(self) -> list[float]:
        out: list[float] = []
        for i in range(1, len(self.equity_curve)):
            prev = self.equity_curve[i - 1]
            out.append((self.equity_curve[i] - prev) / prev if prev else 0.0)
        return out

    def sharpe(self, annual_factor: float = math.sqrt(252)) -> float:
        rets = self.returns()
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        return (mean / std * annual_factor) if std else 0.0

    def sortino(self, annual_factor: float = math.sqrt(252)) -> float:
        rets = self.returns()
        if not rets:
            return 0.0
        mean = sum(rets) / len(rets)
        downside = [min(0.0, r) for r in rets]
        var = sum(d ** 2 for d in downside) / len(downside) if downside else 0.0
        std = math.sqrt(var) if var > 0 else 0.0
        return (mean / std * annual_factor) if std else 0.0

    def ulcer_index(self) -> float:
        peak = self.equity_curve[0]
        sq: list[float] = []
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd_pct = ((peak - eq) / peak * 100.0) if peak else 0.0
            sq.append(dd_pct ** 2)
        return math.sqrt(sum(sq) / len(sq)) if sq else 0.0

    def build_report(self, trades: list[ShadowTrade]) -> dict[str, Any]:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        n = len(trades)
        return {
            "initial_equity": self.initial_equity,
            "final_equity": round(self.equity_curve[-1], 2),
            "total_pnl": round(self.equity_curve[-1] - self.initial_equity, 2),
            "trade_count": n,
            "daily_pnl": {k: round(v, 2) for k, v in sorted(self.daily_pnl.items())},
            "weekly_pnl": {k: round(v, 2) for k, v in sorted(self.weekly_pnl.items())},
            "monthly_pnl": {k: round(v, 2) for k, v in sorted(self.monthly_pnl.items())},
            "max_drawdown": round(self.max_drawdown(), 4),
            "profit_factor": round(_safe_div(gross_profit, gross_loss), 4),
            "expectancy": round(_safe_div(sum(t.pnl for t in trades), n), 4),
            "win_rate": round(_safe_div(len(wins), n), 4),
            "sharpe": round(self.sharpe(), 4),
            "sortino": round(self.sortino(), 4),
            "ulcer_index": round(self.ulcer_index(), 4),
            "equity_curve": [round(e, 2) for e in self.equity_curve],
        }
