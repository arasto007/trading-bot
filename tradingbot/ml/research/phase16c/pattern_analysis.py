"""Phase 16C — pattern analysis for rejected TREND bars."""

from __future__ import annotations

from typing import Any

import numpy as np


PATTERN_FIELDS = (
    "adx",
    "atr_percentile",
    "ema20_slope",
    "ema50_slope",
    "candle_momentum",
    "macd_histogram",
    "breakout_distance",
    "rsi",
    "higher_high_count",
    "lower_low_count",
)


def _session_from_row(r: dict[str, Any]) -> str:
    return str(r.get("session", "unknown"))


def _field_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "mean": round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
    }


def analyze_rejection_patterns(records: list[dict[str, Any]]) -> dict[str, Any]:
    rejected = [r for r in records if not r.get("rf_pass")]
    accepted = [r for r in records if r.get("rf_pass")]
    all_trend = records

    def _collect(subset: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for field in PATTERN_FIELDS:
            vals = [float(r.get("features", {}).get(field, r.get(field, 0.0))) for r in subset]
            out[field] = _field_stats(vals)
        sessions: dict[str, int] = {}
        for r in subset:
            s = _session_from_row(r)
            sessions[s] = sessions.get(s, 0) + 1
        out["session_distribution"] = sessions
        adx_vals = [float(r.get("adx", 0)) for r in subset]
        out["high_adx_rate"] = round(
            float(np.mean([a > 30 for a in adx_vals])) if adx_vals else 0.0, 4,
        )
        out["high_vol_rate"] = round(
            float(np.mean([float(r.get("atr_percentile", 0)) > 70 for r in subset])) if subset else 0.0,
            4,
        )
        return out

    rej_stats = _collect(rejected)
    acc_stats = _collect(accepted) if accepted else {}
    all_stats = _collect(all_trend)

    # Common rejection signature: compare rejected mean vs accepted mean
    signatures: list[dict[str, Any]] = []
    for field in PATTERN_FIELDS:
        rej_m = rej_stats.get(field, {}).get("mean", 0.0)
        acc_m = acc_stats.get(field, {}).get("mean", 0.0) if acc_stats else all_stats[field]["mean"]
        delta = rej_m - acc_m
        if abs(delta) > 0.01 or field in ("adx", "macd_histogram", "breakout_distance"):
            signatures.append({
                "field": field,
                "rejected_mean": rej_m,
                "accepted_mean": acc_m,
                "delta": round(delta, 4),
            })
    signatures.sort(key=lambda x: -abs(x["delta"]))

    return {
        "rejected_count": len(rejected),
        "accepted_count": len(accepted),
        "rejected_patterns": rej_stats,
        "accepted_patterns": acc_stats,
        "all_trend_patterns": all_stats,
        "distinctive_signatures": signatures[:8],
        "trend_duration_proxy": {
            "rejected_hh_mean": rej_stats.get("higher_high_count", {}).get("mean", 0),
            "rejected_ll_mean": rej_stats.get("lower_low_count", {}).get("mean", 0),
        },
    }
