"""Phase 22L — Step 5: range model input quality on Dataset A window."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range


def audit_range_input_quality(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    max_bars: int = 5000,
    stride: int = 5,
    warmup: int = 300,
) -> dict[str, Any]:
    from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
    from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter

    bundle = load_phase9_9_bundle(build_if_missing=False)
    range_inner = RangeEngineAdapter.load(symbol="XAUUSD")
    feature_order = list(bundle.feature_order)

    wdf = candles.copy()
    if not isinstance(wdf.index, pd.DatetimeIndex):
        wdf.index = pd.to_datetime(wdf.index, utc=True)
    wdf = wdf.reset_index()
    tcol = "timestamp" if "timestamp" in wdf.columns else wdf.columns[0]
    wdf = wdf.rename(columns={tcol: "timestamp"})
    wdf["timestamp"] = pd.to_datetime(wdf["timestamp"], utc=True)
    if len(wdf) > max_bars:
        wdf = wdf.iloc[-max_bars:]

    ds = dataset.copy()
    ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)

    probs: list[float] = []
    feat_matrix: list[list[float]] = []

    for i in range(warmup, len(wdf), max(1, stride)):
        window = wdf.iloc[: i + 1]
        unified = build_unified_frame(window.tail(300), ds)
        row = unified.iloc[-1]
        mapped = row_for_phase99_range(row)
        feats = range_inner._features_from_row(mapped)
        if feats is None:
            continue
        prob = bundle.predict_proba(feats)
        probs.append(prob)
        feat_matrix.append([float(feats.get(f, 0.0)) for f in feature_order])

    arr = np.array(probs) if probs else np.array([0.5])
    X = np.array(feat_matrix) if feat_matrix else np.zeros((0, len(feature_order)))

    feat_stats: dict[str, Any] = {}
    dead: list[str] = []
    flat: list[str] = []
    for j, name in enumerate(feature_order):
        if X.size == 0:
            feat_stats[name] = {"variance": 0.0, "zero_pct": 100.0}
            dead.append(name)
            continue
        col = X[:, j]
        var = float(np.var(col))
        zero_pct = float(np.mean(np.abs(col) < 1e-9)) * 100
        feat_stats[name] = {
            "mean": round(float(np.mean(col)), 6),
            "std": round(float(np.std(col)), 6),
            "variance": round(var, 8),
            "zero_pct": round(zero_pct, 2),
            "unique": int(len(np.unique(np.round(col, 6)))),
            "min": round(float(np.min(col)), 6),
            "max": round(float(np.max(col)), 6),
        }
        if var < 1e-12:
            dead.append(name)
        if zero_pct > 95.0:
            flat.append(name)

    hist_bins = [0.0, 0.35, 0.45, 0.55, 0.65, 1.0]
    hist, _ = np.histogram(arr, bins=hist_bins)
    histogram = {
        f"{hist_bins[k]:.2f}-{hist_bins[k+1]:.2f}": int(hist[k]) for k in range(len(hist))
    }

    corr: dict[str, float] = {}
    if X.shape[0] > 10 and X.shape[1] >= 2:
        c = np.corrcoef(X.T)
        for a in range(len(feature_order)):
            for b in range(a + 1, len(feature_order)):
                corr[f"{feature_order[a]}|{feature_order[b]}"] = round(float(c[a, b]), 4)

    return {
        "phase": "22L",
        "step": 5,
        "bars_evaluated": len(probs),
        "feature_order": feature_order,
        "probability_stats": {
            "mean": round(float(arr.mean()), 4),
            "std": round(float(arr.std()), 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "median": round(float(np.median(arr)), 4),
        },
        "probability_histogram": histogram,
        "feature_stats": feat_stats,
        "dead_features": dead,
        "flat_features": flat,
        "feature_correlation": corr,
        "model_feature_importance_from_bundle": bundle.config.get("feature_importance") or bundle.config.get("coefficients"),
    }
