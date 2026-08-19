"""Phase 14.10 — walk-forward robustness recomputation."""

from __future__ import annotations

from typing import Any

import numpy as np


def compute_robustness_score(pfs: list[float]) -> float:
    if len(pfs) <= 1:
        return 0.5
    return round(max(0.0, 1.0 - float(np.std(pfs))), 4)


def recompute_robustness(
    yearly_metrics: dict[str, Any],
    adaptive_threshold: dict[str, Any],
    adaptive_regime_policy: dict[str, Any],
    *,
    baseline_robustness: float = 0.17,
) -> dict[str, Any]:
    static_pfs = [
        float(v["profit_factor"])
        for v in yearly_metrics.get("per_year", {}).values()
        if not v.get("skipped")
    ]
    baseline_score = compute_robustness_score(static_pfs)

    adaptive_pfs = [
        float(v["adaptive_pf"])
        for v in adaptive_threshold.get("per_year", {}).values()
        if not v.get("skipped")
    ]
    adaptive_score = compute_robustness_score(adaptive_pfs)

    policy_pfs = [
        float(v["regime_policy_pf"])
        for v in adaptive_regime_policy.get("per_year", {}).values()
        if not v.get("skipped")
    ]
    policy_score = compute_robustness_score(policy_pfs)

    best_name = "static"
    best_score = baseline_score
    for name, score in (
        ("adaptive_threshold", adaptive_score),
        ("regime_policy", policy_score),
    ):
        if score > best_score:
            best_name = name
            best_score = score

    return {
        "phase": "14.10",
        "baseline_robustness_reported": baseline_robustness,
        "static_recomputed": baseline_score,
        "adaptive_threshold_robustness": adaptive_score,
        "regime_policy_robustness": policy_score,
        "best_research_variant": best_name,
        "best_robustness": best_score,
        "improvement_vs_baseline": round(best_score - baseline_robustness, 4),
        "meets_wf_gate": best_score > 0.40,
        "yearly_pfs_static": static_pfs,
        "yearly_pfs_adaptive_threshold": adaptive_pfs,
        "yearly_pfs_regime_policy": policy_pfs,
    }
