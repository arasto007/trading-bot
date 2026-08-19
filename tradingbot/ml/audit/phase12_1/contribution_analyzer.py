"""Phase 12.1 — strategy agreement and conflict analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.audit.phase12_1.replay_analyzer import analyze_replay


def analyze_contribution(
    *,
    paper_run_id: str = "phase11_v1",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    replay = analyze_replay(paper_run_id=paper_run_id, base_dir=base_dir)
    signals = replay["signals"]
    ml_gen = signals["phase9_9_ml_generated"]
    legacy_gen = signals["legacy_priceaction_generated"]
    ml_final = signals["final_ml_selected"]
    legacy_final = signals["final_legacy_selected"]
    agreement = replay["agreement_cycles"]
    conflict = replay["conflict_cycles"]

    comparable = agreement + conflict
    agreement_rate = round(agreement / comparable, 4) if comparable else 0.0
    conflict_rate = round(conflict / comparable, 4) if comparable else 0.0

    total_final = ml_final + legacy_final
    ml_contribution_pct = round(ml_final / max(1, total_final), 4)
    legacy_contribution_pct = round(legacy_final / max(1, total_final), 4)

    dominant = replay["dominant_final_source"]
    return {
        "agreement_rate": agreement_rate,
        "conflict_rate": conflict_rate,
        "agreement_cycles": agreement,
        "conflict_cycles": conflict,
        "ml_contribution_percentage": ml_contribution_pct * 100,
        "legacy_contribution_percentage": legacy_contribution_pct * 100,
        "dominant_strategy": dominant,
        "signals_generated": {
            "ml": ml_gen,
            "legacy": legacy_gen,
        },
        "signals_selected_as_final": {
            "ml": ml_final,
            "legacy": legacy_final,
        },
        "decision_mechanism": {
            "type": "ML_PRIORITY_OVERRIDE",
            "ml_weight_when_active": "100%",
            "legacy_weight_when_ml_hold": "100%",
            "voting": False,
            "confidence_weighting": False,
            "description": "ML non-HOLD overrides legacy; no ensemble fusion.",
        },
    }
