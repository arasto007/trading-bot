"""Phase 16B — alignment PSI and z-score metrics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.feature_alignment.config import SHIFTED_FEATURES
from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
from tradingbot.ml.feature_alignment.feature_statistics import load_training_statistics
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _psi(expected: np.ndarray, actual: np.ndarray, *, bins: int = 10) -> float:
    eps = 1e-6
    if len(expected) < 2 or len(actual) < 2:
        return 0.0
    lo = min(float(np.min(expected)), float(np.min(actual)))
    hi = max(float(np.max(expected)), float(np.max(actual))) + eps
    br = np.linspace(lo, hi, bins)
    eh, _ = np.histogram(expected, bins=br)
    ah, _ = np.histogram(actual, bins=br)
    ep = eh / max(eh.sum(), 1) + eps
    ap = ah / max(ah.sum(), 1) + eps
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def alignment_metrics_for_window(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int,
    stride: int,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features

    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    aligner = build_distribution_aligner(base_dir=base_dir, symbol=symbol)
    train_stats = load_training_statistics(base_dir=base_dir, symbol=symbol)
    train_frame = build_ml_features(candles)
    scaler = bundle.scaler
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    raw_by_feat: dict[str, list[float]] = {f: [] for f in SHIFTED_FEATURES}
    aligned_by_feat: dict[str, list[float]] = {f: [] for f in SHIFTED_FEATURES}
    z_scores: dict[str, list[float]] = {f: [] for f in SHIFTED_FEATURES}

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        aligned = aligner.align({f: float(row.get(f, 0.0)) for f in SHIFTED_FEATURES})
        for f in SHIFTED_FEATURES:
            raw = float(row.get(f, 0.0))
            raw_by_feat[f].append(raw)
            aligned_by_feat[f].append(float(aligned[f]))
            j = list(bundle.feature_order).index(f) if f in bundle.feature_order else -1
            if j >= 0:
                mu, sd = float(scaler.mean_[j]), float(scaler.scale_[j])
                z_scores[f].append(abs((raw - mu) / max(sd, 1e-12)))

    per_feature = []
    for f in SHIFTED_FEATURES:
        train_vals = train_frame[f].dropna().astype(float).values if f in train_frame.columns else train_stats[f].quantiles
        # subsample training for PSI speed
        if len(train_vals) > 5000:
            train_vals = train_vals[:: max(1, len(train_vals) // 5000)]
        raw = np.array(raw_by_feat[f])
        al = np.array(aligned_by_feat[f])
        per_feature.append({
            "feature": f,
            "psi_before": round(_psi(train_vals, raw), 6),
            "psi_after": round(_psi(train_vals, al), 6),
            "mean_z_before": round(float(np.mean(z_scores[f])), 4) if z_scores[f] else 0.0,
        })

    drift_index = float(np.mean([x["psi_after"] for x in per_feature])) if per_feature else 0.0
    return {
        "days": days,
        "stride": stride,
        "trend_bars": len(raw_by_feat[SHIFTED_FEATURES[0]]),
        "per_feature": per_feature,
        "drift_index": round(drift_index, 6),
        "max_psi_after": round(max((x["psi_after"] for x in per_feature), default=0.0), 6),
    }
