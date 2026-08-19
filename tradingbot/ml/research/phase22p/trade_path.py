"""Phase 22P — executed trade path and counterfactual analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import simulate_trade_outcome


def analyze_trade_paths(
    trades_detail: list[dict],
    ohlcv: pd.DataFrame | None,
) -> dict[str, Any]:
    """For each executed trade: actual PnL and whether signal was forward-profitable."""
    rows: list[dict] = []
    if not trades_detail:
        return {"phase": "22P", "trades": [], "summary": {"count": 0}}

    ohlcv_ready = ohlcv is not None and not ohlcv.empty
    if ohlcv_ready:
        ohlcv = ohlcv.copy()
        ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)

    profitable = 0
    would_be_profitable_no_filter = 0

    for t in trades_detail:
        pnl = float(t.get("pnl") or 0)
        side = t.get("side", "BUY")
        entry_time = t.get("entry_time")
        actual_profitable = pnl > 0
        if actual_profitable:
            profitable += 1

        forward_r = None
        no_filter_profitable = None
        if ohlcv_ready and entry_time:
            ts = pd.Timestamp(entry_time)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            idx = ohlcv.index.searchsorted(ts)
            if idx < len(ohlcv) - 5:
                outcome = simulate_trade_outcome(ohlcv, idx, direction=side)
                forward_r = round(float(outcome.get("r_multiple", 0)), 4)
                no_filter_profitable = forward_r > 0
                if no_filter_profitable:
                    would_be_profitable_no_filter += 1

        rows.append({
            "side": side,
            "entry_time": entry_time,
            "exit_time": t.get("exit_time"),
            "pnl": pnl,
            "r_multiple": t.get("r_multiple"),
            "strategy": t.get("strategy"),
            "actual_profitable": actual_profitable,
            "forward_r_at_entry": forward_r,
            "profitable_without_filter_hypothesis": no_filter_profitable,
            "interpretation": (
                "Trade passed all filters; actual PnL is realized outcome. "
                "forward_r_at_entry is research simulator at entry bar."
            ),
        })

    n = len(rows)
    return {
        "phase": "22P",
        "trades": rows,
        "summary": {
            "count": n,
            "actual_profitable": profitable,
            "actual_losses": n - profitable,
            "win_rate_pct": round(profitable / max(n, 1) * 100, 2),
            "would_be_forward_profitable_at_entry": would_be_profitable_no_filter,
            "note": (
                "Executed trades already passed ML + RiskGate filters. "
                "Counterfactual 'no filter' uses same entry bar forward-R simulator."
            ),
        },
    }
