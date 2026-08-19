"""Phase 9.6 — stable feature selection across splits."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance

from tradingbot.ml.data.paths import feature_stability_report_path
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.data_loader import TrainingSplits
from tradingbot.ml.training.model_factory import DEFAULT_SEED

DRIFT_THRESHOLD = 0.35
VARIANCE_EPS = 1e-12


def _importance_by_split(splits: TrainingSplits, split: str, seed: int) -> dict[str, float]:
    if split == "train":
        X, y = splits.train_xy()
    elif split == "validation":
        X, y = splits.validation_xy()
    else:
        X, y = splits.test_xy()
    features = [f for f in splits.feature_columns if f in X.columns]
    Xv = X.loc[:, features].astype(np.float64).values
    yv = y.to_numpy(dtype=int)
    if len(np.unique(yv)) < 2:
        return {f: 0.0 for f in features}
    rf = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=seed, n_jobs=1)
    rf.fit(Xv, yv)
    perm = permutation_importance(rf, Xv, yv, n_repeats=3, random_state=seed, n_jobs=1)
    return {features[i]: float(perm.importances_mean[i]) for i in range(len(features))}


def run_feature_stability_selection(
    splits: TrainingSplits,
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Rank features by cross-split stability and build feature sets A/B/C."""
    features = [f for f in feature_names() if f in splits.train.columns]
    train_imp = _importance_by_split(splits, "train", seed)
    val_imp = _importance_by_split(splits, "validation", seed)
    test_imp = _importance_by_split(splits, "test", seed)

    rows: list[dict[str, Any]] = []
    stable: list[str] = []
    unstable: list[str] = []
    remove: list[str] = []

    for feat in features:
        tr = train_imp.get(feat, 0.0)
        va = val_imp.get(feat, 0.0)
        te = test_imp.get(feat, 0.0)
        drift = abs(tr - te)
        var_train = float(splits.train[feat].astype(float).std()) if feat in splits.train.columns else 0.0
        stability = 1.0 - min(1.0, drift / max(tr, 1e-9))

        if var_train <= VARIANCE_EPS:
            category = "REMOVE"
            remove.append(feat)
        elif drift > DRIFT_THRESHOLD or stability < 0.5:
            category = "UNSTABLE"
            unstable.append(feat)
        else:
            category = "STABLE"
            stable.append(feat)

        rows.append(
            {
                "feature": feat,
                "train_importance": round(tr, 6),
                "validation_importance": round(va, 6),
                "test_importance": round(te, 6),
                "drift_score": round(drift, 6),
                "variance_stability": round(var_train, 6),
                "stability_score": round(stability, 4),
                "category": category,
            }
        )

    ranked_stable = sorted(
        stable,
        key=lambda f: -train_imp.get(f, 0.0),
    )
    feature_sets = {
        "A_top10_stable": ranked_stable[:10],
        "B_top15_stable": ranked_stable[:15],
        "C_all_except_unstable": [f for f in features if f not in unstable and f not in remove],
    }

    return {
        "phase": "9.6",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "features": rows,
        "stable_features": ranked_stable,
        "unstable_features": unstable,
        "remove_features": remove,
        "feature_sets": feature_sets,
    }


def save_feature_stability_report(
    splits: TrainingSplits,
    base_dir: str | Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> Path:
    report = run_feature_stability_selection(splits, seed=seed)
    path = feature_stability_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
