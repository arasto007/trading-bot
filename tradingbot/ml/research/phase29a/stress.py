"""Stress validation for filtered strategy."""

from __future__ import annotations

import random
from typing import Any

from tradingbot.ml.research.phase29a.analysis import _trades_to_perf


def stress_test_filtered(
    trades: list[dict[str, Any]],
    scores: list[float],
    threshold: float,
    *,
    initial: float = 200.0,
    seed: int = 42,
) -> dict[str, Any]:
    rng = random.Random(seed)
    kept = [t for t, s in zip(trades, scores) if s >= threshold]
    baseline_perf = _trades_to_perf(kept, initial=initial)

    scenarios: dict[str, Any] = {}

    # Spread +50%
    spread_stressed = []
    for t in kept:
        t2 = dict(t)
        extra_cost = float(t.get("spread", 0.3)) * 0.5 * float(t.get("lot", 0.01)) * 100
        t2["pnl"] = float(t["pnl"]) - extra_cost
        spread_stressed.append(t2)
    scenarios["spread_plus_50pct"] = _trades_to_perf(spread_stressed, initial=initial)

    # Slippage 0.10 ATR
    slip_stressed = []
    for t in kept:
        t2 = dict(t)
        atr = float(t.get("atr") or 1.0)
        slip_cost = 0.10 * atr * float(t.get("lot", 0.01)) * 100
        t2["pnl"] = float(t["pnl"]) - slip_cost
        slip_stressed.append(t2)
    scenarios["slippage_0_10_atr"] = _trades_to_perf(slip_stressed, initial=initial)

    # Missed trades 20%
    missed = [t for t in kept if rng.random() > 0.20]
    scenarios["missed_trades_20pct"] = _trades_to_perf(missed, initial=initial)

    # Combined stress
    combined = []
    for t in kept:
        if rng.random() < 0.20:
            continue
        t2 = dict(t)
        atr = float(t.get("atr") or 1.0)
        cost = float(t.get("spread", 0.3)) * 0.5 * float(t.get("lot", 0.01)) * 100
        cost += 0.10 * atr * float(t.get("lot", 0.01)) * 100
        t2["pnl"] = float(t["pnl"]) - cost
        combined.append(t2)
    scenarios["combined_stress"] = _trades_to_perf(combined, initial=initial)

    unfiltered = _trades_to_perf(trades, initial=initial)
    base_pf = float(unfiltered.get("profit_factor", 1)) if isinstance(unfiltered.get("profit_factor"), (int, float)) else 1.0

    improvements = {}
    for name, perf in scenarios.items():
        pf = perf.get("profit_factor")
        pf_val = float(pf) if isinstance(pf, (int, float)) else 0
        improvements[name] = {
            "profit_factor": pf_val,
            "beats_unfiltered": pf_val > base_pf,
            "beats_baseline_filtered": pf_val >= float(baseline_perf.get("profit_factor", 0)) * 0.95,
        }

    return {
        "phase": "29A",
        "filtered_baseline": baseline_perf,
        "unfiltered_baseline": unfiltered,
        "threshold": threshold,
        "scenarios": scenarios,
        "improvements": improvements,
        "filter_survives_stress": all(v["beats_unfiltered"] for v in improvements.values()),
    }
