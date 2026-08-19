"""Phase 11.5 — session window optimization from paper trades."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase11_5._metrics import trade_metrics

SESSION_WINDOWS = {
    "asia": (0, 8),
    "london": (7, 16),
    "new_york": (13, 21),
    "overlap": (13, 16),
}


def _session_for_hour(hour: int) -> list[str]:
    names: list[str] = []
    for name, (start, end) in SESSION_WINDOWS.items():
        if start <= hour < end:
            names.append(name)
    return names or ["off_hours"]


def optimize_sessions(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in SESSION_WINDOWS}
    buckets["off_hours"] = []

    for trade in trades:
        try:
            hour = pd.Timestamp(trade["timestamp"]).hour
        except Exception:
            continue
        matched = False
        for name in _session_for_hour(hour):
            buckets[name].append(trade)
            matched = True
        if not matched:
            buckets["off_hours"].append(trade)

    session_rows = []
    for name, group in buckets.items():
        m = trade_metrics(group)
        session_rows.append({"session": name, **m})

    best_pf = max(session_rows, key=lambda x: x.get("profit_factor", 0), default={})
    best_exp = max(session_rows, key=lambda x: x.get("expectancy_r", -999), default={})
    lowest_dd = min(session_rows, key=lambda x: x.get("max_drawdown", 1), default={})

    return {
        "sessions": session_rows,
        "best_pf_session": best_pf,
        "best_expectancy_session": best_exp,
        "lowest_drawdown_session": lowest_dd,
        "recommended_windows": [
            s["session"]
            for s in session_rows
            if s.get("profit_factor", 0) >= 1.0 and s.get("trades", 0) >= 5
        ],
    }
