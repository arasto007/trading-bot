"""Phase 15J — evidence-backed root cause detector."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15j.config import VALID_ROOT_CAUSES


def detect_root_cause(
    *,
    trace_report: dict[str, Any],
    statistics: dict[str, Any],
    probability: dict[str, Any],
    feature_drift: dict[str, Any],
    stage_loss: dict[str, Any],
) -> dict[str, Any]:
    causes: list[dict[str, Any]] = []
    primary_stop = trace_report.get("primary_stop_stage", "ENGINE")
    stop_counts = trace_report.get("stop_stage_counts", {})

    if "ENGINE_COLLAPSE" in statistics.get("flags", []):
        causes.append({
            "cause": "ENGINE_COLLAPSE",
            "evidence": {
                "engine_output_pct": statistics.get("engine_output_pct"),
                "trend_buy": statistics.get("trend_buy"),
                "trend_sell": statistics.get("trend_sell"),
                "actionable_pct": probability.get("actionable_pct"),
            },
        })

    if "ENGINE_COLLAPSE" in probability.get("flags", []):
        if not any(c["cause"] == "ENGINE_COLLAPSE" for c in causes):
            causes.append({
                "cause": "ENGINE_COLLAPSE",
                "evidence": {"class_distribution": probability.get("class_distribution")},
            })

    if "PROBABILITY_COLLAPSE" in probability.get("flags", []):
        causes.append({
            "cause": "PROBABILITY_COLLAPSE",
            "evidence": {
                "max_probability": probability.get("all_probabilities", {}).get("max"),
                "threshold": probability.get("threshold"),
                "p99": probability.get("all_probabilities", {}).get("p99"),
            },
        })

    if feature_drift.get("flags"):
        causes.append({
            "cause": "FEATURE_DRIFT",
            "evidence": {
                "drifted_features": feature_drift.get("drifted_features"),
                "psi_threshold": feature_drift.get("psi_threshold"),
            },
        })

    _stage_cause = {
        "DECISION": "DECISION_GATE",
        "CALIBRATION": "CALIBRATION",
        "MAPPING": "CONFIDENCE_MAPPING",
        "RISK": "RISK_GATE",
        "QUALITY": "QUALITY_GATE",
        "KERNEL": "KERNEL_MAPPING",
    }
    if primary_stop in _stage_cause:
        causes.append({
            "cause": _stage_cause[primary_stop],
            "evidence": {
                "stop_count": stop_counts.get(primary_stop, 0),
                "stage_loss": next(
                    (s for s in stage_loss.get("funnel", []) if s["stage"].lower() == primary_stop.lower()),
                    None,
                ),
            },
        })

    if not causes:
        causes.append({
            "cause": "ENGINE_COLLAPSE",
            "evidence": {"primary_stop_stage": primary_stop, "stop_counts": stop_counts},
        })

    unique = list({c["cause"] for c in causes})
    if len(unique) > 1:
        root = "MULTIPLE"
    else:
        root = unique[0]

    assert root in VALID_ROOT_CAUSES

    return {
        "phase": "15J",
        "root_cause": root,
        "primary_failing_stage": primary_stop,
        "causes": causes,
        "quantitative_summary": {
            "trend_bars_traced": trace_report.get("bars_traced"),
            "engine_output_pct": statistics.get("engine_output_pct"),
            "primary_stop_stage": primary_stop,
            "stop_stage_counts": stop_counts,
            "final_signals": stage_loss.get("final_signals"),
        },
    }
