"""Paper trading performance metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from tradingbot.ml.paper.portfolio import Portfolio


@dataclass
class PaperMetrics:
    total_return_r: float
    win_rate: float
    profit_factor: float
    max_drawdown_r: float
    sharpe_like: float
    expectancy_r: float
    trade_frequency: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_metrics(portfolio: Portfolio) -> PaperMetrics:
    r_vals = portfolio.r_multiples()
    if not r_vals:
        return PaperMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    arr = np.asarray(r_vals, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    std = float(arr.std()) if len(arr) > 1 else 1.0
    sharpe = float(arr.mean() / std) if std > 1e-9 else 0.0

    return PaperMetrics(
        total_return_r=portfolio.total_return_r,
        win_rate=round(float((arr > 0).mean()), 4),
        profit_factor=round(float(pf), 4),
        max_drawdown_r=round(portfolio.max_drawdown_r, 4),
        sharpe_like=round(sharpe, 4),
        expectancy_r=round(float(arr.mean()), 4),
        trade_frequency=len(r_vals),
    )


def session_breakdown(portfolio: Portfolio) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[float]] = {}
    for trade in portfolio.closed_trades:
        buckets.setdefault(trade.session or "unknown", []).append(trade.r_multiple)
    out: dict[str, dict[str, float]] = {}
    for session, rs in buckets.items():
        arr = np.asarray(rs, dtype=float)
        out[session] = {
            "trades": float(len(arr)),
            "expected_R": round(float(arr.mean()), 4) if len(arr) else 0.0,
            "win_rate": round(float((arr > 0).mean()), 4) if len(arr) else 0.0,
        }
    return out


def slippage_impact(portfolio: Portfolio) -> dict[str, float]:
    if not portfolio.closed_trades:
        return {"total_slippage": 0.0, "total_spread_cost": 0.0, "avg_slippage": 0.0}
    slips = [t.slippage for t in portfolio.closed_trades]
    spreads = [t.spread_cost for t in portfolio.closed_trades]
    return {
        "total_slippage": round(float(sum(slips)), 6),
        "total_spread_cost": round(float(sum(spreads)), 6),
        "avg_slippage": round(float(np.mean(slips)), 6) if slips else 0.0,
    }
