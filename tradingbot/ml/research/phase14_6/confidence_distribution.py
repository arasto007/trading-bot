"""Phase 14.6 — confidence distribution statistics."""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np


def distribution_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p10": 0.0,
            "p25": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "spread_p90_p10": 0.0,
        }
    arr = np.array(values, dtype=float)
    p10, p25, p50, p75, p90 = np.percentile(arr, [10, 25, 50, 75, 90])
    std = float(np.std(arr))
    return {
        "count": len(values),
        "mean": round(float(np.mean(arr)), 4),
        "std": round(std, 4),
        "min": round(float(np.min(arr)), 4),
        "max": round(float(np.max(arr)), 4),
        "p10": round(float(p10), 4),
        "p25": round(float(p25), 4),
        "p50": round(float(p50), 4),
        "p75": round(float(p75), 4),
        "p90": round(float(p90), 4),
        "spread_p90_p10": round(float(p90 - p10), 4),
    }


def histogram(values: list[float], *, bins: int = 10) -> dict[str, Any]:
    if not values:
        return {"bins": [], "counts": []}
    counts, edges = np.histogram(np.array(values, dtype=float), bins=bins, range=(0.0, 1.0))
    return {
        "bins": [round(float(edges[i]), 2) for i in range(len(edges) - 1)],
        "counts": [int(c) for c in counts],
    }


def compression_detected(calibrated: dict[str, Any], *, max_p90: float = 0.20, max_std: float = 0.08) -> bool:
    return calibrated.get("p90", 1.0) <= max_p90 and calibrated.get("std", 1.0) <= max_std


def compression_resolved(calibrated: dict[str, Any], *, min_spread: float, min_std: float) -> bool:
    return calibrated.get("spread_p90_p10", 0.0) >= min_spread or calibrated.get("std", 0.0) >= min_std
