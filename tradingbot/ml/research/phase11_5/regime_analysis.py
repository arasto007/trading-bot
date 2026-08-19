"""Phase 11.5 — regime proxy analysis from paper trade ATR."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase11_5._metrics import trade_metrics


def analyze_regimes(trades: list[dict[str, Any]]) -> dict[str, Any]:
    atrs = [float(t.get("atr", 0)) for t in trades if t.get("atr")]
    if not atrs:
        return {"regimes": [], "note": "No ATR data in trades"}

    p33, p66 = np.percentile(atrs, [33, 66])
    buckets: dict[str, list[dict[str, Any]]] = {
        "LOW_VOLATILITY": [],
        "RANGE": [],
        "HIGH_VOLATILITY": [],
    }

    for trade in trades:
        atr = float(trade.get("atr", 0))
        if atr <= p33:
            buckets["LOW_VOLATILITY"].append(trade)
        elif atr <= p66:
            buckets["RANGE"].append(trade)
        else:
            buckets["HIGH_VOLATILITY"].append(trade)

    rows = []
    for name, group in buckets.items():
        m = trade_metrics(group)
        sell_pct = sum(1 for t in group if t.get("direction") == "SELL") / max(1, len(group))
        rows.append({"regime": name, "sell_pct": round(sell_pct, 4), **m})

    profitable = [r for r in rows if r.get("profit_factor", 0) >= 1.0 and r.get("trades", 0) >= 5]
    return {
        "atr_percentiles": {"p33": round(float(p33), 4), "p66": round(float(p66), 4)},
        "regimes": rows,
        "profitable_regimes": [r["regime"] for r in profitable],
        "recommendation": profitable[0]["regime"] if profitable else "NONE_CLEAR",
    }
