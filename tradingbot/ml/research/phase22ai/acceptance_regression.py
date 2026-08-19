"""Phase 22AI — acceptance patch regression and freeze bridge validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_8_robustness_report_path,
    phase9_8_window_results_path,
    phase9_9_feature_selection_path,
    phase9_9_model_comparison_path,
)
from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric
from tradingbot.ml.research.robustness_optimizer.freeze_bridge import (
    build_freeze_contract,
    validate_authority_chain,
    validate_accepted_candidate,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import (
    _risk_improved,
    evaluate_acceptance,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _enrich_baseline(baseline: dict[str, Any], baseline_numeric: dict[str, Any]) -> dict[str, Any]:
    merged = dict(baseline)
    merged["mean_auc_gap"] = baseline_numeric.get("mean_auc_gap")
    return merged


def evaluate_acceptance_before_patch(
    best: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Historical ordinal acceptance (pre-22AI) for regression comparison."""
    current = evaluate_acceptance(best, baseline)
    checks = dict(current["checks"])
    base_risk = str(baseline.get("overfitting_risk", "HIGH"))
    best_risk = str(best.get("overfitting_risk", "HIGH"))
    checks["overfitting_risk_decreased"] = _risk_improved(base_risk, best_risk)
    passed = all(checks.values())
    return {
        **current,
        "checks": checks,
        "final_verdict": "PASS" if passed else "FAIL",
        "overfitting_check_mode": "ordinal_label",
    }


def build_acceptance_patch_diff() -> dict[str, Any]:
    return {
        "phase": "22AI",
        "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
        "function": "evaluate_acceptance",
        "before": {
            "check": "overfitting_risk_decreased",
            "logic": "RISK_ORDER[best_risk] < RISK_ORDER[baseline_risk]",
            "helper": "_risk_improved",
            "fail_mode": "HIGH baseline blocks all same-label candidates",
        },
        "after": {
            "check": "overfitting_risk_decreased",
            "logic": "candidate.mean_auc_gap exists AND candidate.mean_auc_gap < baseline.mean_auc_gap",
            "helper": "_mean_auc_gap_improved",
            "fail_mode": "fail closed when either mean_auc_gap missing (no default 0.0)",
        },
        "unchanged_checks": [
            "robustness_improved",
            "mean_expectancy_positive",
            "profitable_windows_ge_4",
            "probability_quality_passed",
        ],
        "baseline_wiring": {
            "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
            "function": "_load_phase98_baseline",
            "added_field": "mean_auc_gap from phase9_8_robustness_report train_test_gap",
        },
        "new_acceptance_fields": [
            "baseline_mean_auc_gap",
            "best_mean_auc_gap",
            "overfitting_check_mode",
        ],
    }


