"""Phase 13.8 — trend ML retraining with expanding walk-forward."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.phase13_8.config import ML_MODELS, WALK_FORWARD_YEARS_138
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model


def _year_series(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.year


def train_and_evaluate_models(
    samples: pd.DataFrame,
    *,
    seed: int = 42,
    quick: bool = False,
) -> dict[str, Any]:
    if samples.empty:
        return {"models": [], "best_model": None}

    cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in samples.columns]
    years = WALK_FORWARD_YEARS_138[:1] if quick else WALK_FORWARD_YEARS_138
    models_to_test = ("logistic",) if quick else ML_MODELS
    results: list[dict[str, Any]] = []

    for model_name in models_to_test:
        window_metrics: list[dict[str, Any]] = []
        for year in years:
            ts = _year_series(samples["timestamp"])
            train = samples[ts < year]
            test = samples[ts == year]
            if train.empty or test.empty:
                continue
            X_tr = train[cols].astype(float)
            y_tr = train["successful_trade"].astype(int).values
            X_te = test[cols].astype(float)
            y_te = test["successful_trade"].astype(int).values
            scaler = StandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)
            model = create_trend_ml_model(model_name, seed=seed)
            model.fit(X_tr_s, y_tr)
            proba = model.predict_proba(X_te_s)[:, 1]
            try:
                auc = float(roc_auc_score(y_te, proba)) if len(np.unique(y_te)) > 1 else 0.5
            except ValueError:
                auc = 0.5
            accepted = proba >= 0.50
            wins = y_te[accepted].sum()
            losses = (1 - y_te[accepted]).sum()
            pf = float(wins / losses) if losses > 0 else (2.0 if wins > 0 else 0.0)
            window_metrics.append(
                {
                    "year": year,
                    "auc": round(auc, 4),
                    "pf_filtered": round(pf, 4),
                    "trades": int(accepted.sum()),
                }
            )

        mean_auc = float(np.mean([w["auc"] for w in window_metrics])) if window_metrics else 0.0
        mean_pf = float(np.mean([w["pf_filtered"] for w in window_metrics])) if window_metrics else 0.0
        total_trades = int(sum(w["trades"] for w in window_metrics))
        results.append(
            {
                "model": model_name,
                "mean_auc": round(mean_auc, 4),
                "mean_pf_filtered": round(mean_pf, 4),
                "total_wf_trades": total_trades,
                "windows": window_metrics,
                "robustness_score": round(min(1.0, mean_auc) * 0.6 + min(1.0, mean_pf / 2.0) * 0.4, 4),
            }
        )

    ranked = sorted(results, key=lambda r: (r["robustness_score"], r["mean_auc"]), reverse=True)
    best = ranked[0] if ranked else None
    return {"models": ranked, "best_model": best["model"] if best else None, "ranking": ranked}


def fit_production_model(
    samples: pd.DataFrame,
    *,
    model_name: str,
    seed: int = 42,
) -> tuple[Any, StandardScaler, list[str]]:
    cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in samples.columns]
    ordered = samples.sort_values("timestamp")
    X = ordered[cols].astype(float)
    y = ordered["successful_trade"].astype(int).values
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    model = create_trend_ml_model(model_name, seed=seed)
    model.fit(X_s, y)
    return model, scaler, cols
