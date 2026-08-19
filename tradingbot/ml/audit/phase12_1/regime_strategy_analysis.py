"""Phase 12.1 — per-regime strategy performance from paper trades."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.ml.data.paths import paper_trading_trades_path
from tradingbot.ml.research.phase11_5._metrics import trade_metrics


def analyze_regime_strategy(
    *,
    paper_run_id: str = "phase11_v1",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    path = paper_trading_trades_path(paper_run_id, base_dir)
    if not path.is_file():
        return {"note": "no trades data", "regimes": []}

    trades = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(trades, list):
        return {"note": "invalid trades", "regimes": []}

    atrs = [float(t.get("atr", 0)) for t in trades if t.get("atr")]
    if not atrs:
        return {"note": "no ATR in trades", "regimes": []}

    p33, p66 = np.percentile(atrs, [33, 66])
    buckets: dict[str, list[dict]] = {
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
    for regime, group in buckets.items():
        m = trade_metrics(group)
        rows.append(
            {
                "regime": regime,
                "strategy": "Phase9.9_ML",
                "trades": m["trades"],
                "profit_factor": m["profit_factor"],
                "win_rate": m["win_rate"],
                "expectancy_r": m["expectancy_r"],
            }
        )
        rows.append(
            {
                "regime": regime,
                "strategy": "priceaction_legacy",
                "trades": 0,
                "profit_factor": None,
                "note": "No legacy-only trades in paper run — ML priority path",
            }
        )

    best = max(
        [r for r in rows if r.get("profit_factor") is not None and r.get("trades", 0) > 0],
        key=lambda x: float(x.get("profit_factor", 0)),
        default={},
    )
    worst = min(
        [r for r in rows if r.get("profit_factor") is not None and r.get("trades", 0) > 0],
        key=lambda x: float(x.get("profit_factor", 999)),
        default={},
    )

    return {
        "atr_percentiles": {"p33": round(float(p33), 4), "p66": round(float(p66), 4)},
        "by_regime": rows,
        "best_performing": best,
        "worst_performing": worst,
    }
