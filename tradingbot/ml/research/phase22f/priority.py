"""Phase 22F — evidence-backed optimization priority list."""

from __future__ import annotations

from typing import Any


def build_priority_list(
    contribution: dict[str, Any],
    overfiltering: dict[str, Any],
    missed: dict[str, Any],
    baseline_by_tf: dict[str, dict],
) -> dict[str, Any]:
    candidates = []
    m5 = baseline_by_tf.get("M5", {})
    pf = m5.get("metrics", {}).get("profit_factor", 0)
    pf_val = float(pf) if pf not in ("inf", None) else 0.0

    for comp in contribution.get("components", [])[:8]:
        blocks = comp.get("blocks_total", 0)
        if blocks < 5:
            continue
        missed_r = 0.0
        blocker_key = comp["component"].replace("_filter", "").replace("riskgate", "riskgate")
        for stage, data in (missed.get("by_blocker") or {}).items():
            if blocker_key in stage or stage in comp["component"]:
                missed_r += data.get("sum_expected_r", 0)
        complexity = {"riskgate": 3, "meta": 2, "calibration": 4, "trade_quality": 3, "rsi_filter": 1, "adx_filter": 1}.get(
            comp["component"], 3
        )
        pf_improve = round(min(0.5, missed_r / max(blocks, 1) * 0.05), 4)
        dd_impact = "high" if comp["component"] == "riskgate" else "medium"
        confidence = "high" if blocks > 100 and missed_r > 1 else "medium" if blocks > 20 else "low"
        risk = "low" if comp["component"] in ("rsi_filter", "adx_filter") else "medium"
        candidates.append({
            "component": comp["component"],
            "evidence_blocks": blocks,
            "evidence_missed_r_sum": round(missed_r, 2),
            "expected_pf_improvement": pf_improve,
            "expected_dd_impact": dd_impact,
            "implementation_complexity_1_5": complexity,
            "confidence": confidence,
            "risk_if_changed": risk,
            "estimated_fast_validation_min": 10,
            "recommendation": _recommend(comp["component"], blocks, missed_r, overfiltering.get("verdict")),
        })

    candidates.sort(
        key=lambda x: (x["expected_pf_improvement"], x["evidence_blocks"]),
        reverse=True,
    )

    return {
        "phase": "22F",
        "baseline_m5_pf": pf_val,
        "overfiltering_verdict": overfiltering.get("verdict"),
        "candidates": candidates,
        "top_recommendation": candidates[0] if candidates else None,
        "note": "Evidence from hold-chain blocks + missed-opportunity forward R only",
    }


def _recommend(component: str, blocks: int, missed_r: float, over_verdict: str) -> str:
    if component == "riskgate" and over_verdict == "over_filtered" and blocks > 500:
        return "Investigate RiskGate cascade (daily loss / min balance) — largest block count with execution collapse"
    if missed_r > 5 and component in ("rsi_filter", "adx_filter"):
        return f"Review {component} — blocked signals with aggregate {missed_r:.1f}R forward potential"
    if component == "calibration" and blocks > 50:
        return "Audit calibration gate — significant pre-RiskGate attrition"
    return f"Monitor {component} — {blocks} blocks recorded"
