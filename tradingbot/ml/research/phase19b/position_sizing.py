"""Phase 19B — position sizing research (equity path simulation)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.metrics import max_drawdown_r, pf_from_r, expectancy_r


def _equity_path(r_vals: list[float], sizes: list[float], capital: float = 1000.0) -> dict[str, Any]:
    equity = capital
    peak = capital
    max_dd = 0.0
    pnls = []
    for r, s in zip(r_vals, sizes):
        risk_amt = equity * s
        pnl = risk_amt * r
        equity += pnl
        pnls.append(pnl / capital)  # normalize to starting capital units
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity - peak) / peak if peak else 0)
    # R-equivalent for PF: use sized R = r * (s / 0.005)
    sized_r = [r * (s / 0.005) for r, s in zip(r_vals, sizes)]
    return {
        "ending_equity": round(equity, 2),
        "total_return_pct": round((equity - capital) / capital * 100, 2),
        "maximum_drawdown_pct": round(max_dd * 100, 2),
        "profit_factor": pf_from_r(sized_r),
        "expectancy_r": expectancy_r(sized_r),
        "maximum_drawdown_r": max_drawdown_r(sized_r),
    }


def study_position_sizing(trades: list[dict[str, Any]]) -> dict[str, Any]:
    r_vals = [float(t["r_multiple"]) for t in trades]
    n = len(r_vals)
    if n == 0:
        return {"phase": "19B", "variants": []}

    conf = np.array([float(t.get("confidence", 0.5)) for t in trades])
    qual = np.array([float(t.get("quality_score", 0.5)) for t in trades])
    atr = np.array([max(float(t.get("atr", 1.0)), 1e-6) for t in trades])

    base = 0.005
    variants = {
        "fixed_fractional_0.5pct": [base] * n,
        "fixed_fractional_0.25pct": [0.0025] * n,
        "volatility_sizing": (base * (float(np.median(atr)) / atr)).clip(0.001, 0.01).tolist(),
        "confidence_weighted": (base * (0.5 + conf)).clip(0.001, 0.01).tolist(),
        "quality_weighted": (base * (0.5 + qual)).clip(0.001, 0.01).tolist(),
        "kelly_capped": [],
        "risk_parity": (base * (float(np.mean(atr)) / atr)).clip(0.001, 0.008).tolist(),
    }

    # Kelly fraction capped: f = edge/odds, edge~expectancy, odds~avg_win/avg_loss
    wins = [r for r in r_vals if r > 0]
    losses = [abs(r) for r in r_vals if r < 0]
    wr = len(wins) / n
    avg_w = float(np.mean(wins)) if wins else 1.0
    avg_l = float(np.mean(losses)) if losses else 1.0
    kelly = max(0.0, wr - (1 - wr) / max(avg_w / avg_l, 1e-9))
    kelly_f = min(0.01, max(0.001, kelly * 0.25))  # quarter-Kelly, capped 1%
    variants["kelly_capped"] = [kelly_f] * n

    baseline = _equity_path(r_vals, variants["fixed_fractional_0.5pct"])
    results = []
    for name, sizes in variants.items():
        perf = _equity_path(r_vals, sizes)
        results.append({
            "name": name,
            **perf,
            "pf_delta": round(perf["profit_factor"] - baseline["profit_factor"], 4),
            "exp_delta": round(perf["expectancy_r"] - baseline["expectancy_r"], 4),
            "dd_delta_pct": round(perf["maximum_drawdown_pct"] - baseline["maximum_drawdown_pct"], 4),
            "implementation_risk": "LOW" if "fixed" in name else "MED",
        })
    results.sort(key=lambda x: (-x["profit_factor"], x["maximum_drawdown_pct"]))

    return {
        "phase": "19B",
        "baseline_name": "fixed_fractional_0.5pct",
        "baseline": baseline,
        "variants": results,
        "kelly_raw": round(kelly, 4),
        "kelly_applied": round(kelly_f, 4),
    }
