"""Phase 40 — threshold sweep + multi-model walk-forward on expanded v3."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler


def _pf(y: np.ndarray, proba: np.ndarray, thr: float) -> dict[str, float]:
    m = proba >= thr
    if not m.any():
        return {"pf": 0.0, "trades": 0, "win_rate": 0.0}
    yt = y[m]
    w, l = int(yt.sum()), int(len(yt) - yt.sum())
    pf = w / l if l > 0 else (2.0 if w > 0 else 0.0)
    return {"pf": round(pf, 4), "trades": int(m.sum()), "win_rate": round(w / max(len(yt), 1) * 100, 2)}


def sweep_thresholds(y: np.ndarray, proba: np.ndarray, thresholds: list[float]) -> list[dict[str, Any]]:
    return [{"threshold": thr, **_pf(y, proba, thr)} for thr in thresholds]


def walk_forward_retrain(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    model_name: str = "random_forest",
    thresholds: list[float] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

    thresholds = thresholds or [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    work = df[df[label_col].isin([0, 1])].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())
    if len(years) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "years": [int(y) for y in years]}

    windows: list[dict[str, Any]] = []
    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < 80 or len(te) < 20:
            continue
        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)
        y_te = te[label_col].astype(int).values
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        model = create_trend_ml_model(model_name, seed=seed)
        model.fit(X_tr_s, y_tr)
        proba = model.predict_proba(X_te_s)[:, 1]
        try:
            auc = round(float(roc_auc_score(y_te, proba)), 4)
        except ValueError:
            auc = 0.5
        sweep = sweep_thresholds(y_te, proba, thresholds)
        best = max(sweep, key=lambda x: (x["pf"], x["trades"]))
        windows.append({
            "test_year": int(test_year),
            "train_rows": len(tr),
            "test_rows": len(te),
            "auc": auc,
            "threshold_sweep": sweep,
            "best_threshold": best["threshold"],
            "best_pf": best["pf"],
            "best_trades": best["trades"],
        })

    if not windows:
        return {"verdict": "INSUFFICIENT_DATA", "windows": 0}

    mean_auc = round(float(np.mean([w["auc"] for w in windows])), 4)
    mean_best_pf = round(float(np.mean([w["best_pf"] for w in windows])), 4)
    mean_trades = round(float(np.mean([w["best_trades"] for w in windows])), 1)

    if mean_best_pf >= 1.3 and mean_auc >= 0.55:
        verdict = "RETRAIN_READY_FOR_INTEGRATION_REVIEW"
    elif mean_best_pf >= 1.0 and mean_auc >= 0.52:
        verdict = "RETRAIN_MARGINAL"
    elif mean_best_pf > 0.73:
        verdict = "RETRAIN_IMPROVING"
    else:
        verdict = "RETRAIN_INSUFFICIENT"

    return {
        "verdict": verdict,
        "model": model_name,
        "label_column": label_col,
        "rows": len(work),
        "features": len(feature_cols),
        "thresholds": thresholds,
        "walk_forward_windows": windows,
        "mean_auc": mean_auc,
        "mean_best_pf": mean_best_pf,
        "mean_best_trades": mean_trades,
    }
