"""Phase 50 — strict professional walk-forward gate (research only)."""

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


def strict_walk_forward(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    model_name: str = "random_forest",
    thresholds: list[float] | None = None,
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = 15,
    min_windows: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

    thresholds = thresholds or [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
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
        if len(tr) < min_train_rows or len(te) < min_test_rows:
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

        sweep = []
        for thr in thresholds:
            row = {"threshold": thr, **_pf(y_te, proba, thr)}
            sweep.append(row)
        eligible = [s for s in sweep if s["trades"] >= min_test_trades]
        best = max(eligible, key=lambda x: (x["pf"], x["trades"])) if eligible else max(sweep, key=lambda x: x["trades"])

        windows.append({
            "test_year": int(test_year),
            "train_rows": len(tr),
            "test_rows": len(te),
            "auc": auc,
            "best_threshold": best["threshold"],
            "best_pf": best["pf"],
            "best_trades": best["trades"],
            "meets_min_trades": best["trades"] >= min_test_trades,
            "threshold_sweep": sweep,
        })

    if len(windows) < min_windows:
        return {
            "verdict": "INSUFFICIENT_WINDOWS",
            "windows_found": len(windows),
            "min_windows_required": min_windows,
            "walk_forward_windows": windows,
        }

    pfs = [float(w["best_pf"]) for w in windows]
    aucs = [float(w["auc"]) for w in windows]
    mean_pf = round(float(np.mean(pfs)), 4)
    mean_auc = round(float(np.mean(aucs)), 4)
    windows_pf_above_1 = sum(1 for p in pfs if p >= 1.0)
    windows_pf_above_1_3 = sum(1 for p in pfs if p >= 1.3)
    trade_ok = sum(1 for w in windows if w["meets_min_trades"])

    gates = {
        "mean_pf_ge_1_3": mean_pf >= 1.3,
        "mean_auc_ge_0_55": mean_auc >= 0.55,
        "min_windows_ge_3": len(windows) >= min_windows,
        "majority_windows_pf_ge_1": windows_pf_above_1 >= max(2, len(windows) // 2),
        "trade_count_ok": trade_ok >= max(2, len(windows) // 2),
    }
    passed = all(gates.values())

    if passed:
        verdict = "STRICT_GATE_PASS"
    elif mean_pf >= 1.0 and mean_auc >= 0.52:
        verdict = "STRICT_GATE_MARGINAL"
    else:
        verdict = "STRICT_GATE_FAIL"

    return {
        "verdict": verdict,
        "gate_passed": passed,
        "gates": gates,
        "model": model_name,
        "rows": len(work),
        "features": len(feature_cols),
        "walk_forward_windows": windows,
        "mean_pf": mean_pf,
        "mean_auc": mean_auc,
        "windows_pf_above_1": windows_pf_above_1,
        "windows_pf_above_1_3": windows_pf_above_1_3,
        "min_windows": min_windows,
    }
