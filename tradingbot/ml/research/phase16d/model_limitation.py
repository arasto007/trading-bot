"""Phase 16D — model / label / feature limitation scoring."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features


def analyze_model_limitations(
    records: list[Any],
    info_gain: dict[str, Any],
    ceiling_sim: dict[str, Any],
    redundancy: dict[str, Any],
    ceiling: dict[str, Any],
    candles: Any,
    bundle: Any,
) -> dict[str, Any]:
    """Assign confidence scores to limitation hypotheses A–D."""
    scores = {
        "A_missing_information": 0.0,
        "B_rf_architecture": 0.0,
        "C_training_labels": 0.0,
        "D_combination": 0.0,
    }

    # A: candidates show MI, surrogate uplift, saturation high
    high_mi = info_gain.get("high_mi_candidate_count", 0)
    candidates_win = info_gain.get("candidates_outperform_existing", False)
    sat = ceiling.get("overall_saturation_score", 0.0)
    uplift = ceiling_sim.get("expected_improvement", {}).get("max_probability_delta", 0.0)
    if high_mi >= 3:
        scores["A_missing_information"] += 0.3
    if candidates_win:
        scores["A_missing_information"] += 0.25
    if sat > 0.7:
        scores["A_missing_information"] += 0.25
    if ceiling_sim.get("candidates_add_information"):
        scores["A_missing_information"] += 0.2

    # B: surrogate RF on same features achieves higher spread
    frozen_std = ceiling_sim.get("frozen_bundle", {}).get("std", 0.0)
    surr_std = ceiling_sim.get("surrogate_rf_combined", {}).get("std", 0.0)
    if surr_std > frozen_std * 1.5:
        scores["B_rf_architecture"] += 0.35
    existing_only = ceiling_sim.get("surrogate_existing_only", {}).get("max", 0.0)
    frozen_max = ceiling_sim.get("frozen_bundle", {}).get("max", 0.0)
    if existing_only > frozen_max + 0.05:
        scores["B_rf_architecture"] += 0.35

    # C: label analysis from training samples
    try:
        train_frame = build_ml_features(candles)
        if "label" in train_frame.columns:
            labels = train_frame["label"].dropna()
            pos_rate = float(labels.mean()) if len(labels) else 0.5
        else:
            pos_rate = float(np.mean([r.win_proxy for r in records])) if records else 0.5
    except Exception:
        pos_rate = float(np.mean([r.win_proxy for r in records])) if records else 0.5

    if pos_rate < 0.15 or pos_rate > 0.85:
        scores["C_training_labels"] += 0.4
    win_corr = max(
        (abs(r.get("corr_win", 0)) for r in info_gain.get("ranked_features", [])),
        default=0.0,
    )
    if win_corr < 0.1:
        scores["C_training_labels"] += 0.3

    # D: combination when multiple scores high
    high_count = sum(1 for v in scores.values() if v >= 0.5)
    if high_count >= 2:
        scores["D_combination"] = min(1.0, sum(scores.values()) / 3)

    primary = max(scores, key=scores.get)
    return {
        "hypothesis_scores": {k: round(v, 4) for k, v in scores.items()},
        "primary_limitation": primary,
        "label_positive_rate_proxy": round(pos_rate, 4),
        "redundant_feature_count": len(redundancy.get("redundant_pairs", [])),
        "low_information_count": len(redundancy.get("low_information_features", [])),
        "frozen_vs_surrogate_max_delta": round(uplift, 6),
    }


def build_feature_gap_analysis(
    info_gain: dict[str, Any],
    redundancy: dict[str, Any],
    ceiling: dict[str, Any],
    bundle: Any,
) -> dict[str, Any]:
    existing = set(bundle.feature_order)
    top_candidates = [
        r["feature"] for r in info_gain.get("ranked_features", [])
        if r["group"] == "candidate"
    ][:8]
    gaps = []
    for feat in top_candidates:
        if feat not in existing:
            entry = next((r for r in info_gain.get("ranked_features", []) if r["feature"] == feat), {})
            gaps.append({
                "feature": feat,
                "in_production_bundle": False,
                "mutual_info_win": entry.get("mutual_info_win"),
                "corr_prob": entry.get("corr_prob"),
                "gap_type": "missing_from_bundle",
            })
    return {
        "production_features": list(existing),
        "missing_high_value_candidates": gaps,
        "saturation_by_dimension": ceiling.get("saturation_scores", {}),
        "redundant_existing_pairs": redundancy.get("redundant_pairs", [])[:5],
        "information_gap_confirmed": len(gaps) >= 3,
    }
