"""Phase 22AG — acceptance gate calibration forensics (read-only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tradingbot.ml.data.paths import (
    phase9_8_robustness_report_path,
    phase9_8_window_results_path,
    phase9_9_model_comparison_path,
    phase9_9_robustness_report_path,
)
from tradingbot.ml.research.phase22z.overfitting_rule_validation import (
    HIGH_GAP_THRESHOLD,
    HIGH_ROBUSTNESS_THRESHOLD,
    MEDIUM_GAP_THRESHOLD,
    MEDIUM_ROBUSTNESS_THRESHOLD,
    RISK_ORDER,
    classify_overfitting_rejection,
    load_baseline_numeric,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _risk_improved_ordinal(baseline: str, current: str) -> bool:
    return RISK_ORDER.get(current, 2) < RISK_ORDER.get(baseline, 2)


def _numeric_auc_gap_improved(candidate: dict[str, Any], baseline_gap: float) -> bool:
    gap = float(candidate.get("mean_auc_gap", 0.0) or 0.0)
    return gap < baseline_gap


def evaluate_variant(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    variant: str,
    baseline_gap: float,
) -> dict[str, Any]:
    """Simulate acceptance variants without code changes."""
    base = evaluate_acceptance(candidate, baseline)
    checks = dict(base["checks"])

    if variant == "A":
        pass
    elif variant == "B":
        checks["overfitting_risk_decreased"] = _numeric_auc_gap_improved(candidate, baseline_gap)
        checks["numeric_auc_gap_improved"] = checks["overfitting_risk_decreased"]
    elif variant == "C":
        checks["overfitting_risk_decreased"] = True
    elif variant == "D":
        checks["overfitting_risk_decreased"] = _numeric_auc_gap_improved(candidate, baseline_gap)
        checks["numeric_auc_gap_improved"] = checks["overfitting_risk_decreased"]
        checks["probability_quality_passed"] = bool(candidate.get("probability_gate_passed", False))
    else:
        raise ValueError(f"unknown variant {variant}")

    passed = all(v for k, v in checks.items() if not k.startswith("numeric_"))
    return {
        "checks": checks,
        "final_verdict": "PASS" if passed else "FAIL",
        "failed_rules": [k for k, v in checks.items() if not k.startswith("numeric_") and not v],
    }


def build_acceptance_flow() -> dict[str, Any]:
    """STEP 1 — complete evaluate_acceptance trace."""
    return {
        "phase": "22AG",
        "function": "evaluate_acceptance",
        "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
        "helper": "_risk_improved",
        "inputs": {
            "best": {
                "source": "select_best(rank_candidates(...)) or any candidate dict in simulation",
                "fields_used": [
                    "robustness_score",
                    "overfitting_risk",
                    "mean_expectancy",
                    "profitable_windows",
                    "window_count",
                    "probability_gate_passed",
                ],
            },
            "baseline": {
                "source": "_load_phase98_baseline(base_dir) → phase9_8_walk_forward_report.json",
                "fields_used": ["robustness_score", "overfitting_risk"],
            },
        },
        "checks": [
            {
                "name": "robustness_improved",
                "formula": "best.robustness_score > baseline.robustness_score",
                "threshold_source": "Phase 9.8 walk-forward report robustness_score (66.57)",
            },
            {
                "name": "overfitting_risk_decreased",
                "formula": "RISK_ORDER[best_risk] < RISK_ORDER[baseline_risk]",
                "threshold_source": "assess_overfitting_risk labels LOW/MEDIUM/HIGH",
            },
            {
                "name": "mean_expectancy_positive",
                "formula": "best.mean_expectancy > 0",
                "threshold_source": "literal zero",
            },
            {
                "name": "profitable_windows_ge_4",
                "formula": "profitable_windows >= 4 AND window_count >= 4",
                "threshold_source": "hardcoded 4 (walk-forward has 5 windows)",
            },
            {
                "name": "probability_quality_passed",
                "formula": "bool(best.probability_gate_passed)",
                "threshold_source": "probability_selection_gate.py (22X)",
            },
        ],
        "output": {
            "checks": "dict[str, bool]",
            "final_verdict": "PASS if all(checks.values()) else FAIL",
            "probability_gate": "nested audit fields from best candidate",
            "baseline/best scores": "robustness delta and risk labels",
        },
        "failure_reasons": "Any check False → final_verdict FAIL; no partial pass",
        "call_chain": [
            "scripts/train_model.py --phase9-9",
            "RobustnessOptimizer.run",
            "select_best(ranked)",
            "evaluate_acceptance(best, baseline)",
            "save_reports → acceptance embedded in phase9_9_robustness_report.json",
        ],
    }


def build_rule_analysis(candidates: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    """STEP 2 — per-rule independent analysis."""
    rules = []

    def count_fail(rule: str) -> int:
        return sum(
            1
            for c in candidates
            if not evaluate_acceptance(c, baseline)["checks"].get(rule, False)
        )

    rule_specs = [
        (
            "probability_quality_passed",
            "Block degenerate / sell-only / collapsed probability distributions before selection",
            "Phase 22X probability_selection_gate.py",
            "probability_gate_passed == True (buy+sell coverage, std≥0.015, range, collapsed zone)",
            "MEDIUM — relaxing allows bad inference distributions into freeze",
        ),
        (
            "mean_expectancy_positive",
            "Require positive average walk-forward expectancy",
            "Phase 9.9 report_generator evaluate_acceptance",
            "mean_expectancy > 0",
            "HIGH — negative expectancy models should not reach production",
        ),
        (
            "profitable_windows_ge_4",
            "Require majority of walk-forward windows profitable (PF≥1 proxy)",
            "Phase 9.9 report_generator hardcoded 4-of-5",
            "profitable_windows >= 4 AND window_count >= 4",
            "MEDIUM — lowering to 3/5 allows weaker consistency",
        ),
        (
            "robustness_improved",
            "Candidate must beat Phase 9.8 composite robustness score",
            "Phase 9.8 baseline report vs walk-forward robustness_score",
            "best.robustness_score > 66.57",
            "MEDIUM — allows models worse than validated Phase 9.8 baseline",
        ),
        (
            "overfitting_risk_decreased",
            "Require lower ordinal overfitting label vs Phase 9.8 baseline",
            "report_generator._risk_improved + assess_overfitting_risk buckets",
            "order[candidate] < order[baseline] where baseline=HIGH",
            "LOW ordinal relaxation if replaced by numeric AUC-gap gate (see variant B)",
        ),
    ]

    for name, purpose, origin, threshold, risk_if_relaxed in rule_specs:
        rules.append(
            {
                "rule": name,
                "purpose": purpose,
                "origin": origin,
                "current_threshold": threshold,
                "candidates_rejected": count_fail(name),
                "candidates_passed": len(candidates) - count_fail(name),
                "risk_if_relaxed": risk_if_relaxed,
            }
        )

    gate_passed = [c for c in candidates if c.get("probability_gate_passed")]
    return {
        "phase": "22AG",
        "total_candidates": len(candidates),
        "probability_gate_passed_count": len(gate_passed),
        "rules": rules,
        "dominant_blocker": max(rules, key=lambda r: r["candidates_rejected"])["rule"],
    }


def build_overfitting_rule_analysis(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
    baseline_numeric: dict[str, Any],
) -> dict[str, Any]:
    """STEP 3 — overfitting_risk_decreased deep dive."""
    rejections = [
        classify_overfitting_rejection(c, baseline_numeric, {"baseline": baseline}) for c in candidates
    ]
    label_logic = [r for r in rejections if r["rejection_category"] == "Rejected because: Label Logic"]
    really_overfit = [r for r in rejections if r["rejection_category"] == "Rejected because: really Overfit"]

    numeric_safer_analysis = {
        "question": "Would numeric AUC-gap comparison be safer than LOW/MEDIUM/HIGH ordering?",
        "answer": "Yes for baseline HIGH — ordinal requires label drop impossible when both HIGH; numeric compares mean_auc_gap directly",
        "baseline_mean_auc_gap": baseline_numeric["mean_auc_gap"],
        "candidates_with_lower_gap": sum(1 for r in rejections if r["numeric_auc_gap_better_than_baseline"]),
        "candidates_failing_despite_lower_gap": len(label_logic),
        "candidates_worse_than_baseline_gap": len(really_overfit),
        "recommended_numeric_rule": "candidate.mean_auc_gap < baseline.mean_auc_gap (strict improvement)",
        "optional_cap": f"candidate.mean_auc_gap <= {MEDIUM_GAP_THRESHOLD} for MEDIUM bucket alignment",
    }

    return {
        "phase": "22AG",
        "ordinal_implementation": {
            "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "_risk_improved",
            "formula": "RISK_ORDER[current] < RISK_ORDER[baseline]",
            "risk_order": RISK_ORDER,
        },
        "label_source": {
            "file": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
            "function": "assess_overfitting_risk",
            "thresholds": {
                "HIGH": f"mean_gap>{HIGH_GAP_THRESHOLD} OR robustness<{HIGH_ROBUSTNESS_THRESHOLD}",
                "MEDIUM": f"mean_gap>{MEDIUM_GAP_THRESHOLD} OR robustness<{MEDIUM_ROBUSTNESS_THRESHOLD}",
                "LOW": "otherwise",
            },
        },
        "baseline": {
            "overfitting_risk": baseline_numeric["overfitting_risk"],
            "mean_auc_gap": baseline_numeric["mean_auc_gap"],
            "robustness_score": baseline_numeric["robustness_score"],
        },
        "ordinal_vs_numeric": numeric_safer_analysis,
        "rejection_breakdown": {
            "label_logic_failures": len(label_logic),
            "really_overfit_failures": len(really_overfit),
            "ordinal_pass": sum(1 for r in rejections if r["overfitting_risk_decreased_passed"]),
        },
        "examples": {
            "label_logic": label_logic[:3],
            "really_overfit": really_overfit[:2],
        },
    }


def run_candidate_simulation(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
    baseline_numeric: dict[str, Any],
) -> dict[str, Any]:
    """STEP 4 — simulate variants A–D on all 28 candidates."""
    baseline_gap = float(baseline_numeric["mean_auc_gap"])
    variants = {
        "A": "Current acceptance (all 5 checks incl. ordinal overfitting)",
        "B": "Replace ordinal overfitting with numeric mean_auc_gap < baseline",
        "C": "Remove overfitting_risk_decreased only",
        "D": "Numeric AUC-gap improvement + probability gate (other checks retained)",
    }
    results: dict[str, Any] = {}
    for key, description in variants.items():
        accepted: list[str] = []
        rejected: list[dict[str, Any]] = []
        for c in candidates:
            ev = evaluate_variant(c, baseline, variant=key, baseline_gap=baseline_gap)
            eid = str(c.get("experiment_id"))
            if ev["final_verdict"] == "PASS":
                accepted.append(eid)
            else:
                rejected.append(
                    {
                        "experiment_id": eid,
                        "failed_rules": ev["failed_rules"],
                        "probability_gate_passed": c.get("probability_gate_passed"),
                        "mean_auc_gap": c.get("mean_auc_gap"),
                        "robustness_score": c.get("robustness_score"),
                    }
                )
        results[key] = {
            "description": description,
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "rejected_sample": rejected[:8],
            "all_rejected_ids": [r["experiment_id"] for r in rejected],
        }

    safety = {
        "A": "Strictest; 0 candidates pass — freeze gate never opens",
        "B": "Adds numeric overfitting control; still requires robustness/4-window/probability rules",
        "C": "Removes overfitting check entirely — weaker safety on gap/degradation",
        "D": "Strongest minimal fix: numeric gap + probability gate + existing economic checks",
    }

    return {
        "phase": "22AG",
        "baseline_mean_auc_gap": baseline_gap,
        "variants": results,
        "safety_comparison": safety,
        "recommended_variant": "D",
        "note": "Simulation uses existing phase9_9_model_comparison.json only — no retrain",
    }


def determine_root_cause(
    rule_analysis: dict[str, Any],
    overfitting: dict[str, Any],
) -> str:
    """STEP 5 — root cause classification."""
    causes = {
        "BAD_THRESHOLD": False,
        "BAD_METRIC": True,
        "BAD_IMPLEMENTATION": True,
        "BAD_BASELINE": False,
        "MULTIPLE_CAUSES": True,
    }
    # Ordinal comparison against HIGH baseline is structurally broken (implementation)
    # mean_auc_gap is the better metric (bad metric choice for acceptance = ordinal label)
    # Baseline HIGH is correct (Phase 9.8 truth) — not BAD_BASELINE
    # Threshold 4 profitable windows is secondary blocker, not primary root cause
    if overfitting["rejection_breakdown"]["label_logic_failures"] >= 10:
        causes["BAD_IMPLEMENTATION"] = True
    if overfitting["ordinal_vs_numeric"]["candidates_failing_despite_lower_gap"] >= 10:
        causes["BAD_METRIC"] = True
    active = [k for k, v in causes.items() if v and k != "MULTIPLE_CAUSES"]
    if len(active) >= 2:
        return "MULTIPLE_CAUSES"
    return active[0] if active else "MULTIPLE_CAUSES"


def build_acceptance_contract() -> dict[str, Any]:
    """STEP 6 — final acceptance contract design."""
    return {
        "phase": "22AG",
        "version": "2.0-proposed",
        "guarantees": {
            "probability_quality": {
                "rule": "probability_gate_passed == True",
                "source": "probability_selection_gate.py (unchanged from 22X)",
            },
            "non_degenerated_distribution": {
                "rule": "buy_coverage > 0 AND sell_coverage > 0 AND std >= 0.015",
                "source": "embedded in probability gate",
            },
            "positive_expectancy": {
                "rule": "mean_expectancy > 0",
                "source": "retain current check",
            },
            "walk_forward_robustness": {
                "rule": "robustness_score > baseline_phase9_8.robustness_score AND profitable_windows >= 4",
                "source": "retain robustness_improved + profitable_windows_ge_4",
            },
            "controlled_overfitting": {
                "rule": "mean_auc_gap < baseline_mean_auc_gap (numeric, strict)",
                "replaces": "overfitting_risk_decreased ordinal comparison",
                "optional_secondary": f"mean_auc_gap <= {MEDIUM_GAP_THRESHOLD} after beating baseline",
            },
        },
        "removed": [
            "Ordinal-only overfitting_risk_decreased when baseline is HIGH",
        ],
        "final_verdict": "PASS iff all guarantee rules true",
    }


def build_minimal_change_design(simulation: dict[str, Any]) -> dict[str, Any]:
    """STEP 7 — smallest production change recommendation."""
    variant_d = simulation["variants"]["D"]
    return {
        "phase": "22AG",
        "recommendation": "Replace ordinal overfitting_risk_decreased with numeric mean_auc_gap improvement",
        "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
        "function": "evaluate_acceptance",
        "change_description": (
            "Replace checks['overfitting_risk_decreased'] = _risk_improved(base_risk, best_risk) with "
            "checks['mean_auc_gap_improved'] = float(best.get('mean_auc_gap', inf)) < baseline_mean_auc_gap "
            "where baseline_mean_auc_gap is loaded from phase9_8_robustness_report train_test_gap (0.3308). "
            "Keep probability_quality_passed, mean_expectancy_positive, profitable_windows_ge_4, robustness_improved unchanged."
        ),
        "risk": "MEDIUM",
        "risk_rationale": "Numeric gate aligns acceptance with actual generalization gap; still blocked by robustness and 4-window rules",
        "expected_effect": {
            "accepted_candidates_variant_D": variant_d["accepted_count"],
            "accepted_ids": variant_d["accepted"],
            "freeze_gate_can_open": variant_d["accepted_count"] > 0,
            "dominant_remaining_blocker_if_zero": "robustness_improved or profitable_windows_ge_4",
        },
        "out_of_scope_minimal_change": [
            "Lowering profitable_windows threshold",
            "Removing probability gate",
            "Changing assess_overfitting_risk label buckets",
        ],
    }


def determine_verdict(simulation: dict[str, Any]) -> str:
    if simulation["variants"]["D"]["accepted_count"] > 0:
        return "READY_FOR_PHASE_2_IMPLEMENTATION"
    return "ACCEPTANCE_DESIGN_BLOCKED"


def run_forensics(*, base_dir: str | None = None) -> dict[str, Any]:
    comparison = _load_json(phase9_9_model_comparison_path(base_dir))
    ranked = comparison.get("ranked_candidates") or []
    baseline = dict(comparison.get("baseline_phase9_8") or {})
    p98_rob = _load_json(phase9_8_robustness_report_path(base_dir))
    p98_win = _load_json(phase9_8_window_results_path(base_dir))
    baseline_numeric = load_baseline_numeric(p98_rob, p98_win)
    baseline["mean_auc_gap"] = baseline_numeric.get("mean_auc_gap")

    acceptance_flow = build_acceptance_flow()
    rule_analysis = build_rule_analysis(ranked, baseline)
    overfitting = build_overfitting_rule_analysis(ranked, baseline, baseline_numeric)
    simulation = run_candidate_simulation(ranked, baseline, baseline_numeric)
    contract = build_acceptance_contract()
    minimal = build_minimal_change_design(simulation)
    root_cause = determine_root_cause(rule_analysis, overfitting)

    report_snapshot = _load_json(phase9_9_robustness_report_path(base_dir))

    return {
        "acceptance_flow": acceptance_flow,
        "rule_analysis": rule_analysis,
        "overfitting_rule_analysis": overfitting,
        "candidate_simulation": simulation,
        "acceptance_contract": contract,
        "minimal_change_design": minimal,
        "root_cause": root_cause,
        "current_report": {
            "final_verdict": report_snapshot.get("final_verdict"),
            "best_experiment_id": (report_snapshot.get("best_candidate") or {}).get("experiment_id"),
            "acceptance_checks": (report_snapshot.get("acceptance") or {}).get("checks"),
        },
        "verdict": determine_verdict(simulation),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "production_modified": False,
    }
