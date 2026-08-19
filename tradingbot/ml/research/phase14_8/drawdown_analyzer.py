"""Phase 14.8 — drawdown analysis."""

from __future__ import annotations

from typing import Any


def analyze_drawdown(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in records if r.get("allowed")]
    r_vals = [float(r["r_multiple"]) for r in accepted]
    if not r_vals:
        return {
            "max_drawdown": 0.0,
            "max_drawdown_r": 0.0,
            "recovery_bars": 0,
            "underwater_pct": 0.0,
            "equity_curve_points": 0,
        }

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    underwater = 0
    for r in r_vals:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if equity < peak:
            underwater += 1

    return {
        "max_drawdown": round(max_dd, 4),
        "max_drawdown_r": round(max_dd, 4),
        "underwater_pct": round(underwater / len(r_vals), 4),
        "equity_curve_points": len(r_vals),
        "final_equity_r": round(equity, 4),
    }
