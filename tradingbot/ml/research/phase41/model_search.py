"""Phase 41 — advanced model search on expanded v3 (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase40.retrain_sweep import walk_forward_retrain
from tradingbot.ml.research.trend_ml.models import available_trend_ml_candidates


def per_year_label_stats(df: pd.DataFrame, label_col: str = "label_v3") -> list[dict[str, Any]]:
    work = df[df[label_col].isin([0, 1])].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    rows: list[dict[str, Any]] = []
    for year, grp in work.groupby(work["timestamp"].dt.year):
        wr = round(float(grp[label_col].mean()) * 100, 2)
        rows.append({"year": int(year), "rows": len(grp), "win_rate_pct": wr})
    return sorted(rows, key=lambda x: x["year"])


def search_models(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    models: list[str] | None = None,
    thresholds: list[float] | None = None,
) -> dict[str, Any]:
    models = models or available_trend_ml_candidates()
    thresholds = thresholds or [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    results: dict[str, dict] = {}
    best_name = ""
    best_pf = -1.0
    for name in models:
        try:
            res = walk_forward_retrain(
                df, label_col, feature_cols, model_name=name, thresholds=thresholds
            )
        except Exception as exc:
            res = {"verdict": "MODEL_FAILED", "error": str(exc)}
        results[name] = res
        pf = float(res.get("mean_best_pf", 0) or 0)
        if pf > best_pf:
            best_pf = pf
            best_name = name

    overall = results.get(best_name, {})
    verdict = overall.get("verdict", "RETRAIN_INSUFFICIENT")
    return {
        "verdict": verdict,
        "best_model": best_name,
        "mean_best_pf": best_pf,
        "mean_auc": overall.get("mean_auc"),
        "models": results,
        "per_year_labels": per_year_label_stats(df, label_col),
    }
