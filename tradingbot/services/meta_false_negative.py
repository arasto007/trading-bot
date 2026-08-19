"""Phase 21D — Meta false-negative outcome join (telemetry / research only)."""
from __future__ import annotations

from typing import Any

FORWARD_BARS = 24


def classify_24_bar_outcome(
    high,
    low,
    i: int,
    direction: int,
    entry: float,
    sl: float,
    n: int,
    n_bars: int = FORWARD_BARS,
) -> dict[str, Any]:
    """Classify the next n_bars after bar i.

    Same-bar SL + MFE is treated as SL first (does not inflate FN rate).
    """
    risk = abs(float(entry) - float(sl))
    empty = {
        "mfe_r": 0.0,
        "sl_hit": False,
        "reached_1r": False,
        "reached_15r": False,
        "outcome": "timeout",
        "bars_used": 0,
    }
    if risk <= 0 or i < 0:
        return empty
    mfe = 0.0
    sl_hit = False
    bars_used = 0
    end = min(int(n), int(i) + 1 + int(n_bars))
    buy = int(direction) > 0
    for j in range(int(i) + 1, end):
        bars_used += 1
        prev = mfe
        hi = float(high[j])
        lo = float(low[j])
        if buy:
            mfe = max(mfe, (hi - float(entry)) / risk)
            hit_sl = lo <= float(sl)
        else:
            mfe = max(mfe, (float(entry) - lo) / risk)
            hit_sl = hi >= float(sl)
        if hit_sl:
            sl_hit = True
            mfe = prev
            break
    reached_1r = mfe >= 1.0
    reached_15r = mfe >= 1.5
    if reached_15r:
        outcome = "plus_1_5r"
    elif reached_1r:
        outcome = "plus_1r"
    elif sl_hit:
        outcome = "sl_first"
    else:
        outcome = "timeout"
    return {
        "mfe_r": round(float(mfe), 4),
        "sl_hit": sl_hit,
        "reached_1r": reached_1r,
        "reached_15r": reached_15r,
        "outcome": outcome,
        "bars_used": bars_used,
    }


def summarize_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    became_1 = sum(1 for r in rows if r.get("reached_1r"))
    became_15 = sum(1 for r in rows if r.get("reached_15r"))
    sl_first = sum(1 for r in rows if r.get("outcome") == "sl_first")
    timeout = sum(1 for r in rows if r.get("outcome") == "timeout")
    recoverable = 0.0
    for r in rows:
        if not r.get("reached_1r"):
            continue
        mfe = float(r.get("mfe_r") or 0.0)
        recoverable += 1.5 if mfe >= 1.5 else 1.0
    rate = (became_1 / n) if n else 0.0
    return {
        "candidates": n,
        "became_1r": became_1,
        "became_15r": became_15,
        "sl_first": sl_first,
        "timeout": timeout,
        "false_negative_rate": round(rate, 4),
        "potential_recoverable_r": round(recoverable, 3),
    }