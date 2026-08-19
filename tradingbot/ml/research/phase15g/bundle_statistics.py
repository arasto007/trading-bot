"""Phase 15G — distribution and histogram helpers."""

from __future__ import annotations

import statistics
from typing import Any

from tradingbot.ml.monitoring.statistics import percentile


def distribution_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p10": 0.0,
            "p25": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "p10": round(percentile(values, 0.10), 6),
        "p25": round(percentile(values, 0.25), 6),
        "p50": round(percentile(values, 0.50), 6),
        "p75": round(percentile(values, 0.75), 6),
        "p90": round(percentile(values, 0.90), 6),
        "p95": round(percentile(values, 0.95), 6),
        "p99": round(percentile(values, 0.99), 6),
    }


def histogram(values: list[float], *, bins: int = 10) -> dict[str, Any]:
    if not values:
        return {"bins": [], "counts": [], "bin_edges": []}
    lo, hi = min(values), max(values)
    if lo == hi:
        return {
            "bins": [f"{lo:.4f}"],
            "counts": [len(values)],
            "bin_edges": [lo, hi],
        }
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1) if width > 0 else 0
        counts[idx] += 1
    labels = [f"{edges[i]:.4f}-{edges[i + 1]:.4f}" for i in range(bins)]
    return {"bins": labels, "counts": counts, "bin_edges": [round(e, 6) for e in edges]}


def compare_distributions(
    frozen: list[float],
    research: list[float],
) -> dict[str, Any]:
    fs = distribution_stats(frozen)
    rs = distribution_stats(research)
    return {
        "frozen": fs,
        "research": rs,
        "mean_diff": round(fs["mean"] - rs["mean"], 6),
        "median_diff": round(fs["median"] - rs["median"], 6),
        "max_diff": round(fs["max"] - rs["max"], 6),
        "frozen_compressed_vs_research": fs["max"] < rs["p50"],
    }
