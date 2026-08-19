"""Phase 13.5 — per-regime and combined performance metrics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase11_5._metrics import trade_metrics


def compute_regime_performance(trades: list[dict[str, Any]], *, initial_equity: float = 10_000.0) -> dict[str, Any]:
    range_trades = [t for t in trades if t.get("regime") == "RANGE"]
    trend_trades = [t for t in trades if t.get("regime") == "TREND"]
    high_vol_blocks = sum(1 for t in trades if t.get("type") == "block" and t.get("regime") == "HIGH_VOLATILITY")
    no_trade_blocks = sum(1 for t in trades if t.get("type") == "block" and t.get("regime") == "NO_TRADE")

    return {
        "combined": _combined_metrics(trades, initial_equity=initial_equity),
        "RANGE": _regime_slice(range_trades, initial_equity=initial_equity),
        "TREND": _regime_slice(trend_trades, initial_equity=initial_equity),
        "HIGH_VOLATILITY": {"blocked_count": high_vol_blocks},
        "NO_TRADE": {"blocked_count": no_trade_blocks},
    }


def _regime_slice(trades: list[dict[str, Any]], *, initial_equity: float) -> dict[str, Any]:
    m = trade_metrics(trades, initial_equity=initial_equity)
    return {
        "trades": m["trades"],
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy_r"],
        "win_rate": m["win_rate"],
    }


def _combined_metrics(trades: list[dict[str, Any]], *, initial_equity: float) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") != "block"]
    m = trade_metrics(executed, initial_equity=initial_equity)
    days = _trading_days(executed)
    trades_per_day = round(m["trades"] / days, 4) if days > 0 else 0.0
    return {
        "trades": m["trades"],
        "win_rate": m["win_rate"],
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy_r"],
        "max_drawdown": m["max_drawdown"],
        "trades_per_day": trades_per_day,
        "total_pnl": m["total_pnl"],
    }


def _trading_days(trades: list[dict[str, Any]]) -> int:
    if not trades:
        return 0
    days = {pd.Timestamp(t["timestamp"]).date() for t in trades if "timestamp" in t}
    return max(len(days), 1)


def strategy_contribution(trades: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") != "block"]
    by_engine: dict[str, list[dict[str, Any]]] = {}
    for t in executed:
        by_engine.setdefault(str(t.get("source_engine", "unknown")), []).append(t)
    return {
        engine: {
            "trades": len(rows),
            "share": round(len(rows) / len(executed), 4) if executed else 0.0,
            "profit_factor": trade_metrics(rows)["profit_factor"],
        }
        for engine, rows in sorted(by_engine.items())
    }
