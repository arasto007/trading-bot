"""Phase 9.9 / 22X — mandatory probability quality gate for candidate selection."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.walk_forward.model_validator import FIXED_STRATEGY

BUY_THRESHOLD = float(FIXED_STRATEGY.buy_threshold)
SELL_THRESHOLD = float(FIXED_STRATEGY.sell_threshold)
MIN_PROBABILITY_STD = 0.015
MIN_PROBABILITY_RANGE = 0.08
COLLAPSED_ZONE_PCT = 95.0
HIST_BIN_WIDTH = 0.05


def probability_histogram(probs: np.ndarray, *, bin_width: float = HIST_BIN_WIDTH) -> dict[str, Any]:
    edges = np.arange(0.0, 1.0 + bin_width, bin_width)
    counts, bin_edges = np.histogram(probs, bins=edges)
    bins: list[dict[str, Any]] = []
    total = max(len(probs), 1)
    for i, count in enumerate(counts):
        lo = round(float(bin_edges[i]), 2)
        hi = round(float(bin_edges[i + 1]), 2)
        bins.append(
            {
                "range": f"{lo:.2f}-{hi:.2f}",
                "lo": lo,
                "hi": hi,
                "count": int(count),
                "pct": round(int(count) / total * 100, 4),
            }
        )
    return {"bin_width": bin_width, "total": len(probs), "bins": bins}


def compute_window_probability_audit(probs: np.ndarray) -> dict[str, Any]:
    """Per-window probability summary for walk-forward aggregation."""
    p = np.asarray(probs, dtype=float).reshape(-1)
    n = len(p)
    if n == 0:
        return {
            "n": 0,
            "buy_count": 0,
            "sell_count": 0,
            "min": 0.0,
            "max": 0.0,
            "sum": 0.0,
            "sum_sq": 0.0,
            "histogram": probability_histogram(p),
        }

    buy_count = int(np.sum(p >= BUY_THRESHOLD))
    sell_count = int(np.sum(p <= SELL_THRESHOLD))
    return {
        "n": n,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "min": round(float(np.min(p)), 6),
        "max": round(float(np.max(p)), 6),
        "sum": round(float(np.sum(p)), 6),
        "sum_sq": round(float(np.sum(p * p)), 6),
        "histogram": probability_histogram(p),
    }


def _merge_histograms(histograms: list[dict[str, Any]]) -> dict[str, Any]:
    if not histograms:
        return probability_histogram(np.array([], dtype=float))

    merged_bins: dict[str, dict[str, Any]] = {}
    total = 0
    for hist in histograms:
        total += int(hist.get("total", 0))
        for row in hist.get("bins", []):
            key = str(row.get("range"))
            if key not in merged_bins:
                merged_bins[key] = dict(row)
                merged_bins[key]["count"] = 0
            merged_bins[key]["count"] += int(row.get("count", 0))

    bins = []
    for row in merged_bins.values():
        count = int(row["count"])
        bins.append(
            {
                **row,
                "count": count,
                "pct": round(count / max(total, 1) * 100, 4),
            }
        )
    bins.sort(key=lambda b: float(b.get("lo", 0.0)))
    return {
        "bin_width": histograms[0].get("bin_width", HIST_BIN_WIDTH),
        "total": total,
        "bins": bins,
    }


def aggregate_experiment_probability_metrics(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool validation-window probability audits into experiment-level metrics."""
    active = [a for a in audits if int(a.get("n", 0)) > 0]
    if not active:
        return {
            "sample_count": 0,
            "buy_coverage_pct": 0.0,
            "sell_coverage_pct": 0.0,
            "min_probability": 0.0,
            "max_probability": 0.0,
            "std": 0.0,
            "range": 0.0,
            "histogram": probability_histogram(np.array([], dtype=float)),
        }

    n_total = sum(int(a["n"]) for a in active)
    buy_total = sum(int(a["buy_count"]) for a in active)
    sell_total = sum(int(a["sell_count"]) for a in active)
    sum_total = sum(float(a["sum"]) for a in active)
    sum_sq_total = sum(float(a["sum_sq"]) for a in active)
    mean = sum_total / n_total
    variance = max(0.0, (sum_sq_total / n_total) - (mean * mean))
    std = float(np.sqrt(variance))
    min_p = min(float(a["min"]) for a in active)
    max_p = max(float(a["max"]) for a in active)

    return {
        "sample_count": n_total,
        "buy_coverage_pct": round(buy_total / n_total * 100, 4),
        "sell_coverage_pct": round(sell_total / n_total * 100, 4),
        "min_probability": round(min_p, 6),
        "max_probability": round(max_p, 6),
        "std": round(std, 6),
        "range": round(max_p - min_p, 6),
        "histogram": _merge_histograms([a["histogram"] for a in active]),
        "thresholds": {
            "buy_threshold": BUY_THRESHOLD,
            "sell_threshold": SELL_THRESHOLD,
            "min_probability_std": MIN_PROBABILITY_STD,
            "min_probability_range": MIN_PROBABILITY_RANGE,
            "collapsed_zone_pct": COLLAPSED_ZONE_PCT,
        },
    }


