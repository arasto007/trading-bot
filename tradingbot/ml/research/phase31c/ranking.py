"""Conservative production ranking for exit candidates."""

from __future__ import annotations

from typing import Any


def rank_candidates(candidates: list[dict], baseline: dict, *, sim_baseline: dict | None = None) -> list[dict]:
    scored = []
    compare = sim_baseline or baseline
    base_pf = compare.get("profit_factor", 1.0)
    base_dd = compare.get("max_drawdown_pct", 1.0)
    base_exp = compare.get("expectancy", 0.0)

    skip_names = {"baseline_current", "hybrid_b_proxy"}
    for c in candidates:
        if c.get("rejection", {}).get("rejected"):
            continue
        if c["name"] in skip_names:
            continue
        m = c["metrics"]
        meta = c.get("meta", {})
        pf_gain = m["profit_factor"] - base_pf
        if pf_gain <= 0:
            continue
        dd_gain = base_dd - m["max_drawdown_pct"]
        exp_gain = m["expectancy"] - base_exp
        wf = c.get("walkforward", {})
        robustness = 1.0 if wf.get("walkforward_pass") else 0.5 if wf.get("stable") else 0.2
        boot = c.get("bootstrap", {})
        if boot.get("pf_p05", 0) >= base_pf:
            robustness += 0.3

        simplicity = meta.get("simplicity", 5) / 10.0
        safety = meta.get("safety", 5) / 10.0
        complexity_penalty = 0.1 if meta.get("simplicity", 5) < 5 else 0.0

        # Conservative: cap PF gain contribution to avoid rewarding fragile spikes
        pf_component = min(max(pf_gain, 0), 0.25) / 0.25

        composite = (
            0.28 * robustness
            + 0.22 * simplicity
            + 0.22 * safety
            + 0.15 * pf_component
            + 0.08 * min(max(dd_gain, 0) / 20.0, 1.0)
            + 0.05 * min(max(exp_gain, 0) / 2.0, 1.0)
            - complexity_penalty
        )

        scored.append({
            **c,
            "ranking_score": round(composite, 4),
            "pf_gain": round(pf_gain, 4),
            "dd_improvement_pct": round(dd_gain, 2),
            "robustness_score": round(robustness, 2),
        })

    scored.sort(key=lambda x: x["ranking_score"], reverse=True)
    for i, s in enumerate(scored):
        s["production_rank"] = i + 1
    return scored
