"""Phase 19A — capital level simulation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.config import CAPITAL_LEVELS
from tradingbot.ml.phase19a.metrics import max_drawdown_r


def analyze_capital(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    levels: dict[str, Any] = {}

    for capital in CAPITAL_LEVELS:
        equity = float(capital)
        peak = equity
        max_dd_pct = 0.0
        monthly: dict[str, float] = {}
        ruin = False

        for t in accepted:
            risk_pct = float(t.get("risk_percent", 0.005))
            risk_amt = equity * risk_pct
            pnl = risk_amt * float(t["r_multiple"])
            equity += pnl
            if equity <= capital * 0.5:
                ruin = True
            peak = max(peak, equity)
            dd = (equity - peak) / peak if peak > 0 else 0.0
            max_dd_pct = min(max_dd_pct, dd)
            key = f"{t['year']}-{t['month']:02d}"
            monthly[key] = monthly.get(key, 0.0) + pnl

        months_n = max(len(monthly), 1)
        years_n = max(len({k[:4] for k in monthly}), 1)
        total_return = (equity - capital) / capital
        monthly_returns = [v / capital for v in monthly.values()]
        avg_monthly = float(np.mean(monthly_returns)) if monthly_returns else 0.0

        levels[str(capital)] = {
            "starting_capital": capital,
            "ending_capital": round(equity, 2),
            "total_return_pct": round(total_return * 100, 2),
            "monthly_return_avg_pct": round(avg_monthly * 100, 2),
            "annual_return_pct": round((total_return / years_n) * 100, 2),
            "maximum_drawdown_pct": round(max_dd_pct * 100, 2),
            "risk_of_ruin": ruin,
            "trades": len(accepted),
        }

    return {
        "phase": "19A",
        "levels": levels,
        "capital_levels": list(CAPITAL_LEVELS),
    }
