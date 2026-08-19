"""Phase 22F — missed profitable opportunities (blocked but model-correct)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import simulate_trade_outcome


def analyze_missed_opportunities(
    blocked_events: list[dict],
    ohlcv: pd.DataFrame | None,
    *,
    timeframe: str = "M5",
    top_n: int = 100,
) -> dict[str, Any]:
    if ohlcv is None or ohlcv.empty:
        return {"phase": "22F", "missed_count": 0, "top_missed": [], "by_blocker": {}}

    ohlcv = ohlcv.copy()
    ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)
    missed: list[dict] = []
    by_blocker: dict[str, dict] = {}

    for ev in blocked_events:
        direction = ev.get("direction", "")
        if direction not in ("BUY", "SELL"):
            continue
        ts = pd.Timestamp(ev.get("timestamp", ""))
        if ts is pd.NaT:
            continue
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        idx = ohlcv.index.searchsorted(ts)
        if idx >= len(ohlcv) - 5:
            continue
        outcome = simulate_trade_outcome(ohlcv, idx, direction=direction)
        expected_r = float(outcome.get("r_multiple", 0))
        if expected_r <= 0:
            continue
        stage = ev.get("stage", "unknown")
        blocker = by_blocker.setdefault(stage, {"count": 0, "sum_expected_r": 0.0, "correct_blocks": 0})
        blocker["count"] += 1
        blocker["sum_expected_r"] += expected_r
        blocking_correct = expected_r < 0.5
        if blocking_correct:
            blocker["correct_blocks"] += 1
        missed.append({
            **ev,
            "expected_r_if_executed": round(expected_r, 4),
            "mfe": round(float(outcome.get("mfe", 0)), 4),
            "mae": round(float(outcome.get("mae", 0)), 4),
            "blocking_correct": not blocking_correct,
            "blocker_module": stage,
        })

    missed.sort(key=lambda x: x["expected_r_if_executed"], reverse=True)
    top = missed[:top_n]

    return {
        "phase": "22F",
        "timeframe": timeframe,
        "missed_profitable_count": len(missed),
        "top_missed": top,
        "by_blocker": by_blocker,
        "note": "Forward R from research simulator — hindsight evaluation only",
    }
