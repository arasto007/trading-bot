"""Phase 16D — surrogate ceiling simulation without retraining frozen bundle."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.phase16d.config import DEFAULT_SEED, RF_THRESHOLD


def simulate_ceiling_improvement(
    records: list[Any],
    top_candidates: list[str],
    bundle: Any,
) -> dict[str, Any]:
    """
    Fit surrogate models on candidate + existing features → win_proxy.
    Does NOT modify or retrain the frozen production bundle.
    """
    if len(records) < 30:
        return {"error": "insufficient_samples", "bar_count": len(records)}

    existing = list(bundle.feature_order)
    feature_cols = existing + [c for c in top_candidates if c not in existing]
    X = np.array([
        [r.existing.get(f, r.candidates.get(f, 0.0)) for f in feature_cols]
        for r in records
    ], dtype=float)
    y = np.array([r.win_proxy for r in records], dtype=int)
    probs_frozen = np.array([r.probability for r in records], dtype=float)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    lr = LogisticRegression(max_iter=500, random_state=DEFAULT_SEED, C=1.0)
    lr.fit(Xs, y)
    lr_probs = lr.predict_proba(Xs)[:, 1]

    surr_rf = RandomForestClassifier(
        n_estimators=100, max_depth=6, random_state=DEFAULT_SEED, min_samples_leaf=5,
    )
    surr_rf.fit(Xs, y)
    rf_probs = surr_rf.predict_proba(Xs)[:, 1]

    # Existing-only surrogate for comparison
    Xe = np.array([[r.existing.get(f, 0.0) for f in existing] for r in records], dtype=float)
    Xes = StandardScaler().fit_transform(Xe)
    lr_existing = LogisticRegression(max_iter=500, random_state=DEFAULT_SEED)
    lr_existing.fit(Xes, y)
    lr_existing_probs = lr_existing.predict_proba(Xes)[:, 1]

    def _stats(arr: np.ndarray) -> dict[str, float]:
        return {
            "max": round(float(np.max(arr)), 6),
            "mean": round(float(np.mean(arr)), 6),
            "std": round(float(np.std(arr)), 6),
            "p95": round(float(np.percentile(arr, 95)), 6),
            "above_0.40": int(np.sum(arr >= RF_THRESHOLD)),
            "above_0.40_rate": round(float(np.mean(arr >= RF_THRESHOLD)), 6),
        }

    frozen_stats = _stats(probs_frozen)
    combined_stats = _stats(rf_probs)
    existing_only_stats = _stats(lr_existing_probs)

    uplift_max = combined_stats["max"] - frozen_stats["max"]
    uplift_spread = combined_stats["std"] - frozen_stats["std"]
    uplift_throughput = combined_stats["above_0.40"] - frozen_stats["above_0.40"]

    return {
        "simulation_only": True,
        "frozen_bundle_retrained": False,
        "bar_count": len(records),
        "features_used": feature_cols,
        "frozen_bundle": frozen_stats,
        "surrogate_existing_only": existing_only_stats,
        "surrogate_lr_combined": _stats(lr_probs),
        "surrogate_rf_combined": combined_stats,
        "expected_improvement": {
            "max_probability_delta": round(uplift_max, 6),
            "spread_delta": round(uplift_spread, 6),
            "throughput_delta_actionable": uplift_throughput,
            "throughput_delta_rate": round(
                combined_stats["above_0.40_rate"] - frozen_stats["above_0.40_rate"], 6,
            ),
        },
        "theoretical_ceiling_with_candidates": combined_stats["max"],
        "candidates_add_information": uplift_max > 0.03 or uplift_spread > 0.01,
    }
