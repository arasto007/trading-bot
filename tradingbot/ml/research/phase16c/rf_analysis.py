"""Phase 16C — RF probability distribution and distance-to-threshold."""

from __future__ import annotations

from typing import Any

import numpy as np


def _percentile(vals: np.ndarray, p: float) -> float:
    if len(vals) == 0:
        return 0.0
    return float(np.percentile(vals, p * 100))


def analyze_rf_distribution(records: list[dict[str, Any]], *, threshold: float = 0.40) -> dict[str, Any]:
    probs = np.array([r["probability"] for r in records], dtype=float)
    if len(probs) == 0:
        return {"count": 0, "histogram": [], "stats": {}}

    bins = [0.0, 0.1, 0.2, 0.3, 0.35, 0.38, 0.39, 0.40, 0.42, 0.45, 0.50, 1.0]
    hist, edges = np.histogram(probs, bins=bins)
    histogram = [
        {"bin_low": round(float(edges[i]), 3), "bin_high": round(float(edges[i + 1]), 3), "count": int(hist[i])}
        for i in range(len(hist))
    ]

    stats = {
        "min": round(float(np.min(probs)), 6),
        "mean": round(float(np.mean(probs)), 6),
        "median": round(float(np.median(probs)), 6),
        "p90": round(_percentile(probs, 0.90), 6),
        "p95": round(_percentile(probs, 0.95), 6),
        "p99": round(_percentile(probs, 0.99), 6),
        "max": round(float(np.max(probs)), 6),
        "std": round(float(np.std(probs)), 6),
        "above_threshold": int(np.sum(probs >= threshold)),
        "above_threshold_rate": round(float(np.mean(probs >= threshold)), 6),
    }

    return {
        "count": len(probs),
        "threshold": threshold,
        "stats": stats,
        "histogram": histogram,
    }


def analyze_distance_to_threshold(
    records: list[dict[str, Any]],
    *,
    threshold: float = 0.40,
) -> dict[str, Any]:
    rejected = [r for r in records if not r.get("rf_pass")]
    distances = [round(threshold - r["probability"], 6) for r in rejected]
    if not distances:
        return {
            "rejected_count": 0,
            "distances": [],
            "stats": {},
        }

    arr = np.array(distances, dtype=float)
    return {
        "rejected_count": len(distances),
        "threshold": threshold,
        "distances_sample": distances[:50],
        "stats": {
            "min_distance": round(float(np.min(arr)), 6),
            "mean_distance": round(float(np.mean(arr)), 6),
            "median_distance": round(float(np.median(arr)), 6),
            "p90_distance": round(_percentile(arr, 0.90), 6),
            "max_distance": round(float(np.max(arr)), 6),
            "within_0.02": int(np.sum(arr <= 0.02)),
            "within_0.05": int(np.sum(arr <= 0.05)),
            "within_0.10": int(np.sum(arr <= 0.10)),
        },
        "within_0.02_rate": round(float(np.mean(arr <= 0.02)), 6),
        "within_0.05_rate": round(float(np.mean(arr <= 0.05)), 6),
    }
