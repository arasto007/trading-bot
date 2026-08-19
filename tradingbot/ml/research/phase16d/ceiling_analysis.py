"""Phase 16D — confidence saturation vs feature dimensions."""

from __future__ import annotations

from typing import Any

import numpy as np


def _binned_stats(values: list[float], probs: list[float], *, bins: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    arr_v = np.array(values, dtype=float)
    arr_p = np.array(probs, dtype=float)
    edges = np.quantile(arr_v, np.linspace(0, 1, bins + 1))
    edges = np.unique(edges)
    if len(edges) < 2:
        return [{"bin": "all", "mean_prob": round(float(np.mean(arr_p)), 6), "max_prob": round(float(np.max(arr_p)), 6), "count": len(arr_p)}]
    out = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        mask = (arr_v >= lo) & (arr_v <= hi if i == len(edges) - 2 else arr_v < hi)
        if not mask.any():
            continue
        sub = arr_p[mask]
        out.append({
            "bin_low": round(float(lo), 4),
            "bin_high": round(float(hi), 4),
            "count": int(mask.sum()),
            "mean_prob": round(float(np.mean(sub)), 6),
            "max_prob": round(float(np.max(sub)), 6),
            "std_prob": round(float(np.std(sub)), 6),
        })
    return out


def _saturation_score(bins: list[dict[str, Any]]) -> float:
    """Low spread across bins → saturated (lacks separating information)."""
    if len(bins) < 2:
        return 1.0
    means = [b["mean_prob"] for b in bins]
    return round(1.0 - min(1.0, float(np.std(means)) / 0.05), 4)


def analyze_feature_ceiling(records: list[Any]) -> dict[str, Any]:
    probs = [r.probability for r in records]
    dimensions = {
        "adx": [r.adx for r in records],
        "rsi": [r.existing.get("rsi", 0.0) for r in records],
        "ema50_slope": [r.existing.get("ema50_slope", 0.0) for r in records],
        "breakout_distance": [r.existing.get("breakout_distance", 0.0) for r in records],
        "atr_percentile": [r.atr_percentile for r in records],
        "candle_momentum": [r.existing.get("candle_momentum", 0.0) for r in records],
        "trend_persistence": [r.candidates.get("trend_persistence", 0.0) for r in records],
        "trend_age": [r.candidates.get("trend_age", 0.0) for r in records],
    }

    by_dimension: dict[str, Any] = {}
    saturation_scores: dict[str, float] = {}
    for dim, vals in dimensions.items():
        bins = _binned_stats(vals, probs)
        sat = _saturation_score(bins)
        by_dimension[dim] = {"bins": bins, "saturation_score": sat}
        saturation_scores[dim] = sat

    overall_sat = float(np.mean(list(saturation_scores.values()))) if saturation_scores else 1.0
    lacks_information = overall_sat > 0.75

    return {
        "bar_count": len(records),
        "probability_stats": {
            "mean": round(float(np.mean(probs)), 6) if probs else 0.0,
            "max": round(float(np.max(probs)), 6) if probs else 0.0,
            "std": round(float(np.std(probs)), 6) if probs else 0.0,
        },
        "by_dimension": by_dimension,
        "saturation_scores": saturation_scores,
        "overall_saturation_score": round(overall_sat, 4),
        "confidence_saturates_due_to_lack_of_information": lacks_information,
        "interpretation": (
            "RF confidence does not scale with stronger trend indicators — "
            "feature space appears information-limited for separation."
            if lacks_information
            else "Some dimensions show probability spread — partial information present."
        ),
    }
