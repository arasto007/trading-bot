"""Phase 17A — long-term maintenance estimates."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.architecture_matrix import ARCHITECTURES


def _maintenance_profile(arch: dict[str, Any]) -> dict[str, Any]:
    family = arch["model_family"]
    features = arch["features"]
    ensemble = arch["ensemble"]
    aid = arch["id"]

    if aid == "A":
        return {
            "retrain_frequency": "none_frozen",
            "retrain_months": None,
            "automatic_retraining": "not_applicable",
            "drift_resistance": "low",  # already drifted (16Y/16Z)
            "feature_maintenance_burden": "low",
            "monitoring_complexity": "low",
            "notes": "Frozen bundle already exhibits feature-space shift; no recovery path.",
        }

    if aid == "B":
        return {
            "retrain_frequency": "blocked",
            "retrain_months": None,
            "automatic_retraining": "not_applicable",
            "drift_resistance": "low",
            "feature_maintenance_burden": "high",
            "monitoring_complexity": "high",
            "notes": "Non-viable: frozen RF cannot consume new features.",
        }

    if family == "random_forest":
        return {
            "retrain_frequency": "quarterly_or_on_psi",
            "retrain_months": 3,
            "automatic_retraining": "semi_automatic_shadow_then_promote",
            "drift_resistance": "medium",
            "feature_maintenance_burden": "medium" if features == "current_plus_top5" else "low",
            "monitoring_complexity": "medium",
            "notes": "Same sklearn stack; PSI + checksum gates; rollback to trend_rf_v40.",
        }

    if family == "sklearn_gbm":
        return {
            "retrain_frequency": "quarterly",
            "retrain_months": 3,
            "automatic_retraining": "semi_automatic_shadow_then_promote",
            "drift_resistance": "medium_high",
            "feature_maintenance_burden": "medium",
            "monitoring_complexity": "medium",
            "notes": "Still sklearn; hyperparameter sensitivity higher than RF.",
        }

    if family in ("lightgbm", "xgboost"):
        return {
            "retrain_frequency": "monthly_to_quarterly",
            "retrain_months": 2,
            "automatic_retraining": "pipeline_required",
            "drift_resistance": "high",
            "feature_maintenance_burden": "medium_high",
            "monitoring_complexity": "high",
            "notes": "New dependency; version pinning; GPU optional; more ops surface.",
        }

    # stacks
    return {
        "retrain_frequency": "monthly",
        "retrain_months": 1,
        "automatic_retraining": "complex_multi_model_pipeline",
        "drift_resistance": "high",
        "feature_maintenance_burden": "high",
        "monitoring_complexity": "very_high",
        "notes": "Two models + meta-learner; failure modes multiply.",
    }


def build_maintenance_analysis() -> dict[str, Any]:
    profiles = []
    for arch in ARCHITECTURES:
        profiles.append({
            "id": arch["id"],
            "name": arch["name"],
            **_maintenance_profile(arch),
        })

    return {
        "phase": "17A",
        "profiles": profiles,
        "recommended_ops_pattern": {
            "shadow_mode_days": 30,
            "promotion_gates": [
                "dataset_fingerprint_match",
                "model_checksum_recorded",
                "chronological_validation_pass",
                "psi_after_alignment_lt_1",
                "range_engine_regression_zero",
                "trend_actionable_rate_gt_baseline",
            ],
            "rollback": "restore trend_rf_v40 bundle artifacts",
            "range_engine": "never_retrained_in_this_path",
        },
    }
