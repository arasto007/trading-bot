"""Phase 13.4 — trend ML model ranking and selection."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.trend_ml.models import available_trend_ml_candidates
from tradingbot.ml.research.trend_ml.validator import walk_forward_validate


def optimize_trend_ml_models(
    samples: pd.DataFrame,
    *,
    seed: int = 42,
    threshold: float = 0.55,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name in available_trend_ml_candidates():
        wf = walk_forward_validate(samples, model_name=name, seed=seed, threshold=threshold)
        rows.append(
            {
                "model": name,
                "mean_test_roc_auc": wf["mean_test_roc_auc"],
                "mean_auc_gap": wf["mean_auc_gap"],
                "mean_profit_factor": wf["mean_profit_factor"],
                "mean_expectancy_r": wf["mean_expectancy_r"],
                "mean_win_rate": wf["mean_win_rate"],
                "robustness_score": wf["robustness_score"],
                "rank_score": _rank_score(wf),
                "walk_forward": wf,
            }
        )

    ranked = sorted(rows, key=lambda r: r["rank_score"], reverse=True)
    return {
        "candidates": available_trend_ml_candidates(),
        "ranking": ranked,
        "best_model": ranked[0]["model"] if ranked else "logistic",
        "ranking_criteria": ["robustness", "low_overfit", "expectancy", "auc"],
        "threshold": threshold,
    }


def _rank_score(wf: dict[str, Any]) -> float:
    robustness = float(wf.get("robustness_score", 0.0))
    overfit_penalty = max(0.0, 1.0 - float(wf.get("mean_auc_gap", 0.0)))
    expectancy = float(wf.get("mean_expectancy_r", 0.0))
    exp_norm = min(1.0, max(0.0, (expectancy + 1.0) / 3.0))
    auc = float(wf.get("mean_test_roc_auc", 0.5))
    return round(robustness * 0.35 + overfit_penalty * 0.25 + exp_norm * 0.25 + auc * 0.15, 4)


def overfit_analysis(comparison: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in comparison.get("ranking", []):
        gaps = [
            w.get("auc_gap", 0.0)
            for w in row.get("walk_forward", {}).get("windows", [])
            if not w.get("skipped")
        ]
        rows.append(
            {
                "model": row["model"],
                "mean_auc_gap": row.get("mean_auc_gap", 0.0),
                "max_auc_gap": round(float(max(gaps)), 4) if gaps else 0.0,
                "overfit_risk": "low" if row.get("mean_auc_gap", 1.0) < 0.08 else "moderate",
            }
        )
    return {"models": rows, "threshold_gap_warning": 0.15}
