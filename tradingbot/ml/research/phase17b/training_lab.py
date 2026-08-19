"""Phase 17B — chronological RF training lab."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.phase17b.config import (
    DEFAULT_SEED,
    RF_MAX_DEPTH,
    RF_MIN_SAMPLES_LEAF,
    RF_N_ESTIMATORS,
)
from tradingbot.ml.research.phase17b.dataset import chronological_split, extended_feature_columns
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.regime_router.config import WALK_FORWARD_YEARS


def create_research_rf(*, seed: int = DEFAULT_SEED) -> RandomForestClassifier:
    """Same hyperparameters as trend_rf_v40 — conservative, no aggressive tuning."""
    return RandomForestClassifier(
        n_estimators=RF_N_ESTIMATORS,
        max_depth=RF_MAX_DEPTH,
        min_samples_leaf=RF_MIN_SAMPLES_LEAF,
        random_state=seed,
        n_jobs=-1,
    )


def _year_series(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.year


def train_research_rf(
    samples: pd.DataFrame,
    *,
    seed: int = DEFAULT_SEED,
) -> tuple[ResearchRfModel, dict[str, Any]]:
    """
    Train on chronological train split; scaler fit on train only.
    TimeSeriesSplit + walk-forward reported; no shuffle.
    """
    feat_cols = [c for c in extended_feature_columns() if c in samples.columns]
    train, val, test = chronological_split(samples)

    X_train = train[feat_cols].astype(float)
    y_train = train["successful_trade"].astype(int).values
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)

    model = create_research_rf(seed=seed)
    model.fit(X_train_s, y_train)

    # TimeSeriesSplit on train portion only (no leakage into val/test).
    tscv = TimeSeriesSplit(n_splits=min(5, max(2, len(train) // 500)))
    cv_aucs: list[float] = []
    for tr_idx, te_idx in tscv.split(X_train_s):
        if len(tr_idx) < 50 or len(te_idx) < 10:
            continue
        fold_scaler = StandardScaler()
        X_tr = fold_scaler.fit_transform(X_train.iloc[tr_idx])
        X_te = fold_scaler.transform(X_train.iloc[te_idx])
        fold_model = create_research_rf(seed=seed)
        fold_model.fit(X_tr, y_train[tr_idx])
        proba = fold_model.predict_proba(X_te)[:, 1]
        y_te = y_train[te_idx]
        if len(np.unique(y_te)) > 1:
            from sklearn.metrics import roc_auc_score
            cv_aucs.append(float(roc_auc_score(y_te, proba)))

    # Walk-forward by year on full samples (chronological).
    wf_windows: list[dict[str, Any]] = []
    years = sorted(_year_series(samples["timestamp"]).unique())
    for year in years[-len(WALK_FORWARD_YEARS):]:
        ts = _year_series(samples["timestamp"])
        tr = samples[ts < year]
        te = samples[ts == year]
        if len(tr) < 100 or len(te) < 20:
            continue
        fs = StandardScaler()
        Xtr = fs.fit_transform(tr[feat_cols].astype(float))
        Xte = fs.transform(te[feat_cols].astype(float))
        ytr = tr["successful_trade"].astype(int).values
        yte = te["successful_trade"].astype(int).values
        fm = create_research_rf(seed=seed)
        fm.fit(Xtr, ytr)
        proba = fm.predict_proba(Xte)[:, 1]
        if len(np.unique(yte)) > 1:
            from sklearn.metrics import roc_auc_score
            auc = float(roc_auc_score(yte, proba))
        else:
            auc = 0.5
        wf_windows.append({"year": int(year), "train_rows": len(tr), "test_rows": len(te), "auc": round(auc, 4)})

    research = ResearchRfModel(
        model=model,
        scaler=scaler,
        feature_order=feat_cols,
        seed=seed,
        train_rows=len(train),
        metadata={
            "hyperparameters": {
                "n_estimators": RF_N_ESTIMATORS,
                "max_depth": RF_MAX_DEPTH,
                "min_samples_leaf": RF_MIN_SAMPLES_LEAF,
            },
            "train_rows": len(train),
            "val_rows": len(val),
            "test_rows": len(test),
            "conservative_tuning": True,
            "shuffled": False,
        },
    )

    training_report = {
        "phase": "17B",
        "model": "RandomForestClassifier",
        "seed": seed,
        "hyperparameters": research.metadata["hyperparameters"],
        "feature_count": len(feat_cols),
        "features": feat_cols,
        "train_rows": len(train),
        "val_rows": len(val),
        "test_rows": len(test),
        "timeseries_cv_splits": tscv.n_splits,
        "timeseries_cv_mean_auc": round(float(np.mean(cv_aucs)), 4) if cv_aucs else None,
        "walk_forward_windows": wf_windows,
        "walk_forward_mean_auc": round(float(np.mean([w["auc"] for w in wf_windows])), 4) if wf_windows else None,
        "scaler_fit_on": "train_only",
        "shuffled": False,
        "production_bundle_modified": False,
    }
    return research, training_report
