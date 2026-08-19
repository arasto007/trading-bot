"""Phase 36 — chronological retrain validation (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.dataset.splitter import time_based_split


def _pf(y_true: np.ndarray, proba: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    mask = proba >= threshold
    if not mask.any():
        return {"pf": 0.0, "trades": 0, "win_rate": 0.0}
    yt = y_true[mask]
    wins = int(yt.sum())
    losses = int(len(yt) - wins)
    pf = wins / losses if losses > 0 else (2.0 if wins > 0 else 0.0)
    return {"pf": round(pf, 4), "trades": int(mask.sum()), "win_rate": round(wins / max(len(yt), 1) * 100, 2)}


def train_eval_chronological(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Train logistic model with scaler fit on train only — no shuffle."""
    work = df[df[label_col].isin([0, 1])].copy()
    if len(work) < 50:
        return {"error": "insufficient_rows", "rows": len(work)}

    split = time_based_split(work, purge_bars=72, timeframe="M5")
    train, val, test = split.train, split.validation, split.test
    if train.empty or test.empty:
        return {"error": "split_empty", "rows": len(work)}

    X_tr = train[feature_cols].astype(float).fillna(0)
    y_tr = train[label_col].astype(int).values
    X_va = val[feature_cols].astype(float).fillna(0) if not val.empty else X_tr.iloc[:0]
    y_va = val[label_col].astype(int).values if not val.empty else np.array([])
    X_te = test[feature_cols].astype(float).fillna(0)
    y_te = test[label_col].astype(int).values

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_va_s = scaler.transform(X_va) if len(y_va) else np.empty((0, X_tr.shape[1]))
    X_te_s = scaler.transform(X_te)

    model = LogisticRegression(max_iter=500, random_state=seed, class_weight="balanced")
    model.fit(X_tr_s, y_tr)

    def _eval(Xs, y, name: str) -> dict:
        if len(y) == 0:
            return {"split": name, "rows": 0}
        proba = model.predict_proba(Xs)[:, 1]
        try:
            auc = round(float(roc_auc_score(y, proba)), 4) if len(np.unique(y)) > 1 else 0.5
        except ValueError:
            auc = 0.5
        acc = round(float(accuracy_score(y, proba >= 0.5)), 4)
        pf_stats = _pf(y, proba)
        return {"split": name, "rows": len(y), "auc": auc, "accuracy": acc, **pf_stats}

    return {
        "label_column": label_col,
        "train_rows": len(train),
        "val_rows": len(val),
        "test_rows": len(test),
        "features": len(feature_cols),
        "validation": _eval(X_va_s, y_va, "validation"),
        "test": _eval(X_te_s, y_te, "test"),
        "baseline_test_pf": round(float(y_te.mean()) / max(1 - float(y_te.mean()), 0.01), 4),
        "baseline_test_wr": round(float(y_te.mean()) * 100, 2),
    }
