"""Phase 15K — feature impact on probability ceiling."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase15k.data_access import Phase15KContext


def _permutation_importance_proxy(
    bundle,
    row_features: np.ndarray,
    feature_order: list[str],
    baseline_prob: float,
) -> dict[str, float]:
    importances: dict[str, float] = {}
    for j, feat in enumerate(feature_order):
        perturbed = row_features.copy()
        perturbed[j] = 0.0
        feats = {feature_order[k]: float(perturbed[k]) for k in range(len(feature_order))}
        p = float(bundle.predict_proba(feats))
        importances[feat] = abs(baseline_prob - p)
    return importances


def analyze_feature_ceiling_impact(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    days: int = 365,
    stride: int = 15,
    symbol: str = "XAUUSD",
    ctx: Phase15KContext | None = None,
) -> dict[str, Any]:
    if ctx is None:
        ctx = Phase15KContext.build(
            candles, dataset, base_dir=base_dir, symbol=symbol, days=days, stride=stride,
        )
    bundle = ctx.bundle
    live_rows = ctx.live_rows
    train_samples = ctx.train_samples
    if not live_rows:
        return {"phase": "15K", "features": [], "ceiling_breaking_features": []}

    from tradingbot.ml.research.phase15k.config import pearson_corr, psi_score

    probs = np.array([r["probability"] for r in live_rows])
    live_max_idx = int(np.argmax(probs))
    max_row = live_rows[live_max_idx]
    feat_order = bundle.feature_order

    perm_at_max = _permutation_importance_proxy(
        bundle,
        np.array([max_row["features"][f] for f in feat_order]),
        feat_order,
        float(max_row["probability"]),
    )

    features_report: list[dict[str, Any]] = []
    ceiling_breakers: list[str] = []
    for feat in feat_order:
        live_vals = np.array([r["features"][feat] for r in live_rows])
        train_vals = train_samples[feat].dropna().astype(float).values if feat in train_samples.columns else live_vals
        psi = psi_score(train_vals, live_vals)
        corr_prob = pearson_corr(live_vals, probs)
        corr_ceiling = abs(corr_prob) * (1.0 - float(np.max(probs)))
        shap_proxy = float(np.mean([
            abs(r["probability"] - float(bundle.predict_proba({**{f: r["features"][f] for f in feat_order}, feat: 0.0})))
            for r in live_rows[: min(25, len(live_rows))]
        ]))
        is_breaker = shap_proxy > 0.01 and abs(corr_prob) > 0.15
        if is_breaker:
            ceiling_breakers.append(feat)
        features_report.append({
            "feature": feat,
            "shap_proxy_mean": round(shap_proxy, 6),
            "correlation_with_probability": round(corr_prob, 6),
            "psi": round(psi, 6),
            "psi_ceiling_correlation": round(corr_ceiling, 6),
            "permutation_at_max_bar": round(perm_at_max.get(feat, 0.0), 6),
            "ceiling_breaking": is_breaker,
        })

    features_report.sort(key=lambda x: x["shap_proxy_mean"], reverse=True)
    return {
        "phase": "15K",
        "features": features_report,
        "ceiling_breaking_features": ceiling_breakers,
        "max_probability_bar": {
            "timestamp": max_row["timestamp"],
            "probability": max_row["probability"],
            "top_permutation_features": sorted(perm_at_max.items(), key=lambda x: -x[1])[:3],
        },
    }
