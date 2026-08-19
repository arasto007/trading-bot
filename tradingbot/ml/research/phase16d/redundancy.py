"""Phase 16D — existing feature redundancy analysis."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase16d.config import CORRELATION_REDUNDANT


def _cluster_features(corr: np.ndarray, names: list[str], threshold: float) -> list[list[str]]:
    n = len(names)
    visited = set()
    clusters: list[list[str]] = []
    for i in range(n):
        if i in visited:
            continue
        cluster = [names[i]]
        visited.add(i)
        for j in range(i + 1, n):
            if j not in visited and abs(corr[i, j]) >= threshold:
                cluster.append(names[j])
                visited.add(j)
        if len(cluster) > 1:
            clusters.append(cluster)
    return clusters


def analyze_feature_redundancy(records: list[Any], bundle: Any) -> dict[str, Any]:
    features = list(bundle.feature_order)
    if not records:
        return {"features": features, "correlation_matrix": {}, "clusters": [], "low_information": []}

    matrix = np.array([[r.existing.get(f, 0.0) for f in features] for r in records], dtype=float)
    corr = np.corrcoef(matrix.T)
    corr = np.nan_to_num(corr, nan=0.0)

    corr_dict: dict[str, dict[str, float]] = {}
    for i, fi in enumerate(features):
        corr_dict[fi] = {features[j]: round(float(corr[i, j]), 4) for j in range(len(features))}

    clusters = _cluster_features(corr, features, CORRELATION_REDUNDANT)
    probs = np.array([r.probability for r in records])
    low_information: list[dict[str, Any]] = []
    for j, feat in enumerate(features):
        col = matrix[:, j]
        if float(np.std(col)) < 1e-8:
            low_information.append({"feature": feat, "reason": "zero_variance"})
            continue
        c = float(np.corrcoef(col, probs)[0, 1]) if float(np.std(col)) > 1e-12 else 0.0
        if abs(c) < 0.05:
            low_information.append({"feature": feat, "reason": "low_corr_with_prob", "corr_prob": round(c, 4)})

    redundant_pairs = []
    for i in range(len(features)):
        for j in range(i + 1, len(features)):
            if abs(corr[i, j]) >= CORRELATION_REDUNDANT:
                redundant_pairs.append({
                    "a": features[i], "b": features[j],
                    "correlation": round(float(corr[i, j]), 4),
                })

    return {
        "feature_count": len(features),
        "correlation_matrix": corr_dict,
        "redundant_pairs": redundant_pairs,
        "clusters": clusters,
        "low_information_features": low_information,
        "redundancy_rate": round(len(redundant_pairs) / max(len(features) * (len(features) - 1) / 2, 1), 4),
    }
