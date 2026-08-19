"""Phase 9.9 — isolated window validation using regularized models."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.robustness_optimizer.model_regularization import (
    ModelCandidateConfig,
    create_regularized_model,
)
from tradingbot.ml.research.robustness_optimizer.probability_selection_gate import (
    compute_window_probability_audit,
)
from tradingbot.ml.research.walk_forward.model_validator import (
    _ml_metrics,
    _simulate_trades,
    apply_phase97_filters,
)
from tradingbot.ml.research.walk_forward.window_manager import WalkForwardWindow, assert_no_overlap
from tradingbot.ml.training.model_factory import DEFAULT_SEED


def validate_window_candidate(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    window: WalkForwardWindow,
    *,
    candidate: ModelCandidateConfig,
    feature_cols: list[str],
    seed: int = DEFAULT_SEED,
    regime: str = "RANGE",
    event_scheme: str = "A_all_events",
) -> dict[str, Any]:
    """Train regularized candidate on train only; evaluate on validation."""
    assert_no_overlap(train_df, val_df)
    train_f = apply_phase97_filters(train_df, regime=regime, event_scheme=event_scheme)
    val_f = apply_phase97_filters(val_df, regime=regime, event_scheme=event_scheme)

    if len(train_f) < 20 or len(val_f) < 5:
        return {
            "window_id": window.window_id,
            "skipped": True,
            "reason": "insufficient_rows_after_filter",
            "train_rows": len(train_f),
            "validation_rows": len(val_f),
        }

    cols = [c for c in feature_cols if c in train_f.columns and c in val_f.columns]
    if not cols:
        return {"window_id": window.window_id, "skipped": True, "reason": "no_features"}

    scaler = StandardScaler()
    X_tr = train_f.loc[:, cols].astype(np.float64).values
    y_tr = train_f["label"].astype(int).to_numpy()
    scaler.fit(X_tr)

    X_va = scaler.transform(val_f.loc[:, cols].astype(np.float64).values)
    y_va = val_f["label"].astype(int).to_numpy()

    model = create_regularized_model(candidate, seed)
    model.fit(scaler.transform(X_tr), y_tr)

    train_proba = model.predict_proba(scaler.transform(X_tr))
    train_pred = model.predict(scaler.transform(X_tr))
    train_ml = _ml_metrics(y_tr, train_pred, train_proba)

    val_proba = model.predict_proba(X_va)
    val_pred = model.predict(X_va)
    val_ml = _ml_metrics(y_va, val_pred, val_proba)
    p_win = val_proba[:, 1]
    probability_audit = compute_window_probability_audit(p_win)
    trading = _simulate_trades(val_f.reset_index(drop=True), val_proba)

    train_val_gap = round(train_ml["roc_auc"] - val_ml["roc_auc"], 4)
    performance_degradation = 0.0
    if train_ml["roc_auc"] > 0:
        performance_degradation = round(max(0.0, train_val_gap / train_ml["roc_auc"]), 4)

    return {
        "window_id": window.window_id,
        "skipped": False,
        "train_start": window.train_start,
        "train_end": window.train_end,
        "validation_start": window.validation_start,
        "validation_end": window.validation_end,
        "train_rows": len(train_f),
        "validation_rows": len(val_f),
        "shuffle": False,
        "scaler_fit_on": "train_only",
        **val_ml,
        **trading,
        "probability_audit": probability_audit,
        "train_roc_auc": train_ml["roc_auc"],
        "train_val_auc_gap": train_val_gap,
        "performance_degradation": performance_degradation,
    }
