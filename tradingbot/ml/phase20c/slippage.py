"""Phase 20C — slippage analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def analyze_slippage(data: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    orders = audit.get("orders") or []
    slips = []
    for o in orders:
        if o.get("slippage") is not None:
            slips.append(float(o["slippage"]))

    if not slips:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_slippage_samples",
            "count": 0,
        }

    return {
        "phase": "20C",
        "status": "COMPLETE",
        "count": len(slips),
        "average_slippage": round(float(np.mean(slips)), 6),
        "median_slippage": round(float(np.median(slips)), 6),
        "worst_slippage": round(float(np.max(slips)), 6),
        "p95_slippage": round(float(np.percentile(slips, 95)), 6),
        "std_slippage": round(float(np.std(slips)), 6),
    }
