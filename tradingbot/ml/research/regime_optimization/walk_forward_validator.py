"""Phase 9.6 — walk-forward validation (chronological, no shuffle)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import walk_forward_report_path
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.regime_optimization.regime_utils import metrics_block
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.training.model_factory import DEFAULT_SEED


def _year_mask(ts: pd.Series, start: int, end: int) -> np.ndarray:
    years = pd.to_datetime(ts, utc=True).dt.year
    return ((years >= start) & (years <= end)).to_numpy()


def build_walk_forward_windows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Build chronological walk-forward windows from dataset timestamps."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    years = sorted(ts.dt.year.unique().tolist())
    windows: list[dict[str, Any]] = []

    if years and min(years) <= 2021 and max(years) >= 2025:
        windows.append(
            {
                "window_id": "window_1",
                "train_years": [2021, 2023],
                "validation_years": [2024, 2024],
                "test_years": [2025, max(years)],
            }
        )
        if max(years) >= 2026:
            windows.append(
                {
                    "window_id": "window_2",
                    "train_years": [2021, 2024],
                    "validation_years": [2025, 2025],
                    "test_years": [2026, 2026],
                }
            )

    if len(windows) < 2 and len(years) >= 3:
        y0, y1, y2 = years[0], years[len(years) // 2], years[-1]
        windows.append(
            {
                "window_id": "window_adaptive_1",
                "train_years": [y0, years[max(0, len(years) // 3 - 1)]],
                "validation_years": [years[len(years) // 3], years[min(len(years) - 1, len(years) // 3 + 1)]],
                "test_years": [y2, y2],
            }
        )

    if len(years) >= 4:
        windows.append(
            {
                "window_id": "window_rolling",
                "train_years": [years[0], years[-3]],
                "validation_years": [years[-2], years[-2]],
                "test_years": [years[-1], years[-1]],
            }
        )

    if not windows:
        n = len(df)
        cut1 = int(n * 0.6)
        cut2 = int(n * 0.8)
        windows.append(
            {
                "window_id": "window_index",
                "index_splits": {"train_end": cut1, "val_end": cut2},
            }
        )
    return windows


def _partition_window(df: pd.DataFrame, window: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if "index_splits" in window:
        idx = window["index_splits"]
        ordered = df.sort_values("timestamp").reset_index(drop=True)
        train = ordered.iloc[: idx["train_end"]]
        val = ordered.iloc[idx["train_end"] : idx["val_end"]]
        test = ordered.iloc[idx["val_end"] :]
        return train, val, test

    ts = df["timestamp"]
    tr_s, tr_e = window["train_years"]
    va_s, va_e = window["validation_years"]
    te_s, te_e = window["test_years"]
    train = df.loc[_year_mask(ts, tr_s, tr_e)]
    val = df.loc[_year_mask(ts, va_s, va_e)]
    test = df.loc[_year_mask(ts, te_s, te_e)]
    return train, val, test


def run_walk_forward_validation(
    df: pd.DataFrame,
    feature_cols: list[str],
    *,
    seed: int = DEFAULT_SEED,
    model_name: str = "lightgbm",
    hyperparameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk-forward train/evaluate without shuffle."""
    np.random.seed(seed)
    windows = build_walk_forward_windows(df)
    results: list[dict[str, Any]] = []

    for window in windows:
        train, val, test = _partition_window(df, window)
        if min(len(train), len(val), len(test)) < 15:
            results.append({"window_id": window["window_id"], "skipped": True, "reason": "insufficient_rows"})
            continue
        cols = [c for c in feature_cols if c in train.columns]
        if not cols:
            cols = [c for c in feature_names() if c in train.columns][:15]

        scaler = StandardScaler()
        X_tr = train.loc[:, cols].astype(np.float64)
        y_tr = train["label"].astype(int).to_numpy()
        scaler.fit(X_tr.values)
        X_va = scaler.transform(val.loc[:, cols].astype(np.float64).values)
        X_te = scaler.transform(test.loc[:, cols].astype(np.float64).values)
        y_va = val["label"].astype(int).to_numpy()
        y_te = test["label"].astype(int).to_numpy()

        model = create_research_model(model_name, seed, hyperparameters or {})
        model.fit(scaler.transform(X_tr.values), y_tr, eval_set=(X_va, y_va))
        val_pred = model.predict(X_va)
        test_pred = model.predict(X_te)
        val_proba = model.predict_proba(X_va)
        test_proba = model.predict_proba(X_te)

        val_metrics = metrics_block(y_va, val_pred, val_proba)
        test_metrics = metrics_block(y_te, test_pred, test_proba)
        results.append(
            {
                "window_id": window["window_id"],
                "train_rows": len(train),
                "validation_rows": len(val),
                "test_rows": len(test),
                "validation": val_metrics,
                "test": test_metrics,
                "shuffle": False,
            }
        )

    test_aucs = [
        r["test"]["classification"]["roc_auc"]
        for r in results
        if not r.get("skipped") and "test" in r
    ]
    expectancies = [
        r["test"]["trading"]["expectancy"]
        for r in results
        if not r.get("skipped") and "test" in r
    ]
    return {
        "phase": "9.6",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "windows": results,
        "mean_test_roc_auc": round(float(np.mean(test_aucs)), 4) if test_aucs else 0.0,
        "mean_test_expectancy": round(float(np.mean(expectancies)), 4) if expectancies else 0.0,
        "chronological": True,
        "shuffle": False,
    }


def save_walk_forward_report(
    df: pd.DataFrame,
    feature_cols: list[str],
    base_dir: str | Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> Path:
    report = run_walk_forward_validation(df, feature_cols, seed=seed)
    path = walk_forward_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