def distribution_collapsed(metrics: dict[str, Any]) -> bool:
    buy = float(metrics.get("buy_coverage_pct", 0.0))
    sell = float(metrics.get("sell_coverage_pct", 0.0))
    std = float(metrics.get("std", 0.0))
    p_range = float(metrics.get("range", 0.0))
    max_p = float(metrics.get("max_probability", 0.0))

    if buy >= COLLAPSED_ZONE_PCT or sell >= COLLAPSED_ZONE_PCT:
        return True
    if std < MIN_PROBABILITY_STD:
        return True
    if p_range < MIN_PROBABILITY_RANGE:
        return True
    if max_p < BUY_THRESHOLD:
        return True
    return False


def evaluate_probability_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    """Hard gate — candidate must pass all checks before ranking acceptance."""
    buy = float(metrics.get("buy_coverage_pct", 0.0))
    sell = float(metrics.get("sell_coverage_pct", 0.0))
    min_p = float(metrics.get("min_probability", 0.0))
    max_p = float(metrics.get("max_probability", 0.0))
    std = float(metrics.get("std", 0.0))

    rejection_reasons: list[str] = []
    if buy == 0.0:
        rejection_reasons.append("buy_coverage_zero")
    if sell == 0.0:
        rejection_reasons.append("sell_coverage_zero")
    if max_p < BUY_THRESHOLD:
        rejection_reasons.append("max_probability_below_buy_threshold")
    if min_p > SELL_THRESHOLD:
        rejection_reasons.append("min_probability_above_sell_threshold")
    if std < MIN_PROBABILITY_STD:
        rejection_reasons.append("probability_std_below_minimum")
    if distribution_collapsed(metrics):
        rejection_reasons.append("probability_distribution_collapsed")

    passed = len(rejection_reasons) == 0
    acceptance_reason = (
        "probability_quality_passed"
        if passed
        else None
    )
    return {
        "passed": passed,
        "acceptance_reason": acceptance_reason,
        "rejection_reason": "; ".join(rejection_reasons) if rejection_reasons else None,
        "rejection_reasons": rejection_reasons,
        "checks": {
            "buy_coverage_nonzero": buy > 0.0,
            "sell_coverage_nonzero": sell > 0.0,
            "max_probability_ge_buy_threshold": max_p >= BUY_THRESHOLD,
            "min_probability_le_sell_threshold": min_p <= SELL_THRESHOLD,
            "probability_std_ge_minimum": std >= MIN_PROBABILITY_STD,
            "distribution_not_collapsed": not distribution_collapsed(metrics),
        },
    }


def compute_probability_metrics(probs: np.ndarray) -> dict[str, Any]:
    """Direct metrics from a probability vector (used in tests)."""
    audit = compute_window_probability_audit(probs)
    return aggregate_experiment_probability_metrics([audit])
