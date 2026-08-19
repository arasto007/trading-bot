"""Phase 22AB — freeze path authority forensics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance


def build_freeze_call_graph() -> dict[str, Any]:
    return {
        "phase": "22AB",
        "anchor_function": "freeze_phase9_9_artifacts",
        "anchor_file": "tradingbot/ml/paper_trading/model_registry.py",
        "direct_callers": [
            {
                "path": "tradingbot/ml/paper_trading/model_registry.py",
                "function": "load_phase9_9_bundle",
                "entry_point": "build_if_missing=True and model.pkl absent",
                "cli_path": "none (library call)",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A — acceptance not loaded",
                "trigger": "indirect via load_phase9_9_bundle → freeze_phase9_9_artifacts",
            },
            {
                "path": "tradingbot/ml/paper_trading/shadow_engine.py",
                "function": "ShadowEngine.run",
                "entry_point": "load_phase9_9_bundle(build_if_missing=True, training_df=raw)",
                "cli_path": "Phase 9.10 shadow run (not train_model --phase9-9)",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tradingbot/ml/integration/kernel_shadow_runner.py",
                "function": "KernelShadowRunner._ensure_artifacts",
                "entry_point": "KernelShadowRunner.run when model.pkl missing",
                "cli_path": "kernel shadow integration",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tradingbot/ml/shadow/ml_adapter.py",
                "function": "MLAdapter.load",
                "entry_point": "load_phase9_9_bundle(build_if_missing=training_df is not None)",
                "cli_path": "MLAdapter.load with training_df",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tests/test_ml_paper_phase9_10.py",
                "function": "multiple test methods",
                "entry_point": "unit tests",
                "cli_path": "pytest",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tests/test_ml_phase10_1_kernel_bridge.py",
                "function": "test setup",
                "entry_point": "unit tests",
                "cli_path": "pytest",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tests/test_ml_phase10_2_live_shadow.py",
                "function": "test setup",
                "entry_point": "unit tests",
                "cli_path": "pytest",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tests/test_ml_phase11_paper.py",
                "function": "test setup",
                "entry_point": "unit tests",
                "cli_path": "pytest",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tests/test_ml_shadow_phase10.py",
                "function": "test setup",
                "entry_point": "unit tests",
                "cli_path": "pytest",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
            {
                "path": "tests/test_ml_phase10_4_monitoring.py",
                "function": "test setup",
                "entry_point": "unit tests",
                "cli_path": "pytest",
                "acceptance_available": False,
                "acceptance_checked": False,
                "acceptance_ignored": "N/A",
            },
        ],
        "explicitly_not_calling_freeze": [
            {
                "path": "scripts/train_model.py",
                "function": "main --phase9-9",
                "note": "Calls RobustnessOptimizer.run only; never freeze_phase9_9_artifacts",
            },
            {
                "path": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                "function": "RobustnessOptimizer.run",
                "note": "Ends at save_reports + acceptance; no import of model_registry freeze",
            },
        ],
        "load_only_no_freeze": [
            "tradingbot/ml/integration/health_gate.py",
            "tradingbot/ml/integration/pipeline_cache.py",
            "tradingbot/ml/phase15a/engine_registry.py",
            "tradingbot/ml/research/regime_router/range_engine_adapter.py",
        ],
    }


def build_acceptance_vs_freeze_flow() -> dict[str, Any]:
    return {
        "phase": "22AB",
        "diagram_ascii": (
            "Candidate Grid (28 experiments)\n"
            "        ↓\n"
            "Per-window Validation (walk-forward)\n"
            "        ↓\n"
            "Ranking (composite score + probability gate for select_best)\n"
            "        ↓\n"
            "Acceptance (evaluate_acceptance vs Phase 9.8)  ←── train_model --phase9-9 STOPS HERE\n"
            "        ↓ writes JSON only\n"
            "        ✂ BYPASS — no code path to freeze\n"
            "        ↓\n"
            "freeze_phase9_9_artifacts (separate Phase 9.10 registry)\n"
            "        ↓ hardcoded DEFAULT_CONFIG logistic_strong_reg\n"
            "        ↓ model.pkl / scaler.pkl / metadata.json\n"
            "        ↓\n"
            "load_phase9_9_bundle → production / shadow / health (read frozen artifact)"
        ),
        "branches": [
            {
                "name": "phase9_9_research_pipeline",
                "path": "train_model.py --phase9-9 → RobustnessOptimizer → evaluate_acceptance",
                "produces": ["phase9_9_robustness_report.json", "exit code"],
                "calls_freeze": False,
            },
            {
                "name": "phase9_10_freeze_pipeline",
                "path": "freeze_phase9_9_artifacts OR load(build_if_missing=True)",
                "produces": ["data/ml/research/phase9_9_best/*"],
                "reads_acceptance": False,
                "bypass_point": "Entire acceptance stage skipped",
            },
        ],
        "acceptance_bypass_locations": [
            "optimization_orchestrator.py does not import freeze",
            "freeze_phase9_9_artifacts uses DEFAULT_CONFIG not select_best() output",
            "load_phase9_9_bundle(build_if_missing=True) freezes without acceptance",
            "KernelShadowRunner._ensure_artifacts freezes if model.pkl missing",
        ],
    }


def build_historical_freeze_evidence(
    *,
    metadata: dict[str, Any],
    config: dict[str, Any],
    comparison: dict[str, Any],
    robustness_report: dict[str, Any],
    model_path_exists: bool,
) -> dict[str, Any]:
    ranked = comparison.get("ranked_candidates") or []
    baseline = comparison.get("baseline_phase9_8") or {}
    logistic = next(
        (c for c in ranked if c.get("experiment_id") == "logistic_strong_reg__stable_top3__RANGE"),
        {},
    )
    logistic_acceptance = evaluate_acceptance(logistic, baseline) if logistic else {}
    current_best = robustness_report.get("best_candidate") or {}
    acceptance = robustness_report.get("acceptance") or {}

    return {
        "frozen_artifact_metadata": metadata,
        "frozen_artifact_config": config,
        "model_pkl_present": model_path_exists,
        "artifact_files_present": {
            "metadata.json": True,
            "config.json": True,
            "feature_order.json": True,
            "model.pkl": model_path_exists,
            "scaler.pkl": model_path_exists,
        },
        "frozen_candidate_id": metadata.get("candidate_id"),
        "frozen_at_utc": metadata.get("frozen_at_utc"),
        "frozen_robustness_score_in_metadata": metadata.get("robustness_score"),
        "current_report_generated_utc": robustness_report.get("generated_at_utc"),
        "current_acceptance_verdict": acceptance.get("final_verdict"),
        "current_best_candidate_experiment_id": current_best.get("experiment_id"),
        "frozen_matches_current_best": metadata.get("candidate_id") == current_best.get("candidate_id"),
        "frozen_matches_hardcoded_default_config": (
            metadata.get("candidate_id") == "logistic_strong_reg"
            and config.get("features") == ["ema50_slope", "candle_direction", "structure_distance"]
        ),
        "logistic_strong_reg_stable_top3_current_metrics": {
            "robustness_score": logistic.get("robustness_score"),
            "overfitting_risk": logistic.get("overfitting_risk"),
            "mean_profit_factor": logistic.get("mean_profit_factor"),
            "probability_gate_passed": logistic.get("probability_gate_passed"),
            "acceptance_verdict_if_evaluated_now": logistic_acceptance.get("final_verdict"),
            "acceptance_checks_now": logistic_acceptance.get("checks"),
        },
        "was_frozen_winner_accepted": "UNKNOWN_AT_FREEZE_TIME — metadata stores no acceptance verdict",
        "was_frozen_winner_accepted_now": logistic_acceptance.get("final_verdict"),
        "evidence_at_freeze_trigger": {
            "function": "freeze_phase9_9_artifacts",
            "hardcoded_candidate": "logistic_strong_reg",
            "hardcoded_features": config.get("features"),
            "robustness_score_source": "_load_phase99_score reads best_candidate.robustness_score from report at freeze time (not acceptance)",
            "acceptance_gate_in_freeze_code": False,
        },
        "timeline_note": (
            "metadata.frozen_at_utc=2026-06-29 predates current phase9_9_robustness_report "
            f"generated_at_utc={robustness_report.get('generated_at_utc')}. "
            "Report was overwritten by later Phase 9.9 runs; acceptance verdict at original freeze time is not persisted."
        ),
    }


def build_freeze_guard_analysis() -> dict[str, Any]:
    guards = [
        {
            "guard": "acceptance_guard",
            "location": "freeze_phase9_9_artifacts",
            "status": "MISSING",
            "evidence": "No import or call to evaluate_acceptance in model_registry.py",
        },
        {
            "guard": "robustness_guard",
            "location": "freeze_phase9_9_artifacts",
            "status": "INACTIVE",
            "evidence": "_load_phase99_score copies robustness_score into metadata only; does not block freeze",
        },
        {
            "guard": "probability_quality_guard",
            "location": "freeze_phase9_9_artifacts",
            "status": "MISSING",
            "evidence": "No probability_gate check before freeze",
        },
        {
            "guard": "manual_override",
            "location": "freeze_phase9_9_artifacts(config=...)",
            "status": "ACTIVE",
            "evidence": "Optional config parameter overrides DEFAULT_CONFIG",
        },
        {
            "guard": "cli_override",
            "location": "train_model --phase9-9",
            "status": "MISSING",
            "evidence": "CLI does not expose freeze; cannot pass acceptance result",
        },
        {
            "guard": "environment_variable_override",
            "location": "repository search",
            "status": "MISSING",
            "evidence": "No env var gates freeze_phase9_9_artifacts in model_registry.py",
        },
        {
            "guard": "hardcoded_path",
            "location": "DEFAULT_CONFIG + ModelCandidateConfig(logistic_strong_reg)",
            "status": "ACTIVE",
            "evidence": "Freeze always trains hardcoded logistic model regardless of rank/acceptance",
        },
        {
            "guard": "build_if_missing_auto_freeze",
            "location": "load_phase9_9_bundle",
            "status": "ACTIVE",
            "evidence": "Automatically calls freeze when model.pkl absent",
        },
    ]
    return {"phase": "22AB", "guards": guards}


def build_freeze_authority_classification() -> dict[str, Any]:
    return {
        "phase": "22AB",
        "options": {
            "A_acceptance_must_pass_before_freeze": False,
            "B_acceptance_advisory_only": False,
            "C_freeze_ignores_acceptance_entirely": True,
            "D_multiple_freeze_paths_exist": True,
        },
        "proof": {
            "C": [
                "freeze_phase9_9_artifacts has zero references to evaluate_acceptance",
                "RobustnessOptimizer.run never calls freeze",
                "train_model --phase9-9 exit code does not gate freeze",
            ],
            "D": [
                "Direct: freeze_phase9_9_artifacts() in tests and KernelShadowRunner",
                "Indirect: load_phase9_9_bundle(build_if_missing=True) in ShadowEngine, MLAdapter",
                "Hardcoded DEFAULT_CONFIG path independent of ranked winner",
            ],
            "not_B": "Acceptance JSON is never read by freeze or load paths — not advisory, simply disconnected",
        },
        "intentional_vs_defect": {
            "intentional_evidence": [
                "model_registry.py header: Phase 9.10 paper trading registry separate from Phase 9.9 optimizer",
                "freeze docstring: research path only",
                "optimization_orchestrator isolated from execution/freeze by project rules",
            ],
            "defect_evidence": [
                "metadata stores robustness_score from report implying coupling that is not enforced",
                "Production EngineRegistry/HealthGate load frozen bundle with no acceptance check",
                "Hardcoded logistic artifact diverges from post-22X selection (random_forest best, acceptance FAIL)",
                "Degenerated SELL-only model can remain frozen (Phase 22U/22X)",
            ],
            "conclusion": (
                "Phase separation (9.9 research vs 9.10 freeze) appears intentional, but the absence of any "
                "acceptance gate on freeze/load paths is an integration defect — not documented as safe behavior."
            ),
        },
    }


def build_impact_radius() -> dict[str, Any]:
    items = [
        {"path": "tradingbot/ml/paper_trading/model_registry.py", "classification": "CRITICAL", "reason": "freeze + load implementation"},
        {"path": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py", "classification": "HIGH", "reason": "acceptance producer; would need wiring to freeze"},
        {"path": "tradingbot/ml/research/robustness_optimizer/report_generator.py", "classification": "HIGH", "reason": "evaluate_acceptance source"},
        {"path": "tradingbot/ml/paper_trading/shadow_engine.py", "classification": "HIGH", "reason": "build_if_missing auto-freeze"},
        {"path": "tradingbot/ml/integration/kernel_shadow_runner.py", "classification": "HIGH", "reason": "_ensure_artifacts direct freeze"},
        {"path": "tradingbot/ml/shadow/ml_adapter.py", "classification": "MEDIUM", "reason": "conditional build_if_missing"},
        {"path": "tradingbot/ml/phase15a/engine_registry.py", "classification": "MEDIUM", "reason": "loads frozen bundle for live registry"},
        {"path": "tradingbot/ml/integration/health_gate.py", "classification": "MEDIUM", "reason": "loads bundle; no freeze but consumes artifact"},
        {"path": "tradingbot/ml/integration/pipeline_cache.py", "classification": "MEDIUM", "reason": "caches phase99 bundle"},
        {"path": "data/ml/research/phase9_9_best/", "classification": "MEDIUM", "reason": "artifact store"},
        {"path": "scripts/train_model.py", "classification": "MEDIUM", "reason": "would need new freeze integration flag"},
        {"path": "tradingbot/kernel/", "classification": "SAFE", "reason": "loads via registry; no freeze authority"},
        {"path": "tests/test_ml_paper_phase9_10.py", "classification": "SAFE", "reason": "test-only freeze calls"},
    ]
    return {
        "phase": "22AB",
        "scenario": "hypothetical future freeze-authority change",
        "items": items,
        "summary": {
            "CRITICAL": 1,
            "HIGH": 4,
            "MEDIUM": 6,
            "SAFE": 2,
        },
    }


def build_root_cause(
    metadata: dict[str, Any],
    robustness_report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "22AB",
        "question": "Why can a rejected model still become a frozen artifact?",
        "answer": (
            "freeze_phase9_9_artifacts() is a separate Phase 9.10 registry function that never reads "
            "evaluate_acceptance() or overfitting_risk_decreased. It trains a hardcoded "
            "logistic_strong_reg model from DEFAULT_CONFIG and can be invoked directly or via "
            "load_phase9_9_bundle(build_if_missing=True) without any connection to the Phase 9.9 "
            "RobustnessOptimizer pipeline."
        ),
        "repository_evidence": [
            {
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "lines": "92-144",
                "fact": "freeze uses DEFAULT_CONFIG; no acceptance import",
            },
            {
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "lines": "154-165",
                "fact": "load_phase9_9_bundle auto-freezes when model.pkl missing",
            },
            {
                "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                "fact": "run() ends at save_reports; never calls freeze",
            },
            {
                "file": "data/ml/research/phase9_9_best/metadata.json",
                "fact": f"frozen candidate={metadata.get('candidate_id')} at {metadata.get('frozen_at_utc')}",
            },
            {
                "file": "data/ml/reports/phase9_9_robustness_report.json",
                "fact": f"current acceptance.final_verdict={robustness_report.get('acceptance', {}).get('final_verdict')}",
            },
        ],
        "no_speculation": True,
    }


def run_forensics(
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.data.paths import (
        phase9_9_config_path,
        phase9_9_metadata_path,
        phase9_9_model_path,
        phase9_9_model_comparison_path,
        phase9_9_robustness_report_path,
    )

    metadata = json.loads(phase9_9_metadata_path(base_dir).read_text(encoding="utf-8"))
    config = json.loads(phase9_9_config_path(base_dir).read_text(encoding="utf-8"))
    comparison = json.loads(phase9_9_model_comparison_path(base_dir).read_text(encoding="utf-8"))
    robustness = json.loads(phase9_9_robustness_report_path(base_dir).read_text(encoding="utf-8"))
    model_exists = phase9_9_model_path(base_dir).is_file()

    classification = build_freeze_authority_classification()
    return {
        "freeze_call_graph": build_freeze_call_graph(),
        "acceptance_vs_freeze_flow": build_acceptance_vs_freeze_flow(),
        "historical_freeze_evidence": build_historical_freeze_evidence(
            metadata=metadata,
            config=config,
            comparison=comparison,
            robustness_report=robustness,
            model_path_exists=model_exists,
        ),
        "freeze_guard_analysis": build_freeze_guard_analysis(),
        "freeze_authority_classification": classification,
        "impact_radius": build_impact_radius(),
        "root_cause_report": build_root_cause(metadata, robustness),
        "verdict": "MULTIPLE_FREEZE_PATHS",
    }
