"""Phase 11 — paper trading performance metrics."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.paper.trade_lifecycle import PaperTrade


def compute_performance(
    trades: list[PaperTrade],
    *,
    ml_buy: int = 0,
    ml_sell: int = 0,
    ml_hold: int = 0,
    risk_allowed: int = 0,
    risk_blocked: int = 0,
    risk_reasons: dict[str, int] | None = None,
    virtual_executions: int = 0,
    rejected_trades: int = 0,
    integrity_failures: int = 0,
    initial_balance: float = 10_000.0,
    equity_curve: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "CLOSED"]
    pnls = np.array([t.pnl for t in closed], dtype=np.float64) if closed else np.array([])
    rs = np.array([t.r_multiple for t in closed], dtype=np.float64) if closed else np.array([])
    wins = pnls > 0 if pnls.size else np.array([], dtype=bool)

    gross_profit = float(pnls[wins].sum()) if wins.any() else 0.0
    gross_loss = float(-pnls[~wins].sum()) if (~wins).any() and pnls.size else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    max_dd = 0.0
    if equity_curve:
        max_dd = max(float(p.get("drawdown", 0)) for p in equity_curve)
    elif closed:
        peak = initial_balance
        eq = initial_balance
        for p in pnls:
            eq += float(p)
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)

    streak_l = max_l = 0
    for p in pnls:
        if p < 0:
            streak_l += 1
            max_l = max(max_l, streak_l)
        else:
            streak_l = 0

    ml_total = ml_buy + ml_sell + ml_hold
    return {
        "ml": {
            "total_signals": ml_total,
            "ml_buy": ml_buy,
            "ml_sell": ml_sell,
            "ml_hold": ml_hold,
            "buy_sell_ratio": round(ml_buy / max(1, ml_buy + ml_sell), 4),
        },
        "trading": {
            "total_trades": len(closed),
            "win_rate": round(float(wins.mean()), 4) if wins.size else 0.0,
            "profit_factor": round(pf, 4),
            "expectancy_r": round(float(rs.mean()), 4) if rs.size else 0.0,
            "average_r": round(float(rs.mean()), 4) if rs.size else 0.0,
            "max_drawdown": round(max_dd, 4),
            "consecutive_losses": max_l,
            "avg_duration_bars": round(float(np.mean([t.bars_held for t in closed])), 2) if closed else 0.0,
        },
        "risk": {
            "allowed": risk_allowed,
            "blocked": risk_blocked,
            "block_reasons": dict(risk_reasons or {}),
        },
        "execution": {
            "virtual_executions": virtual_executions,
            "rejected_trades": rejected_trades,
            "integrity_failures": integrity_failures,
            "order_send": False,
        },
    }
