"""Phase 16C — forensic verdict and next-phase recommendation."""

from __future__ import annotations

from typing import Any

VERDICTS = (
    "RULE_BOTTLENECK",
    "RF_BOTTLENECK",
    "RULE_AND_RF",
    "FEATURE_LIMITATION",
    "UNKNOWN",
)


def determine_verdict(
    *,
    funnel: dict[str, Any],
    rule_stats: dict[str, Any],
    rf_dist: dict[str, Any],
    clusters: dict[str, Any],
    feature_imp: dict[str, Any],
    throughput: dict[str, Any],
) -> str:
    fc = funnel.get("funnel_counts", {})
    trend = fc.get("trend_bars", 0) or 1
    rule_rate = fc.get("rule_pass", 0) / trend
    rf_rate = fc.get("rf_pass", 0) / trend
    rule_rf_cond = fc.get("rf_pass", 0) / max(fc.get("rule_pass", 0), 1)

    max_p = rf_dist.get("stats", {}).get("max", 0.0)
    p99 = rf_dist.get("stats", {}).get("p99", 0.0)
    rules_restrictive = rule_stats.get("rules_restrictive_before_rf", False)
    rule_reject_rate = rule_stats.get("rule_rejection_rate", 0.0)

    # Feature limitation: ceiling barely above threshold, perm importance spread low
    top_blockers = feature_imp.get("top_blockers", [])
    blocker_concentration = top_blockers[0]["mean_permutation_delta"] if top_blockers else 0.0
    feature_limited = max_p < 0.50 and p99 < 0.48 and blocker_concentration < 0.02

    rule_heavy = rule_reject_rate > 0.55 or (1 - rule_rate) > 0.55
    rf_heavy = rule_rate > 0.15 and rule_rf_cond < 0.05 and max_p < 0.45

    if rule_reject_rate > 0.80:
        return "RULE_BOTTLENECK"
    if rule_heavy and rf_heavy:
        return "RULE_AND_RF"
    if rule_heavy and not rf_heavy:
        return "RULE_BOTTLENECK"

    # High rule pass but RF collapse → structural ceiling vs threshold proximity
    if rule_rate > 0.5 and rule_rf_cond < 0.02:
        dominant = clusters.get("dominant_cluster", "far")
        if dominant == "very_close" and max_p >= 0.40:
            return "RF_BOTTLENECK"
        if feature_limited or max_p < 0.48:
            return "FEATURE_LIMITATION"
        return "RF_BOTTLENECK"

    if feature_limited and max_p > 0.38:
        return "FEATURE_LIMITATION"

    if rf_heavy or throughput.get("primary_engine_bottleneck") == "RF":
        return "RF_BOTTLENECK"
    if rules_restrictive and rule_reject_rate > 0.4:
        return "RULE_BOTTLENECK"

    dominant = clusters.get("dominant_cluster", "far")
    if dominant == "very_close" and max_p >= 0.40:
        return "RF_BOTTLENECK"

    if trend == 0:
        return "UNKNOWN"

    return "RF_BOTTLENECK" if rf_rate < rule_rate * 0.5 else "UNKNOWN"


def recommend_next_phase(verdict: str) -> str:
    mapping = {
        "RULE_BOTTLENECK": "Phase 16D — TREND Rule Relaxation Study (read-only variants A–E comparison, no production change)",
        "RF_BOTTLENECK": "Phase 16D — RF Calibration / Score Rescaling Study (read-only Platt/isotonic on frozen bundle outputs)",
        "RULE_AND_RF": "Phase 16D — Dual-Stage TREND Gate Analysis (rule variants + score geometry, read-only)",
        "FEATURE_LIMITATION": "Phase 16D — Feature Ceiling Expansion Study (new features vs frozen bundle, read-only)",
        "UNKNOWN": "Phase 16D — Extended TREND Shadow Trace (longer window + bar-level replay, read-only)",
    }
    return mapping.get(verdict, mapping["UNKNOWN"])


def build_final_report(
    *,
    verdict: str,
    funnel: dict[str, Any],
    rule_stats: dict[str, Any],
    rf_dist: dict[str, Any],
    clusters: dict[str, Any],
    throughput: dict[str, Any],
    threshold_sim: dict[str, Any],
    symbol: str,
    timeframe: str,
    days: int,
    stride: int,
) -> dict[str, Any]:
    return {
        "phase": "16C",
        "verdict": verdict,
        "recommended_next_phase": recommend_next_phase(verdict),
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "stride": stride,
        "summary": {
            "trend_bars": funnel.get("funnel_counts", {}).get("trend_bars", 0),
            "rule_pass": funnel.get("funnel_counts", {}).get("rule_pass", 0),
            "rf_pass": funnel.get("funnel_counts", {}).get("rf_pass", 0),
            "kernel_output": funnel.get("funnel_counts", {}).get("kernel_output", 0),
            "max_probability": rf_dist.get("stats", {}).get("max"),
            "rule_acceptance_rate": rule_stats.get("rule_acceptance_rate"),
            "rejection_geometry": clusters.get("interpretation"),
            "primary_bottleneck": throughput.get("primary_engine_bottleneck"),
        },
        "threshold_simulation_highlights": {
            k: v.get("actionable_signals")
            for k, v in threshold_sim.get("thresholds", {}).items()
        },
        "no_fixes_applied": True,
        "read_only": True,
    }
