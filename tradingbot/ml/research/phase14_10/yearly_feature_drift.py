"""Phase 14.10 — yearly feature distribution drift."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_10.config import FEATURE_DRIFT_COLUMNS, WF_YEARS, slice_year


def _year_feature_stats(unified: pd.DataFrame, year: int) -> dict[str, Any] | None:
    if unified.empty or "timestamp" not in unified.columns:
        return None
    u = unified.copy()
    u["timestamp"] = pd.to_datetime(u["timestamp"], utc=True)
    u = u[u["timestamp"].dt.year == year]
    if u.empty:
        return None

    stats: dict[str, Any] = {"bars": len(u)}
    for col in FEATURE_DRIFT_COLUMNS:
        if col not in u.columns:
            continue
        vals = pd.to_numeric(u[col], errors="coerce").dropna()
        if vals.empty:
            continue
        stats[col] = {
            "mean": round(float(vals.mean()), 6),
            "std": round(float(vals.std()), 6),
            "p25": round(float(np.percentile(vals, 25)), 6),
            "p50": round(float(np.percentile(vals, 50)), 6),
            "p75": round(float(np.percentile(vals, 75)), 6),
        }
    return stats


def _drift_score(baseline: dict[str, float], current: dict[str, float]) -> float:
    if not baseline or not current:
        return 0.0
    deltas = []
    for key in baseline:
        if key in current and abs(baseline[key]) > 1e-9:
            deltas.append(abs(current[key] - baseline[key]) / abs(baseline[key]))
        elif key in current:
            deltas.append(abs(current[key]))
    return round(float(np.mean(deltas)) if deltas else 0.0, 4)


def analyze_feature_drift(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    years = years or WF_YEARS
    unified = build_unified_frame(candles, dataset)
    per_year: dict[str, Any] = {}

    for year in years:
        stats = _year_feature_stats(unified, year)
        if stats is None:
            per_year[str(year)] = {"year": year, "skipped": True}
        else:
            per_year[str(year)] = {"year": year, "skipped": False, "features": stats}

    active = {k: v for k, v in per_year.items() if not v.get("skipped")}
    baseline_year = min(int(y) for y in active) if active else None
    drift_vs_baseline: dict[str, Any] = {}

    if baseline_year is not None:
        base_feats = active[str(baseline_year)]["features"]
        for year_key, payload in active.items():
            if int(year_key) == baseline_year:
                continue
            year_feats = payload["features"]
            col_drifts: dict[str, float] = {}
            for col in FEATURE_DRIFT_COLUMNS:
                b = base_feats.get(col, {})
                c = year_feats.get(col, {})
                if b and c:
                    col_drifts[col] = _drift_score(
                        {"mean": b["mean"], "std": b["std"]},
                        {"mean": c["mean"], "std": c["std"]},
                    )
            drift_vs_baseline[year_key] = {
                "vs_year": baseline_year,
                "per_feature_drift": col_drifts,
                "mean_drift": round(float(np.mean(list(col_drifts.values()))), 4) if col_drifts else 0.0,
            }

    ranked = sorted(
        ((k, v.get("mean_drift", 0.0)) for k, v in drift_vs_baseline.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    shifted_features: list[str] = []
    if drift_vs_baseline:
        agg: dict[str, list[float]] = {}
        for payload in drift_vs_baseline.values():
            for col, score in payload.get("per_feature_drift", {}).items():
                agg.setdefault(col, []).append(score)
        shifted_features = [
            col for col, scores in sorted(agg.items(), key=lambda x: np.mean(x[1]), reverse=True)
            if np.mean(scores) > 0.15
        ]

    return {
        "phase": "14.10",
        "per_year": per_year,
        "drift_vs_baseline": drift_vs_baseline,
        "baseline_year": baseline_year,
        "most_shifted_features": shifted_features[:5],
        "drift_ranking": [{"year": int(k), "mean_drift": v} for k, v in ranked],
        "feature_columns": list(FEATURE_DRIFT_COLUMNS),
    }
