"""Shared helpers for offline validation (Phase 4.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.models.dataset_loader import (
    RESOLVED_LABELS,
    VALID_SPLITS,
    resolve_feature_columns,
)
from tradingbot.ml.models.evaluator import expected_r_from_proba


def load_resolved_dataset(
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Load resolved samples in chronological order (never shuffled)."""
    store = DatasetStore(base_dir)
    df = store.load(symbol, timeframe)
    if df is None or df.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    work = df[df["label"].isin(RESOLVED_LABELS)].copy()
    work = work[work["split"].isin(VALID_SPLITS)].copy()
    if "timestamp" in work.columns:
        work = work.sort_values("timestamp").reset_index(drop=True)

    feature_cols = resolve_feature_columns(work)
    if not feature_cols:
        raise ValueError("No feature columns found in dataset")
    return work, feature_cols


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    proba: np.ndarray,
) -> dict[str, float]:
    """Compute standard classification and expected_R metrics."""
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    metrics: dict[str, float] = {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = round(float(roc_auc_score(y_true, proba[:, 1])), 4)
        metrics["pr_auc"] = round(float(average_precision_score(y_true, proba[:, 1])), 4)
    else:
        metrics["roc_auc"] = 0.0
        metrics["pr_auc"] = 0.0

    exp_r = expected_r_from_proba(proba)
    metrics["expected_R"] = round(float(exp_r.mean()), 4)
    metrics["predicted_winrate"] = round(float((y_pred == 1).mean()), 4)
    return metrics


def stability_score(values: list[float]) -> float:
    """Higher is more stable (1 - coefficient of variation, clipped to [0, 1])."""
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if abs(mean) < 1e-9:
        return 1.0 if float(arr.std()) < 1e-9 else 0.0
    cv = float(arr.std()) / abs(mean)
    return round(max(0.0, min(1.0, 1.0 - cv)), 4)


def write_json_report(path: Path, payload: dict[str, Any]) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def timestamp_bounds(df: pd.DataFrame) -> tuple[str | None, str | None]:
    if "timestamp" not in df.columns or df.empty:
        return None, None
    ts = pd.to_datetime(df["timestamp"])
    return str(ts.min()), str(ts.max())
