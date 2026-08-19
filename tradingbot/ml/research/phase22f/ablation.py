"""Phase 22F — feature contribution from baseline hold-chain evidence."""

from __future__ import annotations

from typing import Any

COMPONENT_MAP = {
    "decision_hold": "decision_engine",
    "calibration_hold": "calibration",
    "trade_quality_hold": "trade_quality",
    "rsi_filter_hold": "rsi_filter",
    "adx_filter_hold": "adx_filter",
    "meta_hold": "meta",
    "riskgate_hold": "riskgate",
}


def build_feature_contribution(
    baseline_by_tf: dict[str, dict],
    missed_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive per-component trade removal counts from hold-chain (single baseline run)."""
    components: dict[str, dict] = {}
    pf_base = []
    exp_base = []

    for tf, result in baseline_by_tf.items():
        hc = result.get("hold_chain") or {}
        stages = hc.get("ml_hold_stages") or {}
        m = result.get("metrics") or {}
        pf_base.append(float(m.get("profit_factor") or 0))
        exp_base.append(float(m.get("expectancy") or 0))
        bars = max(hc.get("bars_evaluated", 1), 1)

        for stage_key, comp in COMPONENT_MAP.items():
            if stage_key == "meta_hold":
                count = hc.get("meta_hold", 0)
            elif stage_key == "riskgate_hold":
                count = hc.get("riskgate_hold", 0)
            else:
                count = stages.get(stage_key, 0)
            entry = components.setdefault(comp, {
                "component": comp,
                "blocks_total": 0,
                "blocks_by_tf": {},
                "pct_of_bars_total": 0.0,
            })
            entry["blocks_total"] += count
            entry["blocks_by_tf"][tf] = count

        rg_reasons = hc.get("riskgate_block_reasons") or {}
        rg = components.setdefault("riskgate", {"component": "riskgate", "blocks_total": 0, "blocks_by_tf": {}, "reasons": {}})
        for reason, cnt in rg_reasons.items():
            rg.setdefault("reasons", {})[reason] = rg.get("reasons", {}).get(reason, 0) + cnt

    total_bars = sum(max(r.get("hold_chain", {}).get("bars_evaluated", 0), 1) for r in baseline_by_tf.values())
    avg_pf = sum(pf_base) / max(len(pf_base), 1)
    avg_exp = sum(exp_base) / max(len(exp_base), 1)

    ranked = []
    for comp, data in components.items():
        blocks = data["blocks_total"]
        pct = round(blocks / total_bars * 100, 3)
        data["pct_of_bars_total"] = pct
        missed_r = 0.0
        if missed_summary and comp in missed_summary.get("by_blocker", {}):
            missed_r = missed_summary["by_blocker"][comp].get("sum_expected_r", 0)
        ranked.append({
            **data,
            "trades_removed_estimate": blocks,
            "pf_baseline_avg": round(avg_pf, 4),
            "expectancy_baseline_avg": round(avg_exp, 4),
            "pf_delta_if_unblocked_estimate": round(missed_r / max(blocks, 1) * 0.01, 4),
            "dd_impact_estimate": "requires_execution_sim",
        })

    ranked.sort(key=lambda x: x["blocks_total"], reverse=True)
    return {
        "phase": "22F",
        "method": "hold_chain_counterfactual_from_baseline",
        "production_modified": False,
        "components": ranked,
        "note": "Block counts are per-bar/per-signal evaluations, not unique trades",
    }
