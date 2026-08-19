"""Phase 20B — drawdown behavior analysis."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.metrics import max_drawdown_r


def analyze_drawdown(observation: dict[str, Any]) -> dict[str, Any]:
    trades = observation.get("trades") or []
    r_vals = []
    for t in trades:
        if "r_multiple" in t:
            r_vals.append(float(t["r_multiple"]))
        elif "pnl_r" in t:
            r_vals.append(float(t["pnl_r"]))

    live_dd = observation.get("drawdown") or []
    risk_events = observation.get("risk_events") or []

    if not r_vals and not live_dd:
        return {
            "phase": "20B",
            "passed": False,
            "note": "no_drawdown_samples",
            "maximum_drawdown_r": 0.0,
        }

    equity = np.cumsum(r_vals) if r_vals else np.array([0.0])
    peak = np.maximum.accumulate(equity)
    dd_series = equity - peak
    max_dd = float(np.min(dd_series)) if len(dd_series) else 0.0

    # Clustering: consecutive negative equity steps
    clusters = []
    in_dd = False
    start = 0
    for i, d in enumerate(dd_series):
        if d < -0.5 and not in_dd:
            in_dd = True
            start = i
        elif d >= -0.1 and in_dd:
            in_dd = False
            clusters.append({"start": start, "end": i, "depth_r": float(np.min(dd_series[start:i + 1]))})
    if in_dd:
        clusters.append({"start": start, "end": len(dd_series) - 1, "depth_r": float(np.min(dd_series[start:]))})

    # Recovery times (bars from trough to new peak)
    recoveries = []
    for c in clusters:
        end = c["end"]
        trough_eq = equity[end]
        rec = None
        for j in range(end + 1, len(equity)):
            if equity[j] >= peak[end]:
                rec = j - end
                break
        recoveries.append(rec)

    # Worst streak windows
    max_loss_streak = 0
    cur = 0
    for r in r_vals:
        if r < 0:
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0

    riskgate_blocks = [
        e for e in risk_events
        if not e.get("allowed", True) or "risk" in str(e.get("reason", "")).lower()
    ]

    live_dd_pct = [float(d.get("drawdown_pct", 0)) for d in live_dd]
    max_live_dd_pct = min(live_dd_pct) if live_dd_pct else None

    return {
        "phase": "20B",
        "maximum_drawdown_r": round(max_dd, 4),
        "max_live_drawdown_pct": max_live_dd_pct,
        "drawdown_clusters": clusters[:20],
        "cluster_count": len(clusters),
        "recovery_bars": [r for r in recoveries if r is not None],
        "mean_recovery_bars": round(float(np.mean([r for r in recoveries if r is not None])), 2)
        if any(r is not None for r in recoveries) else None,
        "worst_loss_streak": max_loss_streak,
        "riskgate_activations": len(riskgate_blocks),
        "riskgate_patterns": [
            {"reason": e.get("reason"), "timestamp": e.get("timestamp")}
            for e in riskgate_blocks[:20]
        ],
        "passed": abs(max_dd) <= 20.0 and max_loss_streak <= 10,
    }
