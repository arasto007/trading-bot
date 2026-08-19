"""Phase 17B — TREND dataset builder (chronological, no shuffle)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase17b.config import LABEL_KEY, TOP5_FEATURES
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features, formulas_report
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels


def extended_feature_columns() -> tuple[str, ...]:
    return tuple(TREND_ML_FEATURE_COLUMNS) + tuple(TOP5_FEATURES)


def _chronological_window(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    """Last N days only — chronological, no shuffle."""
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles

    return prepare_calibration_candles(candles, days=days)


def build_trend_dataset(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    train_days: int | None = None,
) -> pd.DataFrame:
    """Rebuild TREND labeled dataset with existing + top5 features."""
    from tradingbot.ml.research.phase17b.config import DEFAULT_TRAIN_DAYS

    window = _chronological_window(candles, train_days or DEFAULT_TRAIN_DAYS)
    frame = build_ml_features(window)
    # Attach top5 using regime labels without leaving string columns for float coercion.
    regimes = attach_regime_labels(frame)
    frame_for_features = frame.copy()
    frame_for_features["regime"] = regimes.values
    enriched = attach_top5_features(frame_for_features)
    # build_labeled_samples float-coerces all non-timestamp columns — drop string regime.
    label_frame = enriched.drop(columns=["regime"], errors="ignore")
    samples = build_labeled_samples(
        label_frame, symbol=symbol, rule_fn=evaluate_variant_a, label_key=LABEL_KEY,
    )
    feat_cols = extended_feature_columns()
    keep = ["timestamp", "direction", "regime", "successful_trade", *feat_cols]
    for c in feat_cols:
        if c not in samples.columns:
            samples[c] = 0.0
    return samples[keep].sort_values("timestamp").reset_index(drop=True)


def chronological_split(
    samples: pd.DataFrame,
    *,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological split — NO shuffle."""
    n = len(samples)
    if n == 0:
        empty = samples.copy()
        return empty, empty, empty
    t_end = int(n * train_ratio)
    v_end = int(n * (train_ratio + val_ratio))
    train = samples.iloc[:t_end].copy()
    val = samples.iloc[t_end:v_end].copy()
    test = samples.iloc[v_end:].copy()
    return train, val, test


def _dist_stats(series: pd.Series) -> dict[str, float]:
    s = series.dropna().astype(float)
    if s.empty:
        return {"count": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": int(len(s)),
        "mean": round(float(s.mean()), 6),
        "std": round(float(s.std()), 6),
        "min": round(float(s.min()), 6),
        "max": round(float(s.max()), 6),
    }


def build_dataset_report(samples: pd.DataFrame, *, train_days: int | None = None) -> dict[str, Any]:
    from tradingbot.ml.research.phase17b.config import DEFAULT_TRAIN_DAYS

    train, val, test = chronological_split(samples)
    pos = int(samples["successful_trade"].sum()) if not samples.empty else 0
    neg = len(samples) - pos
    missing = {c: int(samples[c].isna().sum()) for c in extended_feature_columns() if c in samples.columns}
    return {
        "phase": "17B",
        "rows_total": len(samples),
        "rows_train": len(train),
        "rows_val": len(val),
        "rows_test": len(test),
        "train_window_days": train_days or DEFAULT_TRAIN_DAYS,
        "class_balance": {
            "positive": pos,
            "negative": neg,
            "positive_rate": round(pos / max(len(samples), 1), 6),
        },
        "missing_values": missing,
        "missing_total": sum(missing.values()),
        "label_key": LABEL_KEY,
        "chronological_split": True,
        "shuffled": False,
        "feature_columns": list(extended_feature_columns()),
    }


def build_feature_report(samples: pd.DataFrame) -> dict[str, Any]:
    distributions = {
        c: _dist_stats(samples[c]) for c in extended_feature_columns() if c in samples.columns
    }
    top5_only = {c: distributions.get(c, {}) for c in TOP5_FEATURES}
    return {
        "phase": "17B",
        "formulas": formulas_report(),
        "top5_distributions": top5_only,
        "all_distributions": distributions,
    }
