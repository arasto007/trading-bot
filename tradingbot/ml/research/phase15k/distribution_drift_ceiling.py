"""Phase 15K — train vs live distribution drift vs ceiling."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from tradingbot.ml.research.phase15k.data_access import Phase15KContext, sample_training_probabilities


def analyze_distribution_drift_ceiling(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    days: int = 365,
    stride: int = 10,
    ctx: Phase15KContext | None = None,
) -> dict[str, Any]:
    if ctx is None:
        ctx = Phase15KContext.build(
            candles, dataset, base_dir=base_dir, symbol=symbol, days=days, stride=stride,
        )
    bundle = ctx.bundle
    live_rows = ctx.live_rows
    train_samples = ctx.train_samples
    probs = np.array([r["probability"] for r in live_rows]) if live_rows else np.array([])

    from tradingbot.ml.research.phase15k.config import DRIFT_CEILING_CORR, PSI_CRITICAL, dist_stats, pearson_corr, psi_score

    per_feature: list[dict[str, Any]] = []
    drift_critical: list[str] = []
    for feat in bundle.feature_order:
        if feat not in train_samples.columns:
            continue
        train_vals = train_samples[feat].dropna().astype(float).values
        live_vals = np.array([r["features"][feat] for r in live_rows]) if live_rows else np.array([])
        ks_stat, ks_p = stats.ks_2samp(train_vals, live_vals) if len(live_vals) > 1 else (0.0, 1.0)
        psi = psi_score(train_vals, live_vals)
        corr_ceiling = abs(pearson_corr(live_vals, probs)) if len(probs) else 0.0
        critical = psi > PSI_CRITICAL and corr_ceiling > DRIFT_CEILING_CORR
        if critical:
            drift_critical.append(feat)
        per_feature.append({
            "feature": feat,
            "ks_statistic": round(float(ks_stat), 6),
            "ks_pvalue": round(float(ks_p), 6),
            "psi": round(psi, 6),
            "training_mean": round(float(np.mean(train_vals)), 6),
            "live_mean": round(float(np.mean(live_vals)), 6) if len(live_vals) else 0.0,
            "training_std": round(float(np.std(train_vals)), 6),
            "live_std": round(float(np.std(live_vals)), 6) if len(live_vals) else 0.0,
            "correlation_with_ceiling": round(corr_ceiling, 6),
            "drift_critical": critical,
        })

    interactions: list[dict[str, Any]] = []
    if len(bundle.feature_order) >= 2:
        f0, f1 = bundle.feature_order[0], bundle.feature_order[1]
        if live_rows:
            joint_live = np.array([
                live_rows[i]["features"][f0] * live_rows[i]["features"][f1]
                for i in range(len(live_rows))
            ])
            joint_train = (train_samples[f0].astype(float) * train_samples[f1].astype(float)).values
            interactions.append({
                "pair": [f0, f1],
                "joint_psi": round(psi_score(joint_train, joint_live), 6),
                "joint_ks": round(float(stats.ks_2samp(joint_train, joint_live).statistic), 6),
            })

    return {
        "phase": "15K",
        "per_feature": per_feature,
        "drift_critical_features": drift_critical,
        "joint_interactions_top": interactions,
        "histogram_overlay": {
            "training_probability": dist_stats(sample_training_probabilities(bundle, train_samples)),
            "live_probability": dist_stats(list(probs)),
        },
        "flags": ["DRIFT_CRITICAL"] if drift_critical else [],
    }
