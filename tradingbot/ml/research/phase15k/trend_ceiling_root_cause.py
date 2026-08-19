"""Phase 15K — trend ceiling root cause detector."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15k.config import TREND_THRESHOLD, VALID_ROOT_CAUSES


def _score(evidence: dict[str, float]) -> float:
    return round(min(1.0, max(0.0, sum(evidence.values()) / max(len(evidence), 1))), 4)


def detect_trend_ceiling_root_cause(
    *,
    ceiling: dict[str, Any],
    feature_impact: dict[str, Any],
    distribution_drift: dict[str, Any],
    model_behavior: dict[str, Any],
    pipeline_audit: dict[str, Any],
    engine_replay: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    live_max = float(ceiling.get("live_trend_distribution", {}).get("max", 0.0))
    train_max = float(ceiling.get("training_distribution", {}).get("max", 0.0))
    gap = float(ceiling.get("mathematical_bound", {}).get("gap_to_threshold", 0.0))

    if pipeline_audit.get("flags"):
        candidates.append({
            "cause": "PIPELINE_CORRUPTION",
            "evidence": {
                "pipeline_flags": 1.0,
                "bundle_filter_delta": min(1.0, float(pipeline_audit.get("bundle_vs_filter_max_delta", 0)) * 10),
            },
        })

    if distribution_drift.get("drift_critical_features"):
        candidates.append({
            "cause": "FEATURE_DRIFT",
            "evidence": {
                "drift_critical_count": min(1.0, len(distribution_drift["drift_critical_features"]) / 6),
                "psi_features": min(1.0, len([f for f in distribution_drift.get("per_feature", []) if f.get("psi", 0) > 0.25]) / 6),
            },
        })

    if pipeline_audit.get("normalization_mismatch") or pipeline_audit.get("bundle_vs_filter_max_delta", 0) > 1e-4:
        candidates.append({
            "cause": "TRAIN_INFERENCE_MISMATCH",
            "evidence": {
                "normalization_mismatch": 1.0 if pipeline_audit.get("normalization_mismatch") else 0.0,
                "reorder": 1.0 if pipeline_audit.get("feature_reorder_detected") else 0.0,
            },
        })

    if model_behavior.get("flags"):
        candidates.append({
            "cause": "MODEL_SATURATION",
            "evidence": {
                "tree_saturation": 1.0 if model_behavior.get("tree_saturation") else 0.0,
                "path_collapse": 1.0 if model_behavior.get("path_collapse") else 0.0,
                "low_variance": 1.0 if model_behavior.get("low_variance_leaves") else 0.0,
            },
        })

    train_live_shift = ceiling.get("probability_shift_train_vs_live", {})
    if float(train_live_shift.get("max_delta", 0)) > 0.15:
        candidates.append({
            "cause": "LABEL_SHIFT",
            "evidence": {
                "train_live_max_delta": min(1.0, float(train_live_shift.get("max_delta", 0))),
            },
        })

    if live_max < TREND_THRESHOLD and train_max > live_max + 0.05:
        candidates.append({
            "cause": "PROBABILITY_CALIBRATION_LIMIT",
            "evidence": {
                "live_below_threshold": 1.0,
                "train_live_gap": min(1.0, train_max - live_max),
                "gap_to_threshold": min(1.0, gap / TREND_THRESHOLD),
            },
        })

    if not candidates:
        candidates.append({
            "cause": "PROBABILITY_CALIBRATION_LIMIT",
            "evidence": {"live_max": live_max, "threshold": TREND_THRESHOLD},
        })

    for c in candidates:
        c["score"] = _score({k: float(v) for k, v in c["evidence"].items()})

    ranked = sorted(candidates, key=lambda x: x["score"], reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    root = top["cause"]
    if second and second["score"] > 0.35 and (top["score"] - second["score"]) < 0.15:
        root = "COMBINED_CAUSE"

    assert root in VALID_ROOT_CAUSES

    factors = []
    if distribution_drift.get("drift_critical_features"):
        factors.append(f"PSI drift on {distribution_drift['drift_critical_features'][:3]}")
    if live_max < TREND_THRESHOLD:
        factors.append(f"live max {live_max:.4f} < threshold {TREND_THRESHOLD}")
    if train_max > live_max:
        factors.append(f"training max {train_max:.4f} exceeds live max {live_max:.4f}")
    if model_behavior.get("flags"):
        factors.append(f"model flags: {model_behavior['flags']}")
    if pipeline_audit.get("flags"):
        factors.append(f"pipeline flags: {pipeline_audit['flags']}")

    return {
        "phase": "15K",
        "root_cause": root,
        "evidence_score": top["score"],
        "top_contributing_factors": factors[:3],
        "quantitative_proof": {
            "live_max_probability": live_max,
            "training_max_probability": train_max,
            "threshold": TREND_THRESHOLD,
            "gap_to_threshold": gap,
            "engine_replay_global_max": engine_replay.get("global_max_probability"),
            "all_below_threshold": engine_replay.get("all_below_threshold"),
            "ceiling_breaking_features": feature_impact.get("ceiling_breaking_features", [])[:5],
        },
        "hypothesis_scores": {c["cause"]: c["score"] for c in ranked},
        "candidates": ranked,
    }
