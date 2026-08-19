"""Time-series cross validation — expanding and blocked (no random KFold)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.training import create_model
from tradingbot.ml.validation._utils import (
    classification_metrics,
    load_resolved_dataset,
    write_json_report,
)

CVMode = Literal["expanding", "blocked"]


@dataclass
class CVFold:
    fold_index: int
    train_rows: int
    validation_rows: int
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class CrossValidationReport:
    model: str
    symbol: str
    timeframe: str
    mode: str
    folds: list[CVFold] = field(default_factory=list)
    average_metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _expanding_folds(n_rows: int, n_folds: int, min_train: int) -> list[tuple[slice, slice]]:
    """Chronological expanding-window folds."""
    if n_folds < 1:
        return []
    val_size = max(1, (n_rows - min_train) // n_folds)
    folds: list[tuple[slice, slice]] = []
    train_end = min_train
    for _ in range(n_folds):
        val_start = train_end
        val_end = min(val_start + val_size, n_rows)
        if val_end <= val_start:
            break
        folds.append((slice(0, val_start), slice(val_start, val_end)))
        train_end = val_end
    return folds


def _blocked_folds(
    n_rows: int,
    n_folds: int,
    train_block: int,
    val_block: int,
) -> list[tuple[slice, slice]]:
    """Blocked sliding-window CV (fixed train block, fixed val block)."""
    folds: list[tuple[slice, slice]] = []
    start = 0
    for _ in range(n_folds):
        train_start = start
        train_end = train_start + train_block
        val_start = train_end
        val_end = val_start + val_block
        if val_end > n_rows:
            break
        folds.append((slice(train_start, train_end), slice(val_start, val_end)))
        start += val_block
    return folds


def _run_folds(
    df: pd.DataFrame,
    feature_cols: list[str],
    folds: list[tuple[slice, slice]],
    model_name: str,
    model_params: dict[str, Any] | None,
) -> list[CVFold]:
    results: list[CVFold] = []
    for idx, (train_sl, val_sl) in enumerate(folds):
        train_df = df.iloc[train_sl]
        val_df = df.iloc[val_sl]
        X_train = train_df[feature_cols]
        y_train = train_df["label"].astype(int)
        X_val = val_df[feature_cols]
        y_val = val_df["label"].astype(int)

        model = create_model(model_name, model_params)
        model.fit(X_train, y_train, eval_set=(X_val, y_val))

        proba = model.predict_proba(X_val)
        y_pred = (proba[:, 1] >= 0.5).astype(int)
        metrics = classification_metrics(np.asarray(y_val), y_pred, proba)
        results.append(
            CVFold(
                fold_index=idx,
                train_rows=len(train_df),
                validation_rows=len(val_df),
                metrics=metrics,
            )
        )
    return results


def run_cross_validation(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    mode: CVMode = "expanding",
    base_dir: str | Path | None = None,
    model_params: dict[str, Any] | None = None,
    n_folds: int = 3,
    min_train_rows: int = 60,
    train_block: int = 60,
    val_block: int = 30,
    save: bool = True,
) -> CrossValidationReport:
    df, feature_cols = load_resolved_dataset(symbol, timeframe, base_dir)

    if mode == "expanding":
        folds = _expanding_folds(len(df), n_folds, min_train_rows)
    else:
        folds = _blocked_folds(len(df), n_folds, train_block, val_block)

    if not folds:
        raise ValueError(f"No {mode} CV folds could be constructed")

    cv_folds = _run_folds(df, feature_cols, folds, model_name, model_params)

    metric_keys = ("roc_auc", "pr_auc", "precision", "recall", "f1", "expected_R")
    average_metrics: dict[str, float] = {}
    for key in metric_keys:
        vals = [f.metrics.get(key, 0.0) for f in cv_folds]
        average_metrics[key] = round(float(np.mean(vals)), 4) if vals else 0.0

    report = CrossValidationReport(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        mode=mode,
        folds=cv_folds,
        average_metrics=average_metrics,
    )

    if save:
        path = reports_dir(base_dir) / "cross_validation_report.json"
        write_json_report(path, report.to_dict())

    return report
