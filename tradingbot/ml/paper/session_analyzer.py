"""Phase 11 — session-level paper trading analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from tradingbot.ml.paper.trade_lifecycle import PaperTrade


def analyze_sessions(trades: list[PaperTrade]) -> dict[str, Any]:
    """Group closed trades by UTC hour bucket."""
    buckets: dict[str, list[PaperTrade]] = defaultdict(list)
    for trade in trades:
        if trade.status != "CLOSED":
            continue
        try:
            hour = pd.Timestamp(trade.order.timestamp).floor("h").strftime("%H:00")
        except Exception:
            hour = "unknown"
        buckets[hour].append(trade)

    session_metrics = []
    for hour, group in sorted(buckets.items()):
        pnls = [t.pnl for t in group]
        wins = sum(1 for p in pnls if p > 0)
        session_metrics.append(
            {
                "session_hour_utc": hour,
                "trades": len(group),
                "win_rate": round(wins / len(group), 4) if group else 0.0,
                "total_pnl": round(sum(pnls), 4),
                "avg_r": round(sum(t.r_multiple for t in group) / len(group), 4) if group else 0.0,
            }
        )

    best = max(session_metrics, key=lambda x: x["total_pnl"], default=None)
    return {
        "sessions": session_metrics,
        "best_session": best,
        "sell_bias": _sell_bias(trades),
    }


def _sell_bias(trades: list[PaperTrade]) -> dict[str, Any]:
    sells = sum(1 for t in trades if t.order.direction == "SELL")
    buys = sum(1 for t in trades if t.order.direction == "BUY")
    total = buys + sells
    return {
        "buy": buys,
        "sell": sells,
        "sell_ratio": round(sells / total, 4) if total else 0.0,
        "has_sell_bias": sells > buys * 3 if buys else sells > 0,
    }


def compare_to_phase105(phase11_metrics: dict[str, Any], phase105: dict[str, Any] | None) -> dict[str, Any]:
    if not phase105:
        return {"available": False}
    p11 = phase11_metrics.get("trading", {})
    p10 = phase105.get("trading", {}) if "trading" in phase105 else phase105
    return {
        "available": True,
        "win_rate_delta": round(float(p11.get("win_rate", 0)) - float(p10.get("win_rate", 0)), 4),
        "pf_delta": round(float(p11.get("profit_factor", 0)) - float(p10.get("profit_factor", 0)), 4),
        "expectancy_delta": round(float(p11.get("expectancy_r", 0)) - float(p10.get("expectancy_r", 0)), 4),
        "drawdown_delta": round(float(p11.get("max_drawdown", 0)) - float(p10.get("max_drawdown", 0)), 4),
    }
