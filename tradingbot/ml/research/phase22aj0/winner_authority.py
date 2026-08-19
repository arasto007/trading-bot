"""Phase 22AJ0 — winner authority resolution (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_8_robustness_report_path,
    phase9_8_window_results_path,
    phase9_9_model_comparison_path,
    phase9_9_robustness_report_path,
)
from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric
from tradingbot.ml.research.robustness_optimizer.candidate_selector import (
    PRODUCTION_WINNER_RULE,
    select_best,
    select_production_winner,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

PROJECT_ROOT = Path(__file__).resolve().parents[4]

PRODUCTION_RULE_ID = "ACCEPTANCE_PASS_HIGHEST_COMPOSITE"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _enrich_baseline(baseline: dict[str, Any], baseline_numeric: dict[str, Any]) -> dict[str, Any]:
    merged = dict(baseline)
    merged["mean_auc_gap"] = baseline_numeric.get("mean_auc_gap")
    return merged


def build_winner_authority_trace() -> dict[str, Any]:
    """STEP 1 — every place that defines 'best candidate'."""
    return {
        "phase": "22AJ0",
        "definitions": [
            {
                "name": "rank_number_one",
                "component": "rank_candidates() sorted list",
                "file": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
                "function": "rank_candidates",
                "rule": (
                    "ranked[0] after sort by (probability_gate_passed asc, -composite_score, "
                    "-robustness_score, overfitting_risk asc, -profitable_windows)"
                ),
                "filters": "Does not exclude failed probability gate — rank #1 may fail gate",
                "stored_in": "phase9_9_model_comparison.json ranked_candidates[0]",
                "role": "Ranking display / composite ordering",
            },
            {
                "name": "select_best",
                "component": "Optimizer selection",
                "file": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
                "function": "select_best",
                "rule": "First row in ranked list where probability_gate_passed == True",
                "equivalent_to": "Highest composite among probability-gate passers (given rank_candidates sort order)",
                "stored_in": "RobustnessOptimizationResult.best_candidate; phase9_9_robustness_report.json best_candidate",
                "wired_by": "optimization_orchestrator.py line ~141: best = select_best(ranked)",
                "role": "Current optimizer 'winner' written to reports",
            },
            {
                "name": "evaluate_acceptance",
                "component": "Acceptance gate",
                "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                "function": "evaluate_acceptance",
                "rule": "All checks true: robustness_improved, numeric mean_auc_gap, mean_expectancy>0, profitable_windows>=4, probability_quality_passed",
                "current_wiring": "Called ONLY on select_best output in optimization_orchestrator.py — not per-candidate scan",
                "stored_in": "phase9_9_robustness_report.json acceptance",
                "role": "Binary PASS/FAIL gate on one candidate today",
            },
            {
                "name": "freeze_bridge_prototype",
                "component": "Research freeze contract builder",
                "file": "tradingbot/ml/research/robustness_optimizer/freeze_bridge.py",
                "function": "validate_authority_chain / build_freeze_contract",
                "rule": "Prototype scans ALL ranked rows for acceptance PASS; builds contract on first accepted (Phase 22AI)",
                "note": "Differs from orchestrator which evaluates acceptance only on select_best",
                "role": "Research prototype — not production freeze writer",
            },
            {
                "name": "future_freeze_target",
                "component": "Phase 22AF authority redesign",
                "file": "tradingbot/ml/research/phase22af/authority_redesign.json",
                "rule": "select_best → evaluate_acceptance PASS → FreezeContract → registry (design intent)",
                "current_gap": "select_best winner fails acceptance on current 28-candidate artifact set",
                "production_freeze_today": "model_registry.freeze_phase9_9_artifacts uses DEFAULT_CONFIG / logistic_strong_reg — unrelated to optimizer",
                "role": "Target production write authority (not yet wired)",
            },
            {
                "name": "runtime_artifact",
                "component": "Frozen bundle on disk",
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "function": "load_phase9_9_bundle / freeze_phase9_9_artifacts",
                "rule": "Runtime reads phase9_9_best/*; freeze writes hardcoded DEFAULT_CONFIG candidate",
                "role": "Runtime inference authority (read-only load); NOT optimizer winner today",
            },
        ],
        "conflicts_detected": [
            {
                "between": ["select_best", "evaluate_acceptance (per-candidate potential)"],
                "evidence": "select_best=random_forest_shallow__stable_4__RANGE; only acceptance PASS=xgb_baseline_phase96__stable_except_unstable__RANGE",
            },
            {
                "between": ["report best_candidate", "freeze_bridge prototype scan"],
                "evidence": "Report stores select_best; freeze_bridge Phase 22AI built contract from acceptance PASS scan",
            },
            {
                "between": ["optimizer winner", "model_registry DEFAULT_CONFIG freeze"],
                "evidence": "Phase 22AE/22AB: freeze never reads select_best or best_candidate.candidate_id",
            },
        ],
    }


def evaluate_authority_options(
    ranked: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """STEP 2 — score repository-supported authority options A–D."""
    select_best_row = select_best(ranked)
    rank_one = ranked[0] if ranked else None

    option_a_winner = select_best_row or rank_one
    option_a_id = (option_a_winner or {}).get("experiment_id")

    acceptance_pass_rows: list[dict[str, Any]] = []
    for candidate in ranked:
        acceptance = evaluate_acceptance(candidate, baseline)
        if acceptance.get("final_verdict") == "PASS":
            acceptance_pass_rows.append({"candidate": candidate, "acceptance": acceptance})

    option_b_ids = [row["candidate"]["experiment_id"] for row in acceptance_pass_rows]

    option_c_rows = sorted(
        acceptance_pass_rows,
        key=lambda row: float(row["candidate"].get("composite_score", 0.0) or 0.0),
        reverse=True,
    )
    option_c_winner = option_c_rows[0]["candidate"] if option_c_rows else None
    option_c_id = option_c_winner.get("experiment_id") if option_c_winner else None

    orchestrator_acceptance = (
        evaluate_acceptance(select_best_row, baseline) if select_best_row else {"final_verdict": "FAIL"}
    )
    current_orchestrator_rule = {
        "description": "select_best then evaluate_acceptance on that row only (existing orchestrator)",
        "winner_id": option_a_id,
        "acceptance_verdict": orchestrator_acceptance.get("final_verdict"),
        "production_eligible": orchestrator_acceptance.get("final_verdict") == "PASS",
    }

    return {
        "phase": "22AJ0",
        "options": {
            "A_highest_composite_among_probability_gate": {
                "rule": "select_best(ranked) — highest composite with probability_gate_passed",
                "winner_experiment_id": option_a_id,
                "acceptance_pass": orchestrator_acceptance.get("final_verdict") == "PASS",
                "production_eligible_count": 1 if orchestrator_acceptance.get("final_verdict") == "PASS" else 0,
                "repository_support": [
                    "candidate_selector.select_best",
                    "optimization_orchestrator saves best_candidate from select_best",
                ],
                "gap": "Fails acceptance on current artifact set — freeze gate never opens",
            },
            "B_acceptance_pass_only": {
                "rule": "Any candidate where evaluate_acceptance == PASS",
                "pass_count": len(option_b_ids),
                "pass_experiment_ids": option_b_ids,
                "repository_support": [
                    "report_generator.evaluate_acceptance",
                    "phase22af acceptance-gated freeze design",
                ],
                "gap": "Multiple passes would be ambiguous without tie-break (not case today: count=1)",
            },
            "C_acceptance_pass_highest_composite": {
                "rule": "argmax(composite_score) WHERE acceptance PASS AND probability_gate_passed",
                "winner_experiment_id": option_c_id,
                "pass_count": len(option_b_ids),
                "repository_support": [
                    "phase22af design_principles: acceptance-gated freeze only",
                    "candidate_selector composite_score tie-break already used in rank_candidates",
                    "phase22ai freeze_bridge requires acceptance PASS before contract",
                    "Resolves select_best vs acceptance conflict deterministically",
                ],
                "recommended": True,
            },
            "D_existing_orchestrator_sequential": {
                "rule": "select_best → evaluate_acceptance(same row) → freeze if PASS",
                "current_implementation": current_orchestrator_rule,
                "repository_support": ["optimization_orchestrator.py current wiring"],
                "gap": "Yields 0 production-eligible candidates on current 28-candidate artifact set",
            },
        },
        "recommended_option": "C",
        "recommendation_rationale": (
            "Repository evidence: Phase 22AF mandates acceptance-gated freeze; composite_score is the "
            "existing optimizer ranking metric; probability gate is already enforced. Option C is the "
            "only option that yields exactly one production-eligible winner on current artifacts while "
            "aligning acceptance safety with ranking tie-break."
        ),
    }


def build_candidate_eligibility_table(
    ranked: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """STEP 3 — simulate all candidates."""
    select_best_id = (select_best(ranked) or {}).get("experiment_id")
    rows: list[dict[str, Any]] = []

    for rank_index, candidate in enumerate(ranked, start=1):
        acceptance = evaluate_acceptance(candidate, baseline)
        probability_gate = bool(candidate.get("probability_gate_passed"))
        acceptance_pass = acceptance.get("final_verdict") == "PASS"
        production_eligible = acceptance_pass and probability_gate

        rows.append(
            {
                "rank": rank_index,
                "experiment_id": candidate.get("experiment_id"),
                "candidate_id": candidate.get("candidate_id"),
                "feature_subset": candidate.get("feature_subset"),
                "acceptance_verdict": acceptance.get("final_verdict"),
                "acceptance_failed_rules": [k for k, v in acceptance["checks"].items() if not v],
                "probability_gate_passed": probability_gate,
                "composite_score": candidate.get("composite_score"),
                "mean_profit_factor": candidate.get("mean_profit_factor"),
                "robustness_score": candidate.get("robustness_score"),
                "mean_auc_gap": candidate.get("mean_auc_gap"),
                "is_select_best": candidate.get("experiment_id") == select_best_id,
                "is_rank_one": rank_index == 1,
                "production_eligible": production_eligible,
            }
        )

    eligible = [row for row in rows if row["production_eligible"]]
    production_winner = select_production_winner(ranked, baseline)

    return {
        "phase": "22AJ0",
        "candidate_count": len(rows),
        "rows": rows,
        "production_eligible_count": len(eligible),
        "production_eligible_ids": [row["experiment_id"] for row in eligible],
        "select_best_experiment_id": select_best_id,
        "resolved_production_winner": production_winner.get("experiment_id") if production_winner else None,
    }


def build_production_rule() -> dict[str, Any]:
    """STEP 4 — single deterministic production rule."""
    return {
        "phase": "22AJ0",
        "rule_id": PRODUCTION_WINNER_RULE,
        "rule_name": "Acceptance PASS with highest composite score",
        "formal_definition": {
            "ProductionWinner": "argmax(composite_score)",
            "WHERE": [
                "evaluate_acceptance(candidate, baseline).final_verdict == PASS",
                "candidate.probability_gate_passed == True",
            ],
            "ORDER_BY": "composite_score DESC",
            "TIE_BREAK": "rank_candidates sort order (robustness_score, overfitting_risk, profitable_windows)",
        },
        "ascii": (
            "ProductionWinner :=\n"
            "  argmax(composite_score)\n"
            "  WHERE evaluate_acceptance(candidate, baseline) == PASS\n"
            "    AND probability_gate_passed == True"
        ),
        "supersedes": [
            "select_best alone (Option A) — insufficient without acceptance PASS",
            "report best_candidate field alone — must be rewritten to resolved ProductionWinner at freeze wiring",
            "DEFAULT_CONFIG freeze candidate — eliminated at production integration",
        ],
        "orchestrator_change_required": (
            "Replace best = select_best(ranked) with select_production_winner(ranked, baseline) "
            "before evaluate_acceptance and save_reports at freeze wiring phase"
        ),
    }


def build_authority_resolution(
    *,
    winner_trace: dict[str, Any],
    options: dict[str, Any],
    eligibility: dict[str, Any],
    production_rule: dict[str, Any],
    report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """STEP 5 — verify ambiguity resolved."""
    eligible_count = eligibility["production_eligible_count"]
    resolved_winner = eligibility.get("resolved_production_winner")
    report_best = (report_snapshot.get("best_candidate") or {}).get("experiment_id")
    select_best_id = eligibility.get("select_best_experiment_id")

    ambiguity_resolved = eligible_count == 1 and resolved_winner is not None
    current_report_matches_rule = report_best == resolved_winner

    return {
        "phase": "22AJ0",
        "current_state": {
            "report_best_candidate_experiment_id": report_best,
            "select_best_experiment_id": select_best_id,
            "orchestrator_acceptance_on_select_best_only": True,
            "report_matches_select_best": report_best == select_best_id,
            "report_matches_production_rule": current_report_matches_rule,
        },
        "conflicts": winner_trace.get("conflicts_detected", []),
        "resolved_authority": {
            "single_source_of_truth": "select_production_winner (rule ACCEPTANCE_PASS_HIGHEST_COMPOSITE)",
            "module": "tradingbot/ml/research/phase22aj0/winner_authority.py",
            "function": "select_production_winner",
            "production_winner_experiment_id": resolved_winner,
            "unique_winner": ambiguity_resolved,
            "eligible_count": eligible_count,
        },
        "recommended_option": options.get("recommended_option"),
        "production_rule_id": production_rule.get("rule_id"),
        "ambiguity_resolved": ambiguity_resolved,
        "wiring_gaps_before_production": [
            "optimization_orchestrator still uses select_best not select_production_winner",
            "model_registry freeze still uses DEFAULT_CONFIG",
            "report best_candidate field still reflects select_best",
        ],
    }


def determine_verdict(resolution: dict[str, Any]) -> str:
    if resolution.get("ambiguity_resolved") and resolution.get("resolved_authority", {}).get("unique_winner"):
        return "SINGLE_AUTHORITY_DEFINED"
    return "AUTHORITY_CONFLICT"


def run_investigation(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    comparison = _load_json(phase9_9_model_comparison_path(base_dir))
    phase98_robustness = _load_json(phase9_8_robustness_report_path(base_dir))
    phase98_windows = _load_json(phase9_8_window_results_path(base_dir))
    report_snapshot = _load_json(phase9_9_robustness_report_path(base_dir))

    ranked = comparison.get("ranked_candidates") or []
    baseline = _enrich_baseline(
        comparison.get("baseline_phase9_8") or {},
        load_baseline_numeric(phase98_robustness, phase98_windows),
    )

    winner_trace = build_winner_authority_trace()
    options = evaluate_authority_options(ranked, baseline)
    eligibility = build_candidate_eligibility_table(ranked, baseline)
    production_rule = build_production_rule()
    resolution = build_authority_resolution(
        winner_trace=winner_trace,
        options=options,
        eligibility=eligibility,
        production_rule=production_rule,
        report_snapshot=report_snapshot,
    )
    verdict = determine_verdict(resolution)

    return {
        "winner_authority": winner_trace,
        "candidate_eligibility_table": eligibility,
        "authority_resolution": resolution,
        "authority_options": options,
        "production_rule": production_rule,
        "verdict": verdict,
    }


def build_final_report(result: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    resolution = result["authority_resolution"]
    eligibility = result["candidate_eligibility_table"]
    return {
        "phase": "22AJ0",
        "title": "Winner Authority Resolution",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "summary": (
            "Current code defines three conflicting 'best' notions: rank/select_best "
            f"({eligibility.get('select_best_experiment_id')}), report best_candidate (same), "
            f"and acceptance-eligible winner ({eligibility.get('resolved_production_winner')}). "
            "Deterministic production rule: Acceptance PASS + highest composite → exactly one winner."
        ),
        "production_rule": result["production_rule"]["ascii"],
        "production_winner": eligibility.get("resolved_production_winner"),
        "select_best_winner": eligibility.get("select_best_experiment_id"),
        "report_best_candidate": resolution["current_state"]["report_best_candidate_experiment_id"],
        "recommended_option": result["authority_options"]["recommended_option"],
        "wiring_gaps": resolution.get("wiring_gaps_before_production", []),
    }
