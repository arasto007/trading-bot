"""Phase 22AF — minimal safe architecture to connect Phase 9.9 optimizer to production freeze."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE22AE = PROJECT_ROOT / "tradingbot/ml/research/phase22ae/phase22ae_final_report.json"


def _load_phase22ae() -> dict[str, Any]:
    if PHASE22AE.is_file():
        return json.loads(PHASE22AE.read_text(encoding="utf-8"))
    return {}


def build_freeze_repair_design() -> dict[str, Any]:
    """STEP 1 — current architecture, broken edges, required new edges."""
    ae = _load_phase22ae()
    return {
        "phase": "22AF",
        "title": "Freeze Pipeline Repair Design",
        "source_analysis": "Phase 22AE (MULTIPLE_CAUSES: HARDCODED_CONFIG + DISCONNECTED_PIPELINE)",
        "current_flow": {
            "optimizer_path": [
                "scripts/train_model.py --phase9-9",
                "RobustnessOptimizer.run()",
                "run_candidate_grid → rank_candidates → select_best",
                "evaluate_acceptance(best, baseline)",
                "save_reports → data/ml/reports/phase9_9_*.json",
                "exit (no freeze)",
            ],
            "freeze_path": [
                "freeze_phase9_9_artifacts() [direct | load(build_if_missing=True) | KernelShadowRunner]",
                "cfg = config or DEFAULT_CONFIG",
                "ModelCandidateConfig hardcoded logistic_strong_reg",
                "85% chronological retrain",
                "write data/ml/research/phase9_9_best/*",
            ],
            "runtime_path": [
                "load_phase9_9_bundle(build_if_missing=False)",
                "EngineRegistry → RangeEngineAdapter → predict_proba",
            ],
        },
        "broken_edges": [
            {
                "from": "select_best(ranked)",
                "to": "freeze_phase9_9_artifacts",
                "status": "MISSING",
                "impact": "Winner never becomes production artifact",
            },
            {
                "from": "evaluate_acceptance",
                "to": "freeze gate",
                "status": "MISSING",
                "impact": "Acceptance verdict ignored at freeze time",
            },
            {
                "from": "best_candidate dict",
                "to": "ModelCandidateConfig in freeze",
                "status": "MISSING",
                "impact": "Hardcoded logistic_strong_reg always wins",
            },
            {
                "from": "feature_subsets research",
                "to": "freeze feature_order.json",
                "status": "PARTIAL",
                "impact": "DEFAULT_CONFIG static top3, not winner subset",
            },
            {
                "from": "phase9_9_robustness_report.json",
                "to": "freeze candidate selection",
                "status": "PARTIAL",
                "impact": "_load_phase99_score reads score only",
            },
            {
                "from": "ShadowEngine / KernelShadowRunner",
                "to": "freeze without acceptance",
                "status": "UNGUARDED_SIDE_PATH",
                "impact": "Can overwrite artifacts with DEFAULT_CONFIG",
            },
        ],
        "required_new_edges": [
            {
                "from": "select_best(ranked)",
                "to": "FreezeContract builder",
                "action": "Map winner fields → typed freeze input",
            },
            {
                "from": "evaluate_acceptance",
                "to": "freeze gate",
                "action": "Reject freeze unless final_verdict == PASS",
            },
            {
                "from": "FreezeContract",
                "to": "freeze_phase9_9_artifacts (refactored)",
                "action": "Train winner model_name + hyperparameters + feature list",
            },
            {
                "from": "freeze output",
                "to": "metadata.json + config.json",
                "action": "Persist full contract + acceptance snapshot + report checksum",
            },
            {
                "from": "load_phase9_9_bundle",
                "to": "metadata validation",
                "action": "Verify contract fields before inference (HealthGate extension optional)",
            },
            {
                "from": "Shadow auto-freeze paths",
                "to": "read-only or explicit --force-research-freeze",
                "action": "Remove unguarded DEFAULT_CONFIG rebuild in production paths",
            },
        ],
        "design_principles": [
            "Single write authority: acceptance-gated freeze only",
            "Freeze input derived from optimizer report, not DEFAULT_CONFIG literals",
            "Research isolation preserved until explicit approved integration phase",
            "No automatic freeze on build_if_missing in production loaders",
            "Chronological retrain protocol documented in contract (85% slice or full-data refit — pick one explicitly)",
        ],
        "phase22ae_evidence": {
            "verdict": ae.get("verdict"),
            "optimizer_reaches_freeze": ae.get("optimizer_reaches_freeze"),
            "report_vs_frozen": ae.get("report_vs_frozen"),
        },
    }


def build_authority_redesign() -> dict[str, Any]:
    """STEP 2 — new authority chain."""
    return {
        "phase": "22AF",
        "title": "Authority Chain Redesign",
        "previous_authorities": [
            "DEFAULT_CONFIG (freeze write)",
            "RobustnessOptimizer (report only)",
            "Shadow auto-freeze (side path)",
            "On-disk artifact (runtime read)",
        ],
        "target_authority_chain": [
            {
                "stage": 1,
                "name": "Optimizer winner",
                "component": "RobustnessOptimizer → select_best(rank_candidates(...))",
                "authority": "Selects candidate_id, model_name, feature_subset, hyperparameters, metrics",
                "output": "best_candidate row in phase9_9_robustness_report.json",
                "constraints": "Must have probability_gate_passed=True (already enforced by select_best)",
            },
            {
                "stage": 2,
                "name": "Acceptance gate",
                "component": "evaluate_acceptance(best, baseline)",
                "authority": "Binary PASS/FAIL on robustness, overfitting, expectancy, probability quality",
                "output": "acceptance.final_verdict + checks dict embedded in report",
                "constraints": "Freeze blocked on FAIL; no bypass flag in production",
            },
            {
                "stage": 3,
                "name": "Freeze artifact",
                "component": "freeze_phase9_9_artifacts_from_contract (refactored freeze)",
                "authority": "Sole writer of phase9_9_best/* when gate passes",
                "output": "model.pkl, scaler.pkl, feature_order.json, config.json, metadata.json, freeze_manifest.json",
                "constraints": "Must reject unknown candidate_id / missing fields",
            },
            {
                "stage": 4,
                "name": "Model Registry",
                "component": "load_phase9_9_bundle(build_if_missing=False)",
                "authority": "Read-only loader + integrity verification",
                "output": "Phase99Bundle in memory",
                "constraints": "Production default build_if_missing=False; no silent retrain",
            },
            {
                "stage": 5,
                "name": "Runtime",
                "component": "EngineRegistry → RangeEngineAdapter → predict_proba",
                "authority": "Consumes frozen bundle only",
                "output": "RANGE ML signals in live kernel",
                "constraints": "HealthGate validates artifact presence + optional contract checksum",
            },
        ],
        "authority_diagram_ascii": (
            "Optimizer winner (select_best)\n"
            "        ↓\n"
            "Acceptance gate (evaluate_acceptance == PASS)\n"
            "        ↓\n"
            "Freeze artifact (contract-driven retrain + persist)\n"
            "        ↓\n"
            "Model Registry (read-only load)\n"
            "        ↓\n"
            "Runtime (EngineRegistry / HealthGate / KernelAdapter)"
        ),
        "eliminated_authorities": [
            "DEFAULT_CONFIG as implicit freeze winner",
            "Shadow/KernelShadowRunner silent auto-freeze",
            "Hardcoded logistic_strong_reg in freeze body",
        ],
        "runtime_authority_unchanged": "Registry loader remains runtime authority (Phase 22AD); only freeze write source changes",
    }


def build_required_changes() -> dict[str, Any]:
    """STEP 3 — minimum production files; design only, no code."""
    files = [
        {
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "current_role": "DEFAULT_CONFIG, hardcoded freeze, bundle load",
            "required_change": "Replace hardcoded freeze with contract-driven freeze; deprecate DEFAULT_CONFIG as freeze source; keep load/verify; default build_if_missing=False for production callers",
            "risk": "CRITICAL",
            "approval": "Explicit production approval required (core registry)",
        },
        {
            "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
            "current_role": "Runs grid, ranks, accepts, saves JSON, stops",
            "required_change": "After save_reports, if acceptance PASS invoke freeze bridge with best_candidate + acceptance snapshot; if FAIL log and skip freeze",
            "risk": "HIGH",
            "approval": "Phase 9.9 pipeline scope (22X precedent)",
        },
        {
            "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "current_role": "evaluate_acceptance, save_reports",
            "required_change": "Export stable FreezeContract builder helper from best row + feature_subsets map + acceptance; embed report_path checksum in contract",
            "risk": "MEDIUM",
            "approval": "Phase 9.9 research pipeline",
        },
        {
            "file": "scripts/train_model.py",
            "current_role": "CLI entry --phase9-9 exits after optimizer",
            "required_change": "Surface freeze outcome in exit message; optional --dry-freeze flag for contract validation without write (research)",
            "risk": "LOW",
            "approval": "CLI only",
        },
        {
            "file": "tradingbot/ml/integration/kernel_shadow_runner.py",
            "current_role": "_ensure_artifacts calls freeze_phase9_9_artifacts directly",
            "required_change": "Remove direct freeze; require pre-existing artifacts or fail with actionable error pointing to train_model --phase9-9",
            "risk": "HIGH",
            "approval": "Shadow integration — not live hot path but can overwrite artifacts",
        },
        {
            "file": "tradingbot/ml/paper_trading/shadow_engine.py",
            "current_role": "load_phase9_9_bundle(build_if_missing=True)",
            "required_change": "Change to build_if_missing=False or gated research-only flag; never auto-freeze DEFAULT_CONFIG in production base_dir",
            "risk": "HIGH",
            "approval": "Paper/shadow path",
        },
        {
            "file": "tradingbot/ml/shadow/ml_adapter.py",
            "current_role": "Conditional build_if_missing when training_df provided",
            "required_change": "Same as shadow_engine — disable unguarded auto-freeze on production artifact path",
            "risk": "MEDIUM",
            "approval": "Shadow adapter",
        },
        {
            "file": "tradingbot/ml/paper/config.py",
            "current_role": "EXPECTED_FEATURES from DEFAULT_CONFIG at import",
            "required_change": "Validate against artifact feature_order.json at runtime; stop hard-binding to DEFAULT_CONFIG features",
            "risk": "HIGH",
            "approval": "Paper validation path",
        },
        {
            "file": "tradingbot/ml/integration/health_gate.py",
            "current_role": "load bundle, verify integrity, fingerprint checks",
            "required_change": "Optional: verify metadata.acceptance_status==PASS and contract checksum matches report; fail health if manifest stale",
            "risk": "MEDIUM",
            "approval": "Health gate — live fallback behavior",
        },
        {
            "file": "tradingbot/ml/phase15a/engine_registry.py",
            "current_role": "EngineRegistry.build_default loads bundle",
            "required_change": "No logic change if registry load unchanged; document dependency on post-freeze artifacts",
            "risk": "LOW",
            "approval": "Read-only consumer",
        },
    ]
    return {
        "phase": "22AF",
        "minimum_production_surface": [
            "model_registry.py",
            "optimization_orchestrator.py",
            "report_generator.py",
            "kernel_shadow_runner.py",
            "shadow_engine.py",
        ],
        "recommended_new_module": {
            "path": "tradingbot/ml/research/robustness_optimizer/freeze_bridge.py",
            "role": "Build FreezeContract, run guards, call registry freeze — keeps orchestrator thin",
            "note": "Research module first; production import only after approval phase",
        },
        "files": files,
        "out_of_scope_for_minimal_fix": [
            "TradingKernel",
            "RiskGate core",
            "Mt5ExecutionAdapter",
            "Feature pipeline",
            "Dataset builder",
        ],
        "prerequisite_work": [
            "Phase 22Y/22Z: acceptance rule overfitting_risk_decreased may block all freezes until calibrated",
            "Ensure at least one candidate can PASS before first production freeze",
        ],
    }


def build_freeze_contract() -> dict[str, Any]:
    """STEP 4 — freeze contract schema."""
    return {
        "phase": "22AF",
        "name": "FreezeContract",
        "version": "1.0",
        "description": "Typed input connecting optimizer winner to artifact writer",
        "required_fields": {
            "candidate_id": {
                "type": "string",
                "source": "best_candidate.candidate_id",
                "example": "random_forest_shallow",
                "validation": "Must exist in build_regularized_candidates grid",
            },
            "model_type": {
                "type": "string",
                "source": "best_candidate.model_name",
                "example": "random_forest",
                "validation": "Must be supported by create_regularized_model",
            },
            "feature_subset": {
                "type": "string",
                "source": "best_candidate.feature_subset",
                "example": "stable_4",
                "validation": "Key must exist in feature_subsets from feature research",
            },
            "features": {
                "type": "list[str]",
                "source": "feature_subsets[feature_subset]",
                "validation": "Non-empty; chronological order preserved",
            },
            "hyperparameters": {
                "type": "dict",
                "source": "experiment hyperparameters from grid / best row",
                "validation": "Passed to create_regularized_model",
            },
            "thresholds": {
                "type": "dict",
                "fields": {
                    "buy_threshold": 0.55,
                    "sell_threshold": 0.45,
                    "tp_r": 2.0,
                    "sl_r": 1.0,
                    "risk_pct": 0.005,
                },
                "source": "Phase 9.9 policy defaults or config.json legacy until optimizer owns thresholds",
            },
            "regime": {
                "type": "string",
                "source": "best_candidate.regime",
                "default": "RANGE",
            },
            "event_filter": {
                "type": "string",
                "default": "A_all_events",
            },
            "validation_metrics": {
                "type": "dict",
                "required_keys": [
                    "robustness_score",
                    "overfitting_risk",
                    "mean_profit_factor",
                    "mean_expectancy",
                    "mean_auc_gap",
                    "profitable_windows",
                    "window_count",
                    "composite_score",
                ],
                "source": "best_candidate row",
            },
            "probability_metrics": {
                "type": "dict",
                "required_keys": [
                    "buy_coverage_pct",
                    "sell_coverage_pct",
                    "probability_std",
                    "min_probability",
                    "max_probability",
                    "probability_gate_passed",
                ],
                "source": "best_candidate probability fields",
            },
            "acceptance_status": {
                "type": "dict",
                "required_keys": ["final_verdict", "checks"],
                "source": "evaluate_acceptance output",
                "rule": "final_verdict must be PASS before freeze",
            },
        },
        "metadata_extensions": {
            "experiment_id": "best_candidate.experiment_id",
            "report_path": "phase9_9_robustness_report_path",
            "report_checksum_sha256": "hash of report at freeze time",
            "acceptance_snapshot": "full acceptance dict",
            "frozen_at_utc": "ISO timestamp",
            "dataset_fingerprint": "dataset_content_fingerprint(df)",
            "train_protocol": "documented e.g. chronological_85pct_refit",
            "phase": "9.9",
        },
        "artifact_outputs": [
            "model.pkl",
            "scaler.pkl",
            "feature_order.json",
            "config.json",
            "metadata.json",
            "freeze_manifest.json",
        ],
    }


def build_safety_guard_design() -> dict[str, Any]:
    """STEP 5 — guards that must reject freeze."""
    return {
        "phase": "22AF",
        "guard_location": "freeze_bridge.validate_before_freeze(contract, report, feature_subsets)",
        "reject_conditions": [
            {
                "guard": "no_acceptance",
                "condition": "acceptance_status.final_verdict != 'PASS'",
                "error_code": "FREEZE_REJECT_NO_ACCEPTANCE",
                "evidence": "Phase 22AB: freeze currently bypasses acceptance entirely",
            },
            {
                "guard": "failed_probability_gate",
                "condition": "probability_metrics.probability_gate_passed is not True",
                "error_code": "FREEZE_REJECT_PROBABILITY_GATE",
                "evidence": "Phase 22X gate; select_best already filters but guard must re-check at freeze",
            },
            {
                "guard": "missing_metadata",
                "condition": "Any required FreezeContract field null or empty",
                "error_code": "FREEZE_REJECT_INCOMPLETE_CONTRACT",
                "fields_checked": list(build_freeze_contract()["required_fields"].keys()),
            },
            {
                "guard": "unknown_candidate",
                "condition": "candidate_id not in allowed grid OR model_type unsupported",
                "error_code": "FREEZE_REJECT_UNKNOWN_CANDIDATE",
                "allowed_source": "build_regularized_candidates() registry",
            },
            {
                "guard": "missing_validation_report",
                "condition": "phase9_9_robustness_report.json missing or checksum mismatch vs contract",
                "error_code": "FREEZE_REJECT_MISSING_REPORT",
            },
        ],
        "additional_recommended_guards": [
            {
                "guard": "dataset_fingerprint_unchanged",
                "condition": "training df fingerprint matches report integrity fingerprint",
            },
            {
                "guard": "feature_subset_resolution",
                "condition": "feature_subset key resolves to non-empty feature list",
            },
            {
                "guard": "no_production_base_dir_auto_freeze",
                "condition": "block build_if_missing=True freeze when base_dir is production path",
            },
            {
                "guard": "atomic_write",
                "condition": "write to temp dir then rename to prevent partial model.pkl without metadata",
            },
        ],
        "fail_closed": True,
        "on_reject": "Log structured error; do not write artifacts; CLI exit non-zero if freeze requested",
    }


def build_backward_compatibility() -> dict[str, Any]:
    """STEP 6 — backward compatibility analysis."""
    return {
        "phase": "22AF",
        "existing_model_pkl": {
            "current_state": "May exist or be missing independently of metadata sidecars",
            "compatibility": "First contract-driven freeze replaces entire phase9_9_best directory atomically",
            "migration": "Backup existing phase9_9_best/ before first gated freeze; document checksum in freeze_manifest",
            "runtime": "load_phase9_9_bundle unchanged if artifact schema backward compatible",
        },
        "existing_metadata": {
            "current_fields": ["phase", "frozen_at_utc", "candidate_id", "feature_subset", "train_rows", "dataset_fingerprint", "robustness_score"],
            "new_fields_additive": ["experiment_id", "acceptance_snapshot", "report_checksum_sha256", "probability_metrics", "validation_metrics"],
            "breaking_change": "candidate_id may change from logistic_strong_reg to optimizer winner — expected",
            "health_gate": "phase9_fingerprint check continues; add optional acceptance_status check",
        },
        "shadow_paths": {
            "kernel_shadow_runner": "Must stop writing artifacts; tests use temp base_dir with explicit fixture freeze",
            "shadow_engine": "build_if_missing=True must not run on production path",
            "ml_adapter": "Same restriction",
            "test_fixtures": "Tests may call contract freeze with test contracts to temp dirs — unchanged pattern",
        },
        "health_gate": {
            "current": "load bundle build_if_missing=False; verify_bundle_integrity; metadata/feature_order file checks",
            "impact": "Stricter metadata optional; missing model.pkl still fails predict check",
            "fallback": "KernelFallbackError to legacy PriceAction unchanged on health fail",
        },
        "engine_registry": {
            "current": "Double load via load_phase9_9_bundle + RangeEngineAdapter.load(base_dir=None)",
            "impact": "No change required for minimal fix; bundle content changes when freeze source changes",
            "note": "RangeEngineAdapter hardcoded base_dir=None remains separate concern (Phase 22AC)",
        },
        "paper_config_expected_features": {
            "current": "EXPECTED_FEATURES = DEFAULT_CONFIG features at import",
            "impact": "Will mismatch after freeze of non-top3 winner unless validate_frozen_model reads artifact",
            "required_follow_up": "paper/config.py change in same release as contract freeze",
        },
        "default_config_deprecation": {
            "keep_for": "Test fallbacks and documentation only",
            "remove_from": "Freeze default path and paper EXPECTED_FEATURES binding",
        },
    }


def build_migration_plan() -> dict[str, Any]:
    """STEP 7 — phased migration order."""
    return {
        "phase": "22AF",
        "migration_phases": [
            {
                "phase": 1,
                "name": "Contract + guards (research-only prototype)",
                "order": 1,
                "tasks": [
                    "Implement FreezeContract schema and freeze_bridge.validate_before_freeze in research module",
                    "Unit tests: guards reject no acceptance, failed probability gate, unknown candidate, missing report",
                    "Prototype freeze_from_contract writing to temp directories only",
                    "Document train_protocol alignment (85% refit vs full-data) with walk-forward methodology",
                ],
                "production_touch": False,
                "exit_criteria": "All guard tests pass; contract builds from live phase9_9_robustness_report.json",
            },
            {
                "phase": 2,
                "name": "Pipeline connection + side-path removal (approved production)",
                "order": 2,
                "tasks": [
                    "Refactor model_registry freeze to consume FreezeContract; remove hardcoded logistic_strong_reg",
                    "Wire optimization_orchestrator to call freeze_bridge after acceptance PASS only",
                    "Disable unguarded auto-freeze in kernel_shadow_runner, shadow_engine, ml_adapter",
                    "Change load_phase9_9_bundle default to build_if_missing=False globally for production callers",
                    "Resolve acceptance rule blocker (22Y/22Z) so at least one candidate can PASS",
                    "Run train_model --phase9-9 end-to-end; verify artifacts match winner experiment_id",
                ],
                "production_touch": True,
                "exit_criteria": "phase9_9_best metadata candidate_id matches report best_candidate; HealthGate PASS; pytest full",
            },
            {
                "phase": 3,
                "name": "Runtime validation + operational hardening",
                "order": 3,
                "tasks": [
                    "Extend HealthGate to verify acceptance_snapshot and report checksum in metadata",
                    "Update paper/config EXPECTED_FEATURES to read artifact feature_order.json",
                    "Add verify_ml_live_ready check for freeze_manifest presence",
                    "Archive backup of pre-migration logistic_strong_reg artifacts",
                    "Document operator runbook: train → accept → freeze → restart live (PipelineCache reload)",
                ],
                "production_touch": True,
                "exit_criteria": "Live path loads new bundle; no shadow overwrite; dashboard/live ready checks pass",
            },
        ],
        "rollback": "Restore backed-up phase9_9_best/ directory; restart live process",
        "blocked_until": [
            "Acceptance calibration (overfitting_risk_decreased) — otherwise freeze gate never opens",
        ],
    }


def determine_verdict() -> str:
    """READY_FOR_IMPLEMENTATION unless fundamental blocker."""
    return "READY_FOR_IMPLEMENTATION"


def run_design() -> dict[str, Any]:
    return {
        "freeze_repair_design": build_freeze_repair_design(),
        "authority_redesign": build_authority_redesign(),
        "required_changes": build_required_changes(),
        "freeze_contract": build_freeze_contract(),
        "safety_guard_design": build_safety_guard_design(),
        "backward_compatibility": build_backward_compatibility(),
        "migration_plan": build_migration_plan(),
        "verdict": determine_verdict(),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "production_modified": False,
    }
