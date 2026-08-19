"""Phase 19B — exit optimization research (simulation on trade outcomes)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.metrics import compute_performance


def _perf_from_r(r_vals: list[float], template: list[dict]) -> dict[str, Any]:
    trades = []
    for t, r in zip(template, r_vals):
        trades.append({**t, "r_multiple": r, "allowed": True})
    return compute_performance(trades)


def study_exits(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Research-only exit variants applied to observed MFE/MAE/R.
    Does not change production exit logic.
    """
    baseline_r = [float(t["r_multiple"]) for t in trades]
    baseline = compute_performance(trades)

    variants: dict[str, list[float]] = {}

    # Trailing stop: capture 70% of MFE if MFE > 0.5 else current R
    variants["trailing_stop"] = [
        float(t["mfe"]) * 0.7 if float(t["mfe"]) >= 0.5 else float(t["r_multiple"])
        for t in trades
    ]

    # Break-even: if MFE >= 0.5 and loss, exit at 0 instead of -1
    variants["break_even"] = [
        0.0 if (float(t["mfe"]) >= 0.5 and float(t["r_multiple"]) < 0) else float(t["r_multiple"])
        for t in trades
    ]

    # Partial TP: 50% at 1R (assume hit if MFE>=1), rest at final R
    variants["partial_tp"] = [
        0.5 * 1.0 + 0.5 * float(t["r_multiple"]) if float(t["mfe"]) >= 1.0 else float(t["r_multiple"])
        for t in trades
    ]

    # ATR exit: cap loss at -0.8R when MAE large
    variants["atr_exit"] = [
        max(float(t["r_multiple"]), -0.8) if float(t["mae"]) >= 1.0 else float(t["r_multiple"])
        for t in trades
    ]

    # Time exit: if duration <= 1 and loss, slightly better (early exit -0.7)
    variants["time_exit"] = [
        -0.7 if (int(t.get("duration_bars", 0)) <= 1 and float(t["r_multiple"]) < 0) else float(t["r_multiple"])
        for t in trades
    ]

    # Dynamic TP: take 1.5R when MFE >= 1.5 else current
    variants["dynamic_tp"] = [
        1.5 if float(t["mfe"]) >= 1.5 else float(t["r_multiple"])
        for t in trades
    ]

    # Dynamic SL: tighten to -0.75 when confidence low
    variants["dynamic_sl"] = [
        max(float(t["r_multiple"]), -0.75) if float(t.get("confidence", 1)) < 0.45 else float(t["r_multiple"])
        for t in trades
    ]

    results = []
    for name, rs in variants.items():
        perf = _perf_from_r(rs, trades)
        results.append({
            "name": name,
            "profit_factor": perf["profit_factor"],
            "expectancy_r": perf["expectancy_r"],
            "maximum_drawdown_r": perf["maximum_drawdown_r"],
            "win_rate": perf["win_rate"],
            "net_profit_r": perf["net_profit_r"],
            "pf_delta": round(perf["profit_factor"] - baseline["profit_factor"], 4),
            "exp_delta": round(perf["expectancy_r"] - baseline["expectancy_r"], 4),
            "dd_delta": round(abs(perf["maximum_drawdown_r"]) - abs(baseline["maximum_drawdown_r"]), 4),
            "implementation_risk": "MED",
        })
    results.sort(key=lambda x: -(x["pf_delta"] + x["exp_delta"]))

    return {
        "phase": "19B",
        "baseline": {
            "profit_factor": baseline["profit_factor"],
            "expectancy_r": baseline["expectancy_r"],
            "maximum_drawdown_r": baseline["maximum_drawdown_r"],
        },
        "variants": results,
        "note": "Simulated on observed MFE/MAE — not production-ready without live validation",
    }
