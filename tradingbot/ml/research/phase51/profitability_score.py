"""Phase 51 — profitability proximity scoring (research only)."""

from __future__ import annotations

from typing import Any


def profitability_proximity(
    *,
    strict_gate_passed: bool,
    mean_pf: float,
    mean_auc: float,
    windows_count: int,
    windows_pf_above_1_3: int,
    raw_ml_pf: float = 1.15,
    executed_pf: float = 0.31,
    label_prod_match_pct: float = 70.38,
    v7_rows: int = 0,
) -> dict[str, Any]:
    """Score 0-100: how close research evidence is to deployable profitability."""
    score = 0.0
    components: dict[str, float] = {}

    if strict_gate_passed:
        components["strict_multi_year_wf"] = 35.0
    elif mean_pf >= 1.0 and windows_count >= 3:
        components["strict_multi_year_wf"] = 20.0
    elif mean_pf >= 0.8:
        components["strict_multi_year_wf"] = 10.0
    else:
        components["strict_multi_year_wf"] = 0.0

    if mean_pf >= 1.3:
        components["mean_pf"] = 20.0
    elif mean_pf >= 1.0:
        components["mean_pf"] = 12.0
    elif mean_pf >= 0.8:
        components["mean_pf"] = 6.0
    else:
        components["mean_pf"] = 0.0

    if mean_auc >= 0.60:
        components["mean_auc"] = 15.0
    elif mean_auc >= 0.55:
        components["mean_auc"] = 10.0
    elif mean_auc >= 0.52:
        components["mean_auc"] = 5.0
    else:
        components["mean_auc"] = 0.0

    if raw_ml_pf >= 1.2:
        components["raw_ml_edge"] = 10.0
    elif raw_ml_pf >= 1.0:
        components["raw_ml_edge"] = 5.0
    else:
        components["raw_ml_edge"] = 0.0

    if label_prod_match_pct >= 85:
        components["label_alignment"] = 10.0
    elif label_prod_match_pct >= 70:
        components["label_alignment"] = 6.0
    else:
        components["label_alignment"] = 0.0

    if v7_rows >= 8000:
        components["dataset_depth"] = 10.0
    elif v7_rows >= 4000:
        components["dataset_depth"] = 6.0
    elif v7_rows >= 1500:
        components["dataset_depth"] = 3.0
    else:
        components["dataset_depth"] = 0.0

    score = round(sum(components.values()), 1)
    if score >= 80:
        band = "NEAR_PRODUCTION_CANDIDATE"
    elif score >= 60:
        band = "APPROACHING_PROFITABLE"
    elif score >= 40:
        band = "MID_RESEARCH"
    elif score >= 20:
        band = "EARLY_RESEARCH"
    else:
        band = "NOT_CLOSE"

    return {
        "proximity_score": score,
        "proximity_band": band,
        "components": components,
        "interpretation": _interpret(band, strict_gate_passed, executed_pf),
        "windows_pf_above_1_3": windows_pf_above_1_3,
    }


def _interpret(band: str, gate_passed: bool, executed_pf: float) -> str:
    if gate_passed and band in ("NEAR_PRODUCTION_CANDIDATE", "APPROACHING_PROFITABLE"):
        return (
            "Research ML may be viable; next step is read-only integration review and "
            "paper/shadow trading — not live deploy yet."
        )
    if executed_pf < 0.5:
        return (
            "ML research improving but live execution path still destroys edge. "
            "Profitability requires both better ML and execution-path validation."
        )
    return "Continue research; production deploy remains blocked."
