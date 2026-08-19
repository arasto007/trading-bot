"""Model evaluation — classification and trading-oriented metrics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from tradingbot.ml.models.artifacts import evaluation_report_path, reports_dir
from tradingbot.ml.models.base import BaseModel


@dataclass
class EvaluationResult:
    model: str
    symbol: str
    timeframe: str
    split: str
    metrics: dict[str, float] = field(default_factory=dict)
    trading: dict[str, float] = field(default_factory=dict)
    simulated: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_r_from_proba(proba: np.ndarray) -> np.ndarray:
    """
    Expected R per sample: win_prob * 2R - loss_prob * 1R.

    proba columns: [P(class=0), P(class=1)]
    """
    if proba.ndim != 2 or proba.shape[1] < 2:
        raise ValueError("predict_proba must return shape (n, 2)")
    loss_prob = proba[:, 0]
    win_prob = proba[:, 1]
    return win_prob * 2.0 - loss_prob * 1.0


class ModelEvaluator:
    """Evaluate baseline models on held-out splits."""

    def evaluate(
        self,
        model: BaseModel,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
        split: str = "test",
    ) -> EvaluationResult:
        y_true = np.asarray(y).astype(int)
        y_pred = model.predict(X)
        proba = model.predict_proba(X)

        metrics: dict[str, float] = {}
        metrics["accuracy"] = round(float(accuracy_score(y_true, y_pred)), 4)
        metrics["precision"] = round(float(precision_score(y_true, y_pred, zero_division=0)), 4)
        metrics["recall"] = round(float(recall_score(y_true, y_pred, zero_division=0)), 4)
        metrics["f1"] = round(float(f1_score(y_true, y_pred, zero_division=0)), 4)

        if len(np.unique(y_true)) > 1:
            metrics["roc_auc"] = round(float(roc_auc_score(y_true, proba[:, 1])), 4)
            metrics["pr_auc"] = round(float(average_precision_score(y_true, proba[:, 1])), 4)
        else:
            metrics["roc_auc"] = 0.0
            metrics["pr_auc"] = 0.0

        exp_r = expected_r_from_proba(proba)
        trading = {
            "expected_R": round(float(exp_r.mean()), 4),
            "predicted_winrate": round(float((y_pred == 1).mean()), 4),
            "average_predicted_probability": round(float(proba[:, 1].mean()), 4),
        }

        simulated = self._simulate_tp_sl(y_true, y_pred)

        return EvaluationResult(
            model=model.name,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            split=split,
            metrics=metrics,
            trading=trading,
            simulated=simulated,
        )

    @staticmethod
    def _simulate_tp_sl(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
        """Simulate TP/SL outcomes when taking predicted class=1 trades only."""
        take = y_pred == 1
        if not take.any():
            return {"trades_taken": 0.0, "simulated_winrate": 0.0, "simulated_expected_R": 0.0}
        taken_labels = y_true[take]
        wins = (taken_labels == 1).sum()
        losses = (taken_labels == 0).sum()
        n = len(taken_labels)
        winrate = wins / n if n else 0.0
        exp_r = (wins * 2.0 - losses * 1.0) / n if n else 0.0
        return {
            "trades_taken": float(n),
            "simulated_winrate": round(float(winrate), 4),
            "simulated_expected_R": round(float(exp_r), 4),
        }

    def save_report(
        self,
        result: EvaluationResult,
        base_dir: str | Path | None = None,
    ) -> Path:
        reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
        path = evaluation_report_path(result.symbol, result.timeframe, result.model, base_dir)
        path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path
