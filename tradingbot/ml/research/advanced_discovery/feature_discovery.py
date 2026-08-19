"""Phase 9.5 — deep feature analysis for edge discovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import mutual_info_classif
from sklearn.inspection import permutation_importance

from tradingbot.ml.data.paths import feature_discovery_report_path
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.data_loader import TrainingSplits
from tradingbot.ml.training.model_factory import DEFAULT_SEED

LOW_MI_THRESHOLD = 0.001
LOW_CORR_THRESHOLD = 0.01
DRIFT_THRESHOLD = 0.35


def _split_frame(splits: TrainingSplits, name: str) -> pd.DataFrame:
    if name == "train":
        return splits.train
    if name == "validation":
        return splits.validation
    return splits.test


def _feature_stats(frame: pd.DataFrame, feature: str, y: pd.Series) -> dict[str, float]:
    x = frame[feature].astype(float)
    if x.std() <= 1e-12:
        return {"correlation": 0.0, "mutual_information": 0.0}
    corr = float(x.corr(y.astype(float)))
    if np.isnan(corr):
        corr = 0.0
    mi = float(
        mutual_info_classif(
            x.to_numpy().reshape(-1, 1),
            y.to_numpy(),
            random_state=DEFAULT_SEED,
            discrete_features=False,
        )[0]
    )
    return {"correlation": round(corr, 6), "mutual_information": round(mi, 6)}


def run_feature_discovery(
    splits: TrainingSplits,
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Analyze registry features for predictive edge and stability."""
    features = [f for f in feature_names() if f in splits.train.columns]
    split_stats: dict[str, dict[str, dict[str, float]]] = {}

    for split_name in ("train", "validation", "test"):
        frame = _split_frame(splits, split_name)
        y = frame["label"].astype(int)
        split_stats[split_name] = {
            feat: _feature_stats(frame, feat, y) for feat in features
        }

    train_X, y_train = splits.train_xy()
    val_X, y_val = splits.validation_xy()
    X_train = train_X.astype(np.float64).values
    X_val = val_X.astype(np.float64).values
    y_tr = y_train.to_numpy(dtype=int)
    y_va = y_val.to_numpy(dtype=int)

    rf = RandomForestClassifier(n_estimators=60, max_depth=5, random_state=seed, n_jobs=1)
    rf.fit(X_train, y_tr)
    perm = permutation_importance(rf, X_val, y_va, n_repeats=5, random_state=seed, n_jobs=1)

    rankings: list[dict[str, Any]] = []
    useless: list[str] = []
    unstable: list[str] = []

    for i, feat in enumerate(features):
        train_mi = split_stats["train"][feat]["mutual_information"]
        val_mi = split_stats["validation"][feat]["mutual_information"]
        test_mi = split_stats["test"][feat]["mutual_information"]
        drift = abs(train_mi - test_mi)
        stability = 1.0 - min(1.0, drift / max(train_mi, 1e-9))

        entry = {
            "feature": feat,
            "correlation": split_stats["train"][feat]["correlation"],
            "mutual_information_train": train_mi,
            "mutual_information_validation": val_mi,
            "mutual_information_test": test_mi,
            "permutation_importance": round(float(perm.importances_mean[i]), 6),
            "stability_score": round(stability, 4),
            "importance_drift_train_test": round(drift, 6),
        }
        rankings.append(entry)

        if train_mi < LOW_MI_THRESHOLD and abs(entry["correlation"]) < LOW_CORR_THRESHOLD:
            useless.append(feat)
        if drift > DRIFT_THRESHOLD or stability < 0.5:
            unstable.append(feat)

    rankings.sort(
        key=lambda r: (
            -r["permutation_importance"],
            -r["mutual_information_train"],
            -abs(r["correlation"]),
        )
    )
    for idx, row in enumerate(rankings):
        row["rank"] = idx + 1

    return {
        "phase": "9.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "feature_count": len(features),
        "rankings": rankings,
        "top_features": [r["feature"] for r in rankings[:15]],
        "useless_features": useless,
        "unstable_features": unstable,
        "split_summary": split_stats,
        "test_roc_auc_diagnosis": _diagnose_low_test_auc(rankings, unstable, useless),
    }


def _diagnose_low_test_auc(
    rankings: list[dict[str, Any]],
    unstable: list[str],
    useless: list[str],
) -> list[str]:
    notes: list[str] = []
    if len(unstable) >= 5:
        notes.append(f"{len(unstable)} features show train/test importance drift — overfitting risk")
    if len(useless) >= 3:
        notes.append(f"{len(useless)} features carry near-zero MI/correlation — noise features")
    top = rankings[:5]
    if top and top[0]["mutual_information_test"] < 0.01:
        notes.append("Top train features do not generalize to test split")
    if not notes:
        notes.append("Low test AUC likely driven by weak label signal, not single-feature instability")
    return notes


def save_feature_discovery_report(
    splits: TrainingSplits,
    base_dir: str | Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> Path:
    report = run_feature_discovery(splits, seed=seed)
    path = feature_discovery_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
