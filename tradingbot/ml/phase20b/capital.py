"""Phase 20B — capital progression model (config-level simulation only)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase20b.config import CAPITAL_RISK_LEVELS


def simulate_capital_progression(observation: dict[str, Any]) -> dict[str, Any]:
    trades = observation.get("trades") or []
    r_vals = []
    for t in trades:
        if "r_multiple" in t:
            r_vals.append(float(t["r_multiple"]))
        elif "pnl_r" in t:
            r_vals.append(float(t["pnl_r"]))

    levels: dict[str, Any] = {}
    for risk in CAPITAL_RISK_LEVELS:
        equity = 1000.0
        peak = equity
        max_dd = 0.0
        ruin = False
        path = [equity]
        for r in r_vals:
            pnl = equity * risk * r
            equity += pnl
            path.append(equity)
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            if equity <= 500.0:
                ruin = True

        # Smoothness: inverse of path volatility of returns
        rets = np.diff(path) / np.asarray(path[:-1]) if len(path) > 1 else np.array([0.0])
        smoothness = 1.0 / (1.0 + float(np.std(rets))) if len(rets) else 0.0

        levels[f"{int(risk * 100)}pct"] = {
            "risk_pct": risk,
            "starting_capital": 1000.0,
            "ending_capital": round(equity, 2),
            "total_return_pct": round((equity - 1000.0) / 10.0, 2),
            "maximum_drawdown_pct": round(max_dd * 100, 2),
            "risk_of_ruin": ruin,
            "equity_smoothness": round(smoothness, 4),
            "growth_stable": (not ruin) and max_dd < 0.35 and equity >= 1000.0,
        }

    stable_levels = [k for k, v in levels.items() if v["growth_stable"]]
    return {
        "phase": "20B",
        "trades": len(r_vals),
        "levels": levels,
        "stable_levels": stable_levels,
        "recommended_risk_pct": 0.02 if "2pct" in stable_levels else (0.01 if "1pct" in stable_levels else None),
        "passed": "1pct" in stable_levels or "2pct" in stable_levels,
    }
