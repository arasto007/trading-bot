"""Phase 13.2 — walk-forward regime validation (chronological, scaler-only train)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.regime_detector.regime_classifier import (
    REGIME_LABELS,
    create_ml_model,
    encode_labels,
    rule_classify,
)
from tradingbot.ml.research.regime_detector.regime_features import REGIME_FEATURE_COLUMNS


def build_expanding_windows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Expanding walk-forward windows for 2021-2026 style periods."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    years = sorted(ts.dt.year.unique().tolist())
    windows: list[dict[str, Any]] = []

    if years and min(years) <= 2021:
        windows.append(
            {
                "window_id": "wf_2021_2024_train",
                "train_years": (2021, 2023),
                "test_years": (2024, 2024),
            }
        )
        if max(years) >= 2025:
            windows.append(
                {
                    "window_id": "wf_2021_2025_train",
                    "train_years": (2021, 2024),
                    "test_years": (2025, 2025),
                }
            )
        if max(years) >= 2026:
            windows.append(
                {
                    "window_id": "wf_2021_2026_train",
                    "train_years": (2021, 2025),
                    "test_years": (2026, 2026),
                }
            )

    if not windows and len(years) >= 3:
        y0, ym, y1 = years[0], years[len(years) // 2], years[-1]
        windows.append({"window_id": "wf_adaptive", "train_years": (y0, ym), "test_years": (y1, y1)})

    if not windows:
        n = len(df)
        cut = int(n * 0.75)
        windows.append({"window_id": "wf_index", "train_end": cut})

    return windows


def _year_mask(ts: pd.Series, start: int, end: int) -> np.ndarray:
    years = pd.to_datetime(ts, utc=True).dt.year
    return ((years >= start) & (years <= end)).to_numpy()


def _split_window(df: pd.DataFrame, window: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "train_end" in window:
        ordered = df.sort_values("timestamp").reset_index(drop=True)
        return ordered.iloc[: window["train_end"]], ordered.iloc[window["train_end"] :]

    ts = df["timestamp"]
    tr_s, tr_e = window["train_years"]
    te_s, te_e = window["test_years"]
    train = df.loc[_year_mask(ts, tr_s, tr_e)]
    test = df.loc[_year_mask(ts, te_s, te_e)]
    return train, test


def regime_stability(labels: np.ndarray) -> float:
    """Fraction of consecutive bars with same regime (higher = more stable)."""
    if len(labels) < 2:
        return 1.0
    same = sum(1 for i in range(1, len(labels)) if labels[i] == labels[i - 1])
    return round(same / (len(labels) - 1), 4)


def validate_rule_baseline(features: pd.DataFrame) -> dict[str, Any]:
    labels = rule_classify(features)
    y = encode_labels(labels)
    dist = {name: int((labels == name).sum()) for name in REGIME_LABELS}
    return {
        "model": "rule_baseline",
        "distribution": dist,
        "stability": regime_stability(y),
        "total_samples": len(features),
    }


def walk_forward_validate(
    features: pd.DataFrame,
    *,
    model_name: str = "logistic",
    seed: int = 42,
) -> dict[str, Any]:
    """Train ML on rule labels; chronological split; scaler fit on train only."""
    work = features.copy()
    work["rule_label"] = rule_classify(work)
    y_all = encode_labels(work["rule_label"])
    cols = [c for c in REGIME_FEATURE_COLUMNS if c in work.columns]

    windows_out: list[dict[str, Any]] = []
    for window in build_expanding_windows(work):
        train, test = _split_window(work, window)
        if len(train) < 50 or len(test) < 20:
            windows_out.append({"window_id": window["window_id"], "skipped": True})
            continue

        X_tr = train[cols].astype(np.float64).values
        y_tr = encode_labels(train["rule_label"])
        X_te = test[cols].astype(np.float64).values
        y_te = encode_labels(test["rule_label"])

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)

        model = create_ml_model(model_name, seed=seed)
        model.fit(X_tr_s, y_tr)

        tr_pred = model.predict(X_tr_s)
        te_pred = model.predict(X_te_s)

        cm = confusion_matrix(y_te, te_pred, labels=list(range(len(REGIME_LABELS))))
        windows_out.append(
            {
                "window_id": window["window_id"],
                "train_rows": len(train),
                "test_rows": len(test),
                "train_accuracy": round(float(accuracy_score(y_tr, tr_pred)), 4),
                "test_accuracy": round(float(accuracy_score(y_te, te_pred)), 4),
                "test_f1_macro": round(float(f1_score(y_te, te_pred, average="macro", zero_division=0)), 4),
                "overfit_gap": round(float(accuracy_score(y_tr, tr_pred) - accuracy_score(y_te, te_pred)), 4),
                "regime_stability": regime_stability(te_pred),
                "confusion_matrix": cm.tolist(),
                "predicted_distribution": {
                    name: int((te_pred == i).sum()) for i, name in enumerate(REGIME_LABELS)
                },
                "shuffle": False,
            }
        )

    test_accs = [w["test_accuracy"] for w in windows_out if not w.get("skipped")]
    stabilities = [w["regime_stability"] for w in windows_out if not w.get("skipped")]
    return {
        "model": model_name,
        "windows": windows_out,
        "mean_test_accuracy": round(float(np.mean(test_accs)), 4) if test_accs else 0.0,
        "mean_stability": round(float(np.mean(stabilities)), 4) if stabilities else 0.0,
        "chronological": True,
        "shuffle": False,
        "scaler_fit": "train_only",
    }
