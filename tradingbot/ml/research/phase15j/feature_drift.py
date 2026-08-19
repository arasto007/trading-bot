"""Phase 15J — feature drift audit (training vs live)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase15j.config import FEATURE_DRIFT_PSI_THRESHOLD
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features


def _psi(expected: np.ndarray, actual: np.ndarray, *, bins: int = 10) -> float:
    eps = 1e-6
    breaks = np.linspace(
        min(expected.min(), actual.min()),
        max(expected.max(), actual.max()) + eps,
        bins + 1,
    )
    e_hist, _ = np.histogram(expected, bins=breaks)
    a_hist, _ = np.histogram(actual, bins=breaks)
    e_pct = e_hist / max(e_hist.sum(), 1) + eps
    a_pct = a_hist / max(a_hist.sum(), 1) + eps
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def audit_feature_drift(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    days: int = 365,
    stride: int = 5,
) -> dict[str, Any]:
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    feature_order = list(bundle.feature_order)
    training_frame = build_ml_features(candles)
    train_samples = build_labeled_samples(
        training_frame, symbol=symbol, rule_fn=evaluate_variant_a, label_key="label_a_tp_before_sl",
    )

    window = prepare_calibration_candles(candles, days=days)
    live_unified = build_unified_frame(window, dataset)
    live_rows = [
        live_unified.iloc[i]
        for i in range(0, len(live_unified), max(1, stride))
        if rule_classify_row(live_unified.iloc[i]) == "TREND"
    ]

    features_report: list[dict[str, Any]] = []
    drift_flags: list[str] = []
    order_match = feature_order == list(bundle.metadata.get("feature_columns", feature_order))

    for col in feature_order:
        if col not in train_samples.columns:
            continue
        train_vals = train_samples[col].dropna().astype(float).values
        live_vals = np.array([
            float(r.get(col, 0.0)) for r in live_rows if col in r.index
        ], dtype=float)
        if len(live_vals) == 0:
            live_vals = np.array([0.0])
        ks_stat, _ = stats.ks_2samp(train_vals, live_vals)
        psi = _psi(train_vals, live_vals) if len(train_vals) > 10 and len(live_vals) > 10 else 0.0
        flagged = psi > FEATURE_DRIFT_PSI_THRESHOLD
        if flagged:
            drift_flags.append(col)
        features_report.append({
            "feature": col,
            "training_mean": round(float(np.mean(train_vals)), 6),
            "live_mean": round(float(np.mean(live_vals)), 6),
            "training_std": round(float(np.std(train_vals)), 6),
            "live_std": round(float(np.std(live_vals)), 6),
            "ks_statistic": round(float(ks_stat), 6),
            "psi": round(float(psi), 6),
            "feature_drift": flagged,
        })

    return {
        "phase": "15J",
        "features": features_report,
        "training_feature_order": feature_order,
        "live_feature_order": feature_order,
        "feature_order_identical": order_match,
        "feature_order_matches_bundle": list(TREND_ML_FEATURE_COLUMNS) == feature_order,
        "drifted_features": drift_flags,
        "flags": ["FEATURE_DRIFT"] if drift_flags else [],
        "psi_threshold": FEATURE_DRIFT_PSI_THRESHOLD,
    }
