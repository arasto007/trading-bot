"""Walk-forward validation — expanding train windows, chronological only."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.training import create_model
from tradingbot.ml.validation._utils import (
    classification_metrics,
    load_resolved_dataset,
    stability_score,
    timestamp_bounds,
    write_json_report,
)


@dataclass
class WalkForwardWindow:
    window_index: int
    train_start: str | None
    train_end: str | None
    validation_start: str | None
    validation_end: str | None
    train_rows: int
    validation_rows: int
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class WalkForwardReport:
    model: str
    symbol: str
    timeframe: str
    windows: list[WalkForwardWindow] = field(default_factory=list)
    average_metrics: dict[str, float] = field(default_factory=dict)
    stability_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_windows(
    n_rows: int,
    *,
    min_train_rows: int = 60,
    val_window_rows: int = 30,
) -> list[tuple[slice, slice]]:
    """Build expanding train + rolling validation slices (chronological)."""
    folds: list[tuple[slice, slice]] = []
    train_end = min_train_rows
    while train_end + val_window_rows <= n_rows:
        val_start = train_end
        val_end = train_end + val_window_rows
        folds.append((slice(0, train_end), slice(val_start, val_end)))
        train_end = val_end
    return folds


def run_walk_forward(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    model_params: dict[str, Any] | None = None,
    min_train_rows: int = 60,
    val_window_rows: int = 30,
    save: bool = True,
) -> WalkForwardReport:
    """
    Expanding-window walk-forward validation.

  Train: [start → t], Validation: [t → t+w], then expand train through prior validation.
    Never shuffles data.
    """
    df, feature_cols = load_resolved_dataset(symbol, timeframe, base_dir)
    folds = _default_windows(
        len(df),
        min_train_rows=min_train_rows,
        val_window_rows=val_window_rows,
    )
    if not folds:
        raise ValueError("Insufficient rows for walk-forward validation")

    windows: list[WalkForwardWindow] = []
    metric_keys = ("roc_auc", "pr_auc", "precision", "recall", "f1", "expected_R")

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

        t_start, t_end = timestamp_bounds(train_df)
        v_start, v_end = timestamp_bounds(val_df)
        windows.append(
            WalkForwardWindow(
                window_index=idx,
                train_start=t_start,
                train_end=t_end,
                validation_start=v_start,
                validation_end=v_end,
                train_rows=len(train_df),
                validation_rows=len(val_df),
                metrics=metrics,
            )
        )

    average_metrics: dict[str, float] = {}
    for key in metric_keys:
        vals = [w.metrics.get(key, 0.0) for w in windows]
        average_metrics[key] = round(float(np.mean(vals)), 4) if vals else 0.0

    stab = stability_score([w.metrics.get("expected_R", 0.0) for w in windows])

    report = WalkForwardReport(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        windows=windows,
        average_metrics=average_metrics,
        stability_score=stab,
    )

    if save:
        path = reports_dir(base_dir) / f"walk_forward_{model_name.lower()}.json"
        write_json_report(path, report.to_dict())

    return report
