"""Phase 14.10 — recommendations and final report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_10.config import MIN_WF_ROBUSTNESS

_SEVERITY_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}


def _assign_impact_pct(root_causes: list[dict[str, Any]]) -> None:
    if not root_causes:
        return
    weights = [_SEVERITY_WEIGHT.get(str(c.get("severity", "low")), 1.0) for c in root_causes]
    total = sum(weights) or 1.0
    for cause, w in zip(root_causes, weights):
        cause["impact_pct"] = round(100.0 * w / total, 1)


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def build_recommendations(
    *,
    yearly_metrics: dict[str, Any],
    feature_drift: dict[str, Any],
    regime_distribution: dict[str, Any],
    confidence_distribution: dict[str, Any],
    calibration_stability: dict[str, Any],
    threshold_analysis: dict[str, Any],
    adaptive_threshold: dict[str, Any],
    adaptive_regime_policy: dict[str, Any],
    transition_analysis: dict[str, Any],
    robustness_recovery: dict[str, Any],
) -> dict[str, Any]:
    root_causes: list[dict[str, Any]] = []

    if threshold_analysis.get("mean_threshold_spread_pf", 0) > 0.5:
        root_causes.append({
            "rank": 1,
            "cause": "threshold_drift",
            "evidence": f"Per-year optimal threshold spread PF={threshold_analysis['mean_threshold_spread_pf']}",
            "severity": "high",
        })

    if feature_drift.get("most_shifted_features"):
        root_causes.append({
            "rank": 2,
            "cause": "feature_drift",
            "evidence": f"Shifted: {feature_drift['most_shifted_features']}",
            "severity": "medium",
        })

    if calibration_stability.get("yearly_calibration_unstable"):
        root_causes.append({
            "rank": 3,
            "cause": "calibration_drift",
            "evidence": calibration_stability.get("label_distribution", {}),
            "severity": "high",
        })

    regime_shift = regime_distribution.get("regime_shift_summary", {}).get("trend_pct_delta_first_to_last", 0)
    if abs(regime_shift) > 0.10:
        root_causes.append({
            "rank": 4,
            "cause": "regime_drift",
            "evidence": f"TREND pct delta={regime_shift}",
            "severity": "medium",
        })

    conf_delta = confidence_distribution.get("year_comparison", {}).get("confidence_delta", 0)
    if abs(conf_delta) > 0.05:
        root_causes.append({
            "rank": 5,
            "cause": "confidence_distribution_shift",
            "evidence": f"Mean confidence delta={conf_delta}",
            "severity": "medium",
        })

    worst_trans = transition_analysis.get("worst_transition")
    if worst_trans:
        root_causes.append({
            "rank": 6,
            "cause": "regime_transition_losses",
            "evidence": worst_trans,
            "severity": "low",
        })

    root_causes.sort(key=lambda x: x["rank"])
    _assign_impact_pct(root_causes)

    recs: list[dict[str, Any]] = []
    if adaptive_threshold.get("improves_stability"):
        recs.append({
            "action": "use_adaptive_threshold",
            "research_only": True,
            "rule": adaptive_threshold.get("rule"),
            "expected_robustness": robustness_recovery.get("adaptive_threshold_robustness"),
        })
    else:
        recs.append({"action": "keep_static_threshold", "threshold": 0.30, "research_only": True})

    if calibration_stability.get("yearly_calibration_unstable"):
        recs.append({
            "action": "use_yearly_calibration",
            "research_only": True,
            "note": "Refit Platt per calendar year in research layer only.",
        })

    if adaptive_regime_policy.get("policy_mean_pf", 0) > 0:
        recs.append({
            "action": "use_regime_aware_confidence",
            "research_only": True,
            "policy": adaptive_regime_policy.get("policy"),
            "expected_robustness": robustness_recovery.get("regime_policy_robustness"),
        })

    if not recs:
        recs.append({"action": "keep_static", "research_only": True})

    return {
        "phase": "14.10",
        "root_cause_ranking": root_causes,
        "recommendations": recs,
        "primary_recommendation": recs[0]["action"] if recs else "keep_static",
        "robustness_recovery_possible": robustness_recovery.get("improvement_vs_baseline", 0) > 0,
    }


def build_final_report(
    *,
    yearly_metrics: dict[str, Any],
    feature_drift: dict[str, Any],
    regime_distribution: dict[str, Any],
    confidence_distribution: dict[str, Any],
    calibration_stability: dict[str, Any],
    threshold_analysis: dict[str, Any],
    adaptive_threshold: dict[str, Any],
    adaptive_regime_policy: dict[str, Any],
    transition_analysis: dict[str, Any],
    montecarlo_yearly: dict[str, Any],
    robustness_recovery: dict[str, Any],
    recommendations: dict[str, Any],
    fingerprint_unchanged: bool,
    baseline_robustness: float = 0.17,
) -> dict[str, Any]:
    updated_wf = robustness_recovery.get("best_robustness", baseline_robustness)
    root_causes = recommendations.get("root_cause_ranking", [])
    diagnostic_complete = bool(root_causes) and fingerprint_unchanged

    ready_phase15 = (
        updated_wf > MIN_WF_ROBUSTNESS
        and fingerprint_unchanged
        and diagnostic_complete
    )

    return {
        "phase": "14.10",
        "PHASE_14_10_STATUS": "PASS" if diagnostic_complete else "NEEDS_REVIEW",
        "READY_FOR_PHASE15": "YES" if ready_phase15 else "NO",
        "walk_forward_robustness": {
            "baseline": baseline_robustness,
            "static_recomputed": robustness_recovery.get("static_recomputed"),
            "updated_best": updated_wf,
            "best_variant": robustness_recovery.get("best_research_variant"),
        },
        "root_cause_ranking": root_causes,
        "root_cause_summary": {
            "feature_drift": feature_drift.get("most_shifted_features", []),
            "calibration_drift": calibration_stability.get("yearly_calibration_unstable", False),
            "threshold_drift": threshold_analysis.get("mean_threshold_spread_pf", 0),
            "regime_drift": regime_distribution.get("regime_shift_summary", {}),
            "confidence_drift": confidence_distribution.get("year_comparison", {}),
        },
        "recommended_solution": recommendations.get("primary_recommendation"),
        "recommendations": recommendations.get("recommendations", []),
        "monte_carlo_yearly_pass_rate": (
            f"{montecarlo_yearly.get('years_passing_mc', 0)}/{montecarlo_yearly.get('active_years', 0)}"
        ),
        "transition_risk": transition_analysis.get("worst_transition"),
        "adaptive_threshold_research": {
            "improves_stability": adaptive_threshold.get("improves_stability"),
            "rule": adaptive_threshold.get("rule"),
        },
        "yearly_metrics_summary": {
            y: {"pf": v.get("profit_factor"), "trades": v.get("trades")}
            for y, v in yearly_metrics.get("per_year", {}).items()
            if not v.get("skipped")
        },
        "fingerprint_unchanged": fingerprint_unchanged,
        "connected_to_live_trading": False,
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
