"""Phase 16C — feature importance for rejected TREND bars (permutation / optional SHAP)."""

from __future__ import annotations

from typing import Any

import numpy as np


def _permutation_importance(
    bundle: Any,
    features: dict[str, float],
    baseline_prob: float,
) -> dict[str, float]:
    order = list(bundle.feature_order)
    importances: dict[str, float] = {}
    for feat in order:
        perturbed = dict(features)
        perturbed[feat] = 0.0
        p = float(bundle.predict_proba(perturbed))
        importances[feat] = abs(baseline_prob - p)
    return importances


def _try_shap_importance(bundle: Any, records: list[dict[str, Any]], *, max_rows: int = 200) -> dict[str, Any] | None:
    try:
        import shap  # type: ignore[import-untyped]
    except ImportError:
        return None

    order = list(bundle.feature_order)
    rows = records[:max_rows]
    if not rows:
        return None

    X = np.array([[r["features"][f] for f in order] for r in rows], dtype=float)
    inner = getattr(bundle.model, "estimator", bundle.model)
    if not hasattr(inner, "predict_proba"):
        return None

    explainer = shap.TreeExplainer(inner)
    sv = explainer.shap_values(X)
    if isinstance(sv, list):
        sv = sv[1]
    mean_abs = np.abs(sv).mean(axis=0)
    ranked = sorted(
        [{"feature": order[i], "mean_abs_shap": round(float(mean_abs[i]), 6)} for i in range(len(order))],
        key=lambda x: -x["mean_abs_shap"],
    )
    return {"method": "shap", "top_features": ranked, "sample_rows": len(rows)}


def analyze_feature_importance(
    records: list[dict[str, Any]],
    bundle: Any,
    *,
    max_permutation_rows: int = 100,
) -> dict[str, Any]:
    rejected = [r for r in records if not r.get("rf_pass")]
    if not rejected:
        return {"method": "none", "top_features": [], "rejected_bars": 0}

    # Aggregate permutation importance across rejected bars
    agg: dict[str, list[float]] = {f: [] for f in bundle.feature_order}
    for r in rejected[:max_permutation_rows]:
        imp = _permutation_importance(bundle, r["features"], r["probability"])
        for feat, v in imp.items():
            agg[feat].append(v)

    perm_ranked = sorted(
        [
            {
                "feature": feat,
                "mean_permutation_delta": round(float(np.mean(vals)), 6),
                "max_permutation_delta": round(float(np.max(vals)), 6),
            }
            for feat, vals in agg.items()
            if vals
        ],
        key=lambda x: -x["mean_permutation_delta"],
    )

    shap_result = _try_shap_importance(bundle, rejected)
    method = "shap+permutation" if shap_result else "permutation"

    # Features most correlated with low probability among rejected
    probs = np.array([r["probability"] for r in rejected])
    corr_features: list[dict[str, Any]] = []
    for feat in bundle.feature_order:
        vals = np.array([r["features"][feat] for r in rejected])
        if np.std(vals) < 1e-12:
            continue
        corr = float(np.corrcoef(vals, probs)[0, 1])
        corr_features.append({"feature": feat, "corr_with_prob": round(corr, 6)})
    corr_features.sort(key=lambda x: -abs(x["corr_with_prob"]))

    return {
        "method": method,
        "rejected_bars": len(rejected),
        "permutation_top_features": perm_ranked[:10],
        "shap": shap_result,
        "low_prob_correlates": corr_features[:5],
        "top_blockers": perm_ranked[:5],
    }
