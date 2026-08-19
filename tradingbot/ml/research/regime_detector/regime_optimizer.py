"""Phase 13.2 — compare regime models by stability, accuracy, overfitting."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.regime_detector.regime_classifier import available_ml_candidates
from tradingbot.ml.research.regime_detector.regime_validator import validate_rule_baseline, walk_forward_validate


def optimize_regime_models(
    features: pd.DataFrame,
    *,
    seed: int = 42,
) -> dict[str, Any]:
    baseline = validate_rule_baseline(features)
    candidates = ["rule_baseline"] + available_ml_candidates()
    rows: list[dict[str, Any]] = []

    rows.append(
        {
            "model": "rule_baseline",
            "mean_test_accuracy": None,
            "mean_stability": baseline["stability"],
            "overfit_gap": 0.0,
            "rank_score": _rank_score(None, baseline["stability"], 0.0),
            "distribution": baseline["distribution"],
        }
    )

    for name in available_ml_candidates():
        wf = walk_forward_validate(features, model_name=name, seed=seed)
        gaps = [w["overfit_gap"] for w in wf["windows"] if not w.get("skipped")]
        mean_gap = float(np.mean(gaps)) if gaps else 0.0
        rows.append(
            {
                "model": name,
                "mean_test_accuracy": wf["mean_test_accuracy"],
                "mean_stability": wf["mean_stability"],
                "overfit_gap": round(mean_gap, 4),
                "rank_score": _rank_score(wf["mean_test_accuracy"], wf["mean_stability"], mean_gap),
                "walk_forward": wf,
            }
        )

    ranked = sorted(rows, key=lambda r: r["rank_score"], reverse=True)
    return {
        "candidates": candidates,
        "ranking": ranked,
        "best_model": ranked[0]["model"] if ranked else "rule_baseline",
        "ranking_criteria": ["stability", "accuracy", "low_overfitting"],
    }


def _rank_score(accuracy: float | None, stability: float, overfit_gap: float) -> float:
    acc = accuracy if accuracy is not None else 0.85
    return round(stability * 0.45 + acc * 0.35 + max(0.0, 1.0 - overfit_gap) * 0.20, 4)


def feature_importance(features: pd.DataFrame, *, seed: int = 42) -> dict[str, Any]:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.regime_detector.regime_classifier import encode_labels, rule_classify
    from tradingbot.ml.research.regime_detector.regime_features import REGIME_FEATURE_COLUMNS

    work = features.copy()
    work["rule_label"] = rule_classify(work)
    cols = [c for c in REGIME_FEATURE_COLUMNS if c in work.columns]
    if len(work) < 100:
        return {"importances": {}, "note": "insufficient samples"}

    ordered = work.sort_values("timestamp")
    cut = int(len(ordered) * 0.8)
    train = ordered.iloc[:cut]
    X = train[cols].astype(np.float64).values
    y = encode_labels(train["rule_label"])
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    rf = RandomForestClassifier(n_estimators=80, max_depth=5, random_state=seed)
    rf.fit(X_s, y)
    imp = {cols[i]: round(float(v), 4) for i, v in enumerate(rf.feature_importances_)}
    return {"importances": dict(sorted(imp.items(), key=lambda x: -x[1]))}
