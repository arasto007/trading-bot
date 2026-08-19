"""Phase 16D — mutual information and permutation importance for candidates."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.feature_selection import mutual_info_classif

from tradingbot.ml.research.phase15k.config import pearson_corr
from tradingbot.ml.research.phase16d.candidate_compute import CANDIDATE_FEATURE_IDS
from tradingbot.ml.research.phase16d.config import DEFAULT_SEED, LOW_MI_THRESHOLD


def _mutual_info(x: np.ndarray, y: np.ndarray, *, discrete_y: bool = True) -> float:
    if len(x) < 5 or float(np.std(x)) < 1e-12:
        return 0.0
    y_arr = np.asarray(y, dtype=float)
    if not discrete_y:
        ranks = np.argsort(np.argsort(y_arr))
        n_bins = min(5, len(np.unique(y_arr)))
        if n_bins < 2:
            return 0.0
        y_arr = (ranks * n_bins // max(len(y_arr), 1)).astype(int)
    mi = mutual_info_classif(
        x.reshape(-1, 1), y_arr.astype(int), random_state=DEFAULT_SEED, discrete_features=False,
    )[0]
    return float(mi)


def _perm_importance(bundle: Any, features: dict[str, float], baseline: float) -> float:
    order = list(bundle.feature_order)
    total = 0.0
    for feat in order:
        perturbed = dict(features)
        perturbed[feat] = 0.0
        total += abs(baseline - float(bundle.predict_proba(perturbed)))
    return total / max(len(order), 1)


def analyze_information_gain(
    records: list[Any],
    bundle: Any,
) -> dict[str, Any]:
    probs = np.array([r.probability for r in records], dtype=float)
    wins = np.array([r.win_proxy for r in records], dtype=int)

    existing_ids = list(bundle.feature_order)
    all_features: list[tuple[str, str, list[float]]] = []

    for feat in existing_ids:
        vals = [r.existing.get(feat, 0.0) for r in records]
        all_features.append(("existing", feat, vals))
    for feat in CANDIDATE_FEATURE_IDS:
        vals = [r.candidates.get(feat, 0.0) for r in records]
        all_features.append(("candidate", feat, vals))

    ranked: list[dict[str, Any]] = []
    for group, feat, vals in all_features:
        arr = np.array(vals, dtype=float)
        mi_win = _mutual_info(arr, wins, discrete_y=True)
        mi_prob = _mutual_info(arr, probs, discrete_y=False)
        corr_win = pearson_corr(arr, wins.astype(float))
        corr_prob = pearson_corr(arr, probs)
        perm = 0.0
        if group == "existing" and records:
            perm = _perm_importance(bundle, records[0].existing, records[0].probability)
            # aggregate mean perm across sample
            sample = records[: min(50, len(records))]
            perms = []
            for r in sample:
                perts = {}
                for f in existing_ids:
                    perts = dict(r.existing)
                    perts[f] = 0.0
                    perms.append(abs(r.probability - float(bundle.predict_proba(perts))))
            perm = float(np.mean(perms)) if perms else 0.0

        ranked.append({
            "group": group,
            "feature": feat,
            "mutual_info_win": round(mi_win, 6),
            "mutual_info_prob": round(mi_prob, 6),
            "corr_win": round(corr_win, 6),
            "corr_prob": round(corr_prob, 6),
            "permutation_importance_mean": round(perm, 6) if group == "existing" else None,
            "composite_score": round(mi_win * 0.4 + abs(corr_prob) * 0.3 + abs(corr_win) * 0.3, 6),
        })

    ranked.sort(key=lambda x: -x["composite_score"])
    high_mi_candidates = [
        r for r in ranked if r["group"] == "candidate" and r["mutual_info_win"] > LOW_MI_THRESHOLD
    ]

    return {
        "bar_count": len(records),
        "ranked_features": ranked,
        "top_candidates": [r for r in ranked if r["group"] == "candidate"][:8],
        "top_existing": [r for r in ranked if r["group"] == "existing"][:5],
        "high_mi_candidate_count": len(high_mi_candidates),
        "candidates_outperform_existing": (
            len(high_mi_candidates) > 0
            and (not ranked or ranked[0]["group"] == "candidate")
        ),
    }


def build_candidate_ranking(info_gain: dict[str, Any]) -> dict[str, Any]:
    candidates = [r for r in info_gain.get("ranked_features", []) if r["group"] == "candidate"]
    return {
        "ranking": candidates,
        "top_5": candidates[:5],
        "recommended_for_simulation": [c["feature"] for c in candidates[:5]],
    }
