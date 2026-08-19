"""Phase 20C — broker spread analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def analyze_spread(data: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    orders = audit.get("orders") or []
    all_exec = data.get("all_executions") or []
    spreads = []
    for o in orders:
        if o.get("spread") is not None:
            spreads.append(float(o["spread"]))
    for e in all_exec:
        if e.get("spread") is not None:
            spreads.append(float(e["spread"]))

    if not spreads:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_spread_samples",
            "count": 0,
        }

    mean_s = float(np.mean(spreads))
    std_s = float(np.std(spreads)) if len(spreads) > 1 else 0.0
    spikes = sum(1 for s in spreads if s > mean_s + 2 * std_s and std_s > 0)

    return {
        "phase": "20C",
        "status": "COMPLETE",
        "count": len(spreads),
        "average_spread": round(mean_s, 6),
        "maximum_spread": round(float(np.max(spreads)), 6),
        "minimum_spread": round(float(np.min(spreads)), 6),
        "spread_spikes": spikes,
        "spike_rate": round(spikes / len(spreads), 4),
    }
