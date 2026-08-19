"""Phase 11.5 — shared metrics helpers for research analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def trade_metrics(trades: list[dict[str, Any]], *, initial_equity: float = 10_000.0) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "max_drawdown": 0.0,
            "total_pnl": 0.0,
        }
    pnls = np.array([float(t.get("pnl", 0)) for t in trades], dtype=np.float64)
    rs = np.array([float(t.get("R_multiple", 0)) for t in trades], dtype=np.float64)
    wins = pnls > 0
    gross_profit = float(pnls[wins].sum()) if wins.any() else 0.0
    gross_loss = float(-pnls[~wins].sum()) if (~wins).any() else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    eq = initial_equity
    peak = initial_equity
    max_dd = 0.0
    for p in pnls:
        eq += float(p)
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)

    return {
        "trades": len(trades),
        "win_rate": round(float(wins.mean()), 4),
        "profit_factor": round(pf, 4),
        "expectancy_r": round(float(rs.mean()), 4),
        "max_drawdown": round(max_dd, 4),
        "total_pnl": round(float(pnls.sum()), 4),
    }


def scale_trades_risk(trades: list[dict[str, Any]], risk_pct: float, initial_equity: float = 10_000.0) -> list[dict[str, Any]]:
    """Resimulate PnL at different risk% using stored R-multiples."""
    equity = initial_equity
    scaled: list[dict[str, Any]] = []
    for t in trades:
        r_mult = float(t.get("R_multiple", 0))
        risk_amount = equity * risk_pct
        pnl = r_mult * risk_amount
        scaled.append({**t, "pnl": round(pnl, 4), "risk_percent": risk_pct})
        equity += pnl
    return scaled
