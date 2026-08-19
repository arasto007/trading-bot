"""Probability calibration analysis — reliability, Brier score, ECE."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.training import load_model
from tradingbot.ml.validation._utils import write_json_report


@dataclass
class CalibrationReport:
    model: str
    symbol: str
    timeframe: str
    split: str
    brier_score: float
    calibration_error: float
    reliability_curve: list[dict[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _reliability_curve(
    y_true: np.ndarray,
    proba_pos: np.ndarray,
    n_bins: int = 10,
) -> tuple[list[dict[str, float]], float]:
    """Return binned reliability data and expected calibration error."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    curve: list[dict[str, float]] = []
    ece = 0.0
    n = len(y_true)
    for i in range(n_bins):
        low, high = bins[i], bins[i + 1]
        if i == n_bins - 1:
            mask = (proba_pos >= low) & (proba_pos <= high)
        else:
            mask = (proba_pos >= low) & (proba_pos < high)
        count = int(mask.sum())
        if count == 0:
            continue
        mean_pred = float(proba_pos[mask].mean())
        mean_actual = float(y_true[mask].mean())
        curve.append(
            {
                "bin_low": round(float(low), 4),
                "bin_high": round(float(high), 4),
                "mean_predicted": round(mean_pred, 4),
                "mean_actual": round(mean_actual, 4),
                "count": count,
            }
        )
        ece += abs(mean_pred - mean_actual) * (count / n)
    return curve, round(float(ece), 4)


def run_calibration(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    split: str = "validation",
    n_bins: int = 10,
    save: bool = True,
) -> CalibrationReport:
    """Analyze calibration for logistic, xgboost, or lightgbm models."""
    splits = load_dataset_splits(symbol, timeframe, base_dir)
    split_map = {
        "train": (splits.X_train, splits.y_train),
        "validation": (splits.X_val, splits.y_val),
        "test": (splits.X_test, splits.y_test),
    }
    if split not in split_map:
        raise ValueError(f"Unknown split: {split}")
    X, y = split_map[split]
    if X.empty:
        raise ValueError(f"Split '{split}' is empty")

    model = load_model(model_name, base_dir)
    proba = model.predict_proba(X)
    y_true = np.asarray(y).astype(int)
    proba_pos = proba[:, 1]

    curve, ece = _reliability_curve(y_true, proba_pos, n_bins=n_bins)
    brier = round(float(brier_score_loss(y_true, proba_pos)), 4)

    report = CalibrationReport(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        split=split,
        brier_score=brier,
        calibration_error=ece,
        reliability_curve=curve,
    )

    if save:
        path = reports_dir(base_dir) / "calibration_report.json"
        write_json_report(path, report.to_dict())

    return report