def run_candidate_before_after(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    before_accepted: list[str] = []
    after_accepted: list[str] = []
    changed: list[dict[str, Any]] = []
    new_pass: list[dict[str, Any]] = []
    new_fail: list[dict[str, Any]] = []

    for candidate in candidates:
        eid = str(candidate.get("experiment_id"))
        before = evaluate_acceptance_before_patch(candidate, baseline)
        after = evaluate_acceptance(candidate, baseline)

        if before["final_verdict"] == "PASS":
            before_accepted.append(eid)
        if after["final_verdict"] == "PASS":
            after_accepted.append(eid)

        if before["final_verdict"] != after["final_verdict"]:
            row = {
                "experiment_id": eid,
                "before_verdict": before["final_verdict"],
                "after_verdict": after["final_verdict"],
                "before_failed_rules": [k for k, v in before["checks"].items() if not v],
                "after_failed_rules": [k for k, v in after["checks"].items() if not v],
                "mean_auc_gap": candidate.get("mean_auc_gap"),
                "baseline_mean_auc_gap": baseline.get("mean_auc_gap"),
            }
            changed.append(row)
            if before["final_verdict"] == "FAIL" and after["final_verdict"] == "PASS":
                new_pass.append(row)
            if before["final_verdict"] == "PASS" and after["final_verdict"] == "FAIL":
                new_fail.append(row)

    return {
        "phase": "22AI",
        "candidate_count": len(candidates),
        "baseline_mean_auc_gap": baseline.get("mean_auc_gap"),
        "before": {
            "accepted_count": len(before_accepted),
            "accepted_candidates": before_accepted,
        },
        "after": {
            "accepted_count": len(after_accepted),
            "accepted_candidates": after_accepted,
        },
        "candidate_changes": changed,
        "new_pass_candidates": new_pass,
        "new_fail_candidates": new_fail,
        "expected_new_pass": ["xgb_baseline_phase96__stable_except_unstable__RANGE"],
        "expected_new_pass_met": "xgb_baseline_phase96__stable_except_unstable__RANGE" in after_accepted,
    }


def run_freeze_contract_validation(
    *,
    ranked: list[dict[str, Any]],
    baseline: dict[str, Any],
    feature_subsets: dict[str, list[str]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []

    for candidate in ranked:
        acceptance = evaluate_acceptance(candidate, baseline)
        errors = validate_accepted_candidate(
            candidate,
            acceptance,
            feature_subsets=feature_subsets,
        )
        contract = None
        if not errors:
            try:
                contract = build_freeze_contract(
                    candidate,
                    acceptance,
                    feature_subsets=feature_subsets,
                )
                contracts.append(contract)
            except Exception as exc:  # noqa: BLE001 — research report captures all rejections
                errors.append(str(exc))
        rows.append(
            {
                "experiment_id": candidate.get("experiment_id"),
                "acceptance_verdict": acceptance.get("final_verdict"),
                "validation_errors": errors,
                "contract_built": contract is not None,
            }
        )

    return {
        "phase": "22AI",
        "validated_candidates": len(rows),
        "contracts_built": len(contracts),
        "accepted_contracts": [
            {
                "experiment_id": c.get("experiment_id"),
                "candidate_id": c.get("candidate_id"),
                "model_type": c.get("model_type"),
                "feature_subset": c.get("feature_subset"),
            }
            for c in contracts
        ],
        "rows": rows,
        "sample_contract": contracts[0] if contracts else None,
    }


def determine_verdict(
    *,
    regression: dict[str, Any],
    authority: dict[str, Any],
    contract_validation: dict[str, Any],
) -> str:
    if not regression.get("expected_new_pass_met"):
        return "PATCH_DESIGN_FAILED"
    if regression["after"]["accepted_count"] < 1:
        return "PATCH_DESIGN_FAILED"
    if not authority.get("authority_chain_valid"):
        return "PATCH_DESIGN_FAILED"
    if contract_validation.get("contracts_built", 0) < 1:
        return "PATCH_DESIGN_FAILED"
    return "READY_FOR_PRODUCTION_FREEZE_WIRING"


def run_investigation(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    comparison = _load_json(phase9_9_model_comparison_path(base_dir))
    phase98_robustness = _load_json(phase9_8_robustness_report_path(base_dir))
    phase98_windows = _load_json(phase9_8_window_results_path(base_dir))
    feature_payload = _load_json(phase9_9_feature_selection_path(base_dir))

    ranked = comparison.get("ranked_candidates") or []
    baseline = _enrich_baseline(
        comparison.get("baseline_phase9_8") or {},
        load_baseline_numeric(phase98_robustness, phase98_windows),
    )
    feature_subsets = feature_payload.get("feature_subsets") or {}

    patch_diff = build_acceptance_patch_diff()
    regression = run_candidate_before_after(ranked, baseline)
    contract_validation = run_freeze_contract_validation(
        ranked=ranked,
        baseline=baseline,
        feature_subsets=feature_subsets,
    )
    authority = validate_authority_chain(
        ranked=ranked,
        baseline=baseline,
        feature_subsets=feature_subsets,
    )

    verdict = determine_verdict(
        regression=regression,
        authority=authority,
        contract_validation=contract_validation,
    )

    return {
        "acceptance_patch_diff": patch_diff,
        "candidate_before_after": regression,
        "freeze_contract_validation": contract_validation,
        "authority_check": authority,
        "verdict": verdict,
    }
