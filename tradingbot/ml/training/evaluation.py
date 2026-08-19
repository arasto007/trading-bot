"""Classification and trading-aware metrics for Phase 8.6."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from tradingbot.ml.training.model_factory import TrainingModel

TP_R_MULTIPLE = 2.0
SL_R_MULTIPLE = 1.0


@dataclass
class EvaluationMetrics:
    model: str
    split: str
    classification: dict[str, float] = field(default_factory=dict)
    trading: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_r_from_proba(proba: np.ndarray) -> np.ndarray:
    """Expected R: win_prob * 2R - loss_prob * 1R."""
    if proba.ndim != 2 or proba.shape[1] < 2:
        raise ValueError("predict_proba must return shape (n, 2)")
    loss_prob = proba[:, 0]
    win_prob = proba[:, 1]
    return win_prob * TP_R_MULTIPLE - loss_prob * SL_R_MULTIPLE


def label_r_outcomes(y_true: np.ndarray) -> np.ndarray:
    """Map labels to R outcomes: TP=+2R, SL=-1R."""
    y = np.asarray(y_true).astype(int)
    outcomes = np.where(y == 1, TP_R_MULTIPLE, -SL_R_MULTIPLE)
    return outcomes.astype(np.float64)


def profit_factor(outcomes: np.ndarray) -> float:
    gains = outcomes[outcomes > 0].sum()
    losses = -outcomes[outcomes < 0].sum()
    if losses <= 0:
        return float(gains) if gains > 0 else 0.0
    return float(gains / losses)


def max_drawdown_proxy(outcomes: np.ndarray) -> float:
    """Label-based cumulative R drawdown proxy."""
    if len(outcomes) == 0:
        return 0.0
    equity = np.cumsum(outcomes)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    return float(drawdown.max())


class TrainingEvaluator:
    """Evaluate trained models on held-out splits."""

    def evaluate(
        self,
        model: TrainingModel,
        X: np.ndarray,
        y: np.ndarray,
        *,
        split: str = "test",
    ) -> EvaluationMetrics:
        y_true = np.asarray(y).astype(int)
        y_pred = model.predict(X)
        proba = model.predict_proba(X)

        classification: dict[str, float] = {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        }
        if len(np.unique(y_true)) > 1:
            classification["roc_auc"] = round(float(roc_auc_score(y_true, proba[:, 1])), 4)
        else:
            classification["roc_auc"] = 0.0

        cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
        classification["confusion_matrix"] = {
            "labels": [0, 1],
            "matrix": cm.tolist(),
        }

        outcomes = label_r_outcomes(y_true)
        win_rate = float((y_true == 1).mean()) if len(y_true) else 0.0
        expectancy = float(outcomes.mean()) if len(outcomes) else 0.0

        take = y_pred == 1
        tp_pred_rate = float((y_pred == 1).mean()) if len(y_pred) else 0.0
        sl_pred_rate = float((y_pred == 0).mean()) if len(y_pred) else 0.0
        signal_precision = float(precision_score(y_true, y_pred, pos_label=1, zero_division=0))

        if take.any():
            taken_outcomes = outcomes[take]
            sim_win_rate = float((y_true[take] == 1).mean())
            sim_expectancy = float(taken_outcomes.mean())
            sim_pf = round(profit_factor(taken_outcomes), 4)
            sim_mdd = round(max_drawdown_proxy(taken_outcomes), 4)
        else:
            sim_win_rate = 0.0
            sim_expectancy = 0.0
            sim_pf = 0.0
            sim_mdd = 0.0

        trading = {
            "win_rate": round(win_rate, 4),
            "expectancy_R": round(expectancy, 4),
            "expected_R_multiple": round(float(expected_r_from_proba(proba).mean()), 4),
            "profit_factor": round(profit_factor(outcomes), 4),
            "profit_factor_proxy": round(profit_factor(outcomes), 4),
            "max_drawdown_proxy": round(max_drawdown_proxy(outcomes), 4),
            "signal_precision": round(signal_precision, 4),
            "tp_prediction_rate": round(tp_pred_rate, 4),
            "sl_prediction_rate": round(sl_pred_rate, 4),
            "predicted_winrate": round(float((y_pred == 1).mean()), 4),
            "expected_R_from_proba": round(float(expected_r_from_proba(proba).mean()), 4),
            "simulated_win_rate": round(sim_win_rate, 4),
            "simulated_expectancy_R": round(sim_expectancy, 4),
            "simulated_profit_factor": sim_pf,
            "simulated_max_drawdown_proxy": sim_mdd,
        }

        return EvaluationMetrics(
            model=model.name,
            split=split,
            classification=classification,
            trading=trading,
        )
