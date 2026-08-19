"""Phase 22AC — Model Registry architecture and dependency radius mapping."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEARCH_TERMS = (
    "DEFAULT_CONFIG",
    "phase9_9_best",
    "load_phase9_9_bundle",
    "build_if_missing",
    "model.pkl",
    "metadata.json",
    "feature_order.json",
    "config.json",
    "freeze_phase9_9_artifacts",
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "archive",
}

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in {".py", ".json", ".md", ".bat", ".sh"}:
            continue
        files.append(path)
    return files


def _function_at_line(tree: ast.AST, line: int) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                return node.name
        if isinstance(node, ast.ClassDef):
            if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                return node.name
    return None


def scan_repository_usage() -> dict[str, list[dict[str, Any]]]:
    """STEP 2 — repository-wide usage index with file, function, purpose, lines."""
    out: dict[str, list[dict[str, Any]]] = {term: [] for term in SEARCH_TERMS}
    purpose_hints = {
        "DEFAULT_CONFIG": "hardcoded Phase 9.9 freeze / validation defaults",
        "phase9_9_best": "frozen RANGE model bundle alias or artifact directory",
        "load_phase9_9_bundle": "load or auto-freeze Phase 9.9 artifact bundle",
        "build_if_missing": "trigger freeze when model.pkl absent",
        "model.pkl": "serialized sklearn model artifact path or existence check",
        "metadata.json": "frozen model metadata sidecar",
        "feature_order.json": "inference feature column order sidecar",
        "config.json": "frozen trading/threshold config sidecar",
        "freeze_phase9_9_artifacts": "train and persist Phase 9.9 bundle from DEFAULT_CONFIG",
    }

    for path in _iter_source_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not any(term in text for term in SEARCH_TERMS):
            continue

        tree: ast.AST | None = None
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None

        for i, line in enumerate(text.splitlines(), 1):
            for term in SEARCH_TERMS:
                if term not in line:
                    continue
                fn = None
                if tree is not None:
                    fn = _function_at_line(tree, i)
                out[term].append(
                    {
                        "file": _rel(path),
                        "function": fn or "(module)",
                        "purpose": purpose_hints[term],
                        "line": i,
                        "snippet": line.strip()[:160],
                    }
                )
    return out


def build_model_registry_architecture(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 1 — complete Model Registry architecture map."""
    from tradingbot.ml.data.paths import (
        phase9_9_artifacts_root,
        phase9_9_config_path,
        phase9_9_feature_order_path,
        phase9_9_metadata_path,
        phase9_9_model_path,
        phase9_9_robustness_report_path,
        phase9_9_scaler_path,
    )

    root = phase9_9_artifacts_root(base_dir)
    artifact_state = {
        "root": str(root),
        "model.pkl": phase9_9_model_path(base_dir).is_file(),
        "scaler.pkl": phase9_9_scaler_path(base_dir).is_file(),
        "feature_order.json": phase9_9_feature_order_path(base_dir).is_file(),
        "config.json": phase9_9_config_path(base_dir).is_file(),
        "metadata.json": phase9_9_metadata_path(base_dir).is_file(),
        "robustness_report": phase9_9_robustness_report_path(base_dir).is_file(),
    }

    registry_module = {
        "file": "tradingbot/ml/paper_trading/model_registry.py",
        "exports": [
            "DEFAULT_CONFIG",
            "PHASE99_ALIAS",
            "Phase99Bundle",
            "IntegrityResult",
            "freeze_phase9_9_artifacts",
            "load_phase9_9_bundle",
            "verify_bundle_integrity",
        ],
        "callees": [
            {"module": "tradingbot.ml.data.paths", "symbols": ["phase9_9_* path helpers"]},
            {"module": "tradingbot.ml.research.regime_optimization.regime_utils", "symbols": ["apply_event_filter", "assign_market_regime"]},
            {"module": "tradingbot.ml.research.robustness_optimizer.model_regularization", "symbols": ["ModelCandidateConfig", "create_regularized_model"]},
            {"module": "tradingbot.ml.research.research_utils", "symbols": ["dataset_content_fingerprint"]},
            {"module": "tradingbot.ml.training.data_loader", "symbols": ["filter_resolved_labels"]},
            {"module": "joblib", "symbols": ["dump", "load"]},
        ],
        "callers": [
            {"component": "EngineRegistry.build_default", "file": "tradingbot/ml/phase15a/engine_registry.py", "calls": ["load_phase9_9_bundle", "verify_bundle_integrity"]},
            {"component": "HealthGate.run_pre_decision_health", "file": "tradingbot/ml/integration/health_gate.py", "calls": ["load_phase9_9_bundle", "verify_bundle_integrity"]},
            {"component": "PipelineCache", "file": "tradingbot/ml/integration/pipeline_cache.py", "calls": ["load_phase9_9_bundle"]},
            {"component": "ShadowEngine.run", "file": "tradingbot/ml/paper_trading/shadow_engine.py", "calls": ["load_phase9_9_bundle(build_if_missing=True)"]},
            {"component": "KernelShadowRunner._ensure_artifacts", "file": "tradingbot/ml/integration/kernel_shadow_runner.py", "calls": ["freeze_phase9_9_artifacts"]},
            {"component": "MLAdapter.load", "file": "tradingbot/ml/shadow/ml_adapter.py", "calls": ["load_phase9_9_bundle"]},
            {"component": "RangeEngineAdapter.load", "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py", "calls": ["load_phase9_9_bundle(base_dir=None)"]},
            {"component": "PaperTradingConfig.validate_frozen_model", "file": "tradingbot/ml/paper/config.py", "calls": ["DEFAULT_CONFIG", "load_phase9_9_bundle"]},
        ],
    }

    bundle_loading = {
        "entry": "load_phase9_9_bundle",
        "default_build_if_missing": True,
        "production_build_if_missing": False,
        "discovery": {
            "root": "data/ml/research/phase9_9_best/",
            "resolver": "tradingbot.ml.data.paths.phase9_9_artifacts_root",
            "base_dir_none_means": "project data/ml/ (normalize_ml_base_dir maps legacy BASE_DIR to None)",
        },
        "load_sequence": [
            "phase9_9_model_path → joblib.load(model)",
            "phase9_9_scaler_path → joblib.load(scaler)",
            "phase9_9_feature_order_path → json feature_order",
            "phase9_9_config_path → json config",
            "phase9_9_metadata_path → json metadata (optional empty dict)",
        ],
        "auto_freeze_trigger": "model.pkl missing AND build_if_missing=True AND training_df provided",
    }

    metadata_loading = {
        "writer": "freeze_phase9_9_artifacts",
        "reader": "load_phase9_9_bundle",
        "fields_written": [
            "phase",
            "frozen_at_utc",
            "candidate_id",
            "feature_subset",
            "train_rows",
            "dataset_fingerprint",
            "robustness_score",
        ],
        "robustness_score_source": "phase9_9_robustness_report.json best_candidate.robustness_score (0.0 if missing)",
        "direct_readers": [
            {"file": "tradingbot/ml/integration/health_gate.py", "function": "run_pre_decision_health", "check": "phase9_fingerprint vs EXPECTED_DATASET_FINGERPRINT"},
            {"file": "tradingbot/ml/paper/config.py", "function": "validate_frozen_model", "check": "metadata.phase in (9.9, 9.10, 11)"},
        ],
    }

    feature_order_loading = {
        "writer": "freeze_phase9_9_artifacts → feature_order.json",
        "reader_keys": ["feature_order", "features"],
        "consumers": [
            "Phase99Bundle.transform",
            "verify_bundle_integrity",
            "HealthGate (phase9_feature_order_file existence)",
            "RangeEngineAdapter._features_from_row",
            "paper/config EXPECTED_FEATURES (from DEFAULT_CONFIG, not artifact at import time)",
        ],
    }

    components = {
        "EngineRegistry": {
            "file": "tradingbot/ml/phase15a/engine_registry.py",
            "role": "Register RANGE + TREND production engines",
            "registry_calls": ["load_phase9_9_bundle(build_if_missing=False)", "RangeEngineAdapter.load", "load_trend_bundle"],
            "called_by": ["PipelineCache.get_registry", "HealthGate.run_pre_decision_health (registry param)", "phase15 orchestrators"],
        },
        "HealthGate": {
            "file": "tradingbot/ml/integration/health_gate.py",
            "role": "Pre-decision integrity; Kernel fallback on failure",
            "registry_calls": ["load_phase9_9_bundle(build_if_missing=False)", "verify_bundle_integrity", "phase9_9_metadata_path", "phase9_9_feature_order_path"],
            "called_by": ["require_health", "kernel integration orchestrators"],
        },
        "ShadowEngine": {
            "file": "tradingbot/ml/paper_trading/shadow_engine.py",
            "role": "Paper shadow validation; CAN auto-freeze",
            "registry_calls": ["load_phase9_9_bundle(build_if_missing=True, training_df=raw)"],
            "called_by": ["paper trading CLI / orchestrators"],
        },
        "KernelShadowRunner": {
            "file": "tradingbot/ml/integration/kernel_shadow_runner.py",
            "role": "Kernel-integrated shadow replay; direct freeze if model.pkl missing",
            "registry_calls": ["freeze_phase9_9_artifacts via _ensure_artifacts"],
            "called_by": ["kernel shadow integration"],
        },
        "MLAdapter": {
            "file": "tradingbot/ml/shadow/ml_adapter.py",
            "role": "Phase 10 ML predictions from frozen bundle",
            "registry_calls": ["load_phase9_9_bundle(build_if_missing=training_df is not None)"],
            "called_by": ["shadow strategy / kernel bridge"],
        },
        "PipelineCache": {
            "file": "tradingbot/ml/integration/pipeline_cache.py",
            "role": "Singleton cache for registry and bundles",
            "registry_calls": [
                "EngineRegistry.build_default(build_trend_if_missing=False)",
                "load_phase9_9_bundle(build_if_missing=False)",
            ],
            "called_by": ["live ML kernel pipeline"],
            "note": "Does NOT trigger rebuild; read-only load path",
        },
    }

    return {
        "phase": "22AC",
        "title": "Model Registry Architecture Map",
        "artifact_state": artifact_state,
        "model_registry": registry_module,
        "DEFAULT_CONFIG": {
            "defined_in": "tradingbot/ml/paper_trading/model_registry.py",
            "imported_by": [
                "tradingbot/ml/paper/config.py → EXPECTED_FEATURES",
                "tests/test_ml_paper_phase9_10.py",
                "research phase22v model_audit (fallback)",
            ],
            "runtime_authority": "freeze write path; NOT optimizer select_best output",
        },
        "bundle_loading": bundle_loading,
        "artifact_discovery": bundle_loading["discovery"],
        "metadata_loading": metadata_loading,
        "feature_order_loading": feature_order_loading,
        "runtime_components": components,
    }


def build_authority_analysis(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 3 — who selects the production RANGE model."""
    from tradingbot.ml.data.paths import phase9_9_metadata_path, phase9_9_robustness_report_path

    metadata: dict[str, Any] = {}
    meta_path = phase9_9_metadata_path(base_dir)
    if meta_path.is_file():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    report_best: dict[str, Any] = {}
    report_path = phase9_9_robustness_report_path(base_dir)
    if report_path.is_file():
        report_best = json.loads(report_path.read_text(encoding="utf-8")).get("best_candidate", {})

    authorities = [
        {
            "name": "Phase 9.9 Optimizer (RobustnessOptimizer)",
            "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
            "scope": "selection + acceptance reports only",
            "selects_production_model": False,
            "evidence": "train_model --phase9-9 stops after JSON reports; never calls freeze",
        },
        {
            "name": "Model Registry freeze (DEFAULT_CONFIG)",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "scope": "artifact write authority",
            "selects_production_model": True,
            "evidence": "freeze_phase9_9_artifacts trains logistic_strong_reg from DEFAULT_CONFIG; ignores select_best()",
        },
        {
            "name": "Engine Registry",
            "file": "tradingbot/ml/phase15a/engine_registry.py",
            "scope": "runtime assembly",
            "selects_production_model": False,
            "evidence": "load_phase9_9_bundle(build_if_missing=False) — reads whatever is on disk",
        },
        {
            "name": "Bundle Loader (load_phase9_9_bundle)",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "scope": "read + conditional auto-freeze",
            "selects_production_model": "conditional",
            "evidence": "default build_if_missing=True can re-freeze DEFAULT_CONFIG when model.pkl missing",
        },
        {
            "name": "Health Gate",
            "file": "tradingbot/ml/integration/health_gate.py",
            "scope": "runtime validation only",
            "selects_production_model": False,
            "evidence": "build_if_missing=False; checks integrity and fingerprint files",
        },
        {
            "name": "CLI (train_model --phase9-9)",
            "file": "scripts/train_model.py",
            "scope": "research training entry",
            "selects_production_model": False,
            "evidence": "runs optimizer; does not freeze",
        },
        {
            "name": "Hardcoded DEFAULT_CONFIG / paper EXPECTED_FEATURES",
            "file": "tradingbot/ml/paper/config.py",
            "scope": "validation expectations",
            "selects_production_model": True,
            "evidence": "EXPECTED_FEATURES imported from DEFAULT_CONFIG at module load, not from artifact",
        },
        {
            "name": "Shadow auto-freeze paths",
            "file": "tradingbot/ml/paper_trading/shadow_engine.py",
            "scope": "side-effect write on missing model.pkl",
            "selects_production_model": True,
            "evidence": "ShadowEngine + KernelShadowRunner can overwrite artifacts without acceptance",
        },
    ]

    frozen_vs_report = {
        "frozen_metadata_candidate_id": metadata.get("candidate_id"),
        "frozen_robustness_score": metadata.get("robustness_score"),
        "report_best_candidate_id": report_best.get("candidate_id"),
        "report_robustness_score": report_best.get("robustness_score"),
        "aligned": metadata.get("candidate_id") == report_best.get("candidate_id") if report_best else None,
    }

    return {
        "phase": "22AC",
        "question": "Which component is the true authority for selecting the production model?",
        "answer": "No single authority — multiple independent selection/write paths exist",
        "authorities": authorities,
        "frozen_vs_optimizer_report": frozen_vs_report,
        "single_authority": False,
        "primary_write_authority": "freeze_phase9_9_artifacts (DEFAULT_CONFIG)",
        "primary_report_authority": "RobustnessOptimizer + evaluate_acceptance (disconnected from freeze)",
        "primary_runtime_authority": "On-disk phase9_9_best bundle loaded with build_if_missing=False",
    }


def build_artifact_write_paths() -> dict[str, Any]:
    """STEP 4 — every path that can create/overwrite phase9_9 artifacts."""
    write_paths = [
        {
            "artifact": "model.pkl",
            "function": "freeze_phase9_9_artifacts",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "line": 125,
            "mechanism": "joblib.dump(model, phase9_9_model_path)",
            "triggers": ["direct call", "load_phase9_9_bundle(build_if_missing=True)", "KernelShadowRunner._ensure_artifacts"],
        },
        {
            "artifact": "scaler.pkl",
            "function": "freeze_phase9_9_artifacts",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "line": 126,
            "mechanism": "joblib.dump(scaler, phase9_9_scaler_path)",
            "triggers": ["same as model.pkl"],
        },
        {
            "artifact": "feature_order.json",
            "function": "freeze_phase9_9_artifacts",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "line": 127,
            "mechanism": "Path.write_text(json feature_order)",
            "triggers": ["same as model.pkl"],
        },
        {
            "artifact": "config.json",
            "function": "freeze_phase9_9_artifacts",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "line": 131,
            "mechanism": "Path.write_text(json config)",
            "triggers": ["same as model.pkl"],
        },
        {
            "artifact": "metadata.json",
            "function": "freeze_phase9_9_artifacts",
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "line": 142,
            "mechanism": "Path.write_text(json metadata)",
            "triggers": ["same as model.pkl"],
        },
    ]

    indirect_callers = [
        {"file": "tradingbot/ml/paper_trading/model_registry.py", "function": "load_phase9_9_bundle", "condition": "build_if_missing=True and model.pkl missing"},
        {"file": "tradingbot/ml/paper_trading/shadow_engine.py", "function": "ShadowEngine.run", "condition": "build_if_missing=True with training_df"},
        {"file": "tradingbot/ml/integration/kernel_shadow_runner.py", "function": "_ensure_artifacts", "condition": "model.pkl missing → direct freeze"},
        {"file": "tradingbot/ml/shadow/ml_adapter.py", "function": "MLAdapter.load", "condition": "training_df is not None"},
        {"file": "tests/test_ml_paper_phase9_10.py", "function": "multiple", "condition": "pytest temp base_dir"},
        {"file": "tests/test_ml_phase10_1_kernel_bridge.py", "function": "setup", "condition": "pytest temp base_dir"},
        {"file": "tests/test_ml_phase10_2_live_shadow.py", "function": "setup", "condition": "pytest temp base_dir"},
        {"file": "tests/test_ml_phase11_paper.py", "function": "setup", "condition": "pytest temp base_dir"},
        {"file": "tests/test_ml_shadow_phase10.py", "function": "setup", "condition": "pytest temp base_dir"},
        {"file": "tests/test_ml_phase10_4_monitoring.py", "function": "setup", "condition": "pytest temp base_dir"},
    ]

    non_phase99_writes = [
        {
            "note": "Trend v40/v41 bundles use separate writers (not Phase 9.9 RANGE registry)",
            "files": [
                "tradingbot/ml/phase15a/trend_bundle.py",
                "tradingbot/ml/phase17d/bundle_freeze.py",
            ],
        }
    ]

    return {
        "phase": "22AC",
        "phase9_9_production_write_function": "freeze_phase9_9_artifacts",
        "single_writer_function": True,
        "write_paths": write_paths,
        "indirect_callers": indirect_callers,
        "no_other_phase9_9_writers_found": True,
        "related_non_phase99": non_phase99_writes,
    }


def build_dependency_graph() -> dict[str, Any]:
    """STEP 5 — upstream/downstream dependency graph."""
    nodes = [
        {"id": "training", "label": "Training", "depth_upstream": 0, "depth_downstream": 5},
        {"id": "acceptance", "label": "Acceptance", "depth_upstream": 1, "depth_downstream": 4},
        {"id": "freeze", "label": "Freeze", "depth_upstream": 0, "depth_downstream": 4},
        {"id": "registry", "label": "Registry", "depth_upstream": 2, "depth_downstream": 3},
        {"id": "loading", "label": "Loading", "depth_upstream": 3, "depth_downstream": 2},
        {"id": "runtime", "label": "Runtime", "depth_upstream": 4, "depth_downstream": 1},
        {"id": "live_trading", "label": "Live Trading", "depth_upstream": 5, "depth_downstream": 0},
        {"id": "shadow", "label": "Shadow", "depth_upstream": 3, "depth_downstream": 2},
        {"id": "health", "label": "Health", "depth_upstream": 4, "depth_downstream": 1},
        {"id": "testing", "label": "Testing", "depth_upstream": 2, "depth_downstream": 1},
    ]

    edges = [
        {"from": "training", "to": "acceptance", "relation": "RobustnessOptimizer → evaluate_acceptance → JSON reports"},
        {"from": "training", "to": "freeze", "relation": "NO CODE EDGE — optimizer never calls freeze"},
        {"from": "freeze", "to": "registry", "relation": "freeze_phase9_9_artifacts writes phase9_9_best/"},
        {"from": "registry", "to": "loading", "relation": "load_phase9_9_bundle reads artifacts"},
        {"from": "loading", "to": "runtime", "relation": "EngineRegistry, RangeEngineAdapter, MLAdapter"},
        {"from": "runtime", "to": "live_trading", "relation": "PipelineCache → kernel decision path"},
        {"from": "loading", "to": "shadow", "relation": "ShadowEngine, KernelShadowRunner, MLAdapter"},
        {"from": "shadow", "to": "freeze", "relation": "build_if_missing=True / _ensure_artifacts back-edge"},
        {"from": "loading", "to": "health", "relation": "HealthGate verify_bundle_integrity"},
        {"from": "health", "to": "live_trading", "relation": "require_health → fallback if fail"},
        {"from": "freeze", "to": "testing", "relation": "pytest direct freeze to temp dirs"},
        {"from": "registry", "to": "testing", "relation": "research forensics read build_if_missing=False"},
    ]

    return {
        "phase": "22AC",
        "nodes": nodes,
        "edges": edges,
        "max_upstream_depth": 5,
        "max_downstream_depth": 5,
        "critical_back_edge": "shadow → freeze (can overwrite production artifacts)",
    }


def build_hidden_couplings() -> dict[str, Any]:
    """STEP 6 — hidden couplings around registry and freeze."""
    couplings = [
        {
            "id": "default_config_vs_optimizer",
            "description": "Registry freeze assumes DEFAULT_CONFIG logistic_strong_reg; optimizer ranks different candidates",
            "components": ["model_registry.DEFAULT_CONFIG", "RobustnessOptimizer.select_best"],
            "risk": "CRITICAL",
        },
        {
            "id": "default_build_if_missing_true",
            "description": "load_phase9_9_bundle defaults build_if_missing=True; production callers must opt out explicitly",
            "components": ["load_phase9_9_bundle"],
            "risk": "HIGH",
        },
        {
            "id": "range_adapter_base_dir_none",
            "description": "RangeEngineAdapter.load ignores caller base_dir; always load_phase9_9_bundle(base_dir=None)",
            "components": ["RangeEngineAdapter.load", "EngineRegistry.build_default"],
            "risk": "HIGH",
        },
        {
            "id": "paper_expected_features_static",
            "description": "paper/config EXPECTED_FEATURES from DEFAULT_CONFIG at import; not loaded from artifact feature_order.json",
            "components": ["paper/config.py", "validate_frozen_model"],
            "risk": "MEDIUM",
        },
        {
            "id": "health_metadata_partial",
            "description": "HealthGate checks metadata/feature_order file existence; model.pkl failure is separate via verify_bundle_integrity",
            "components": ["HealthGate", "load_phase9_9_bundle"],
            "risk": "HIGH",
        },
        {
            "id": "metadata_without_model",
            "description": "Sidecar JSON can exist while model.pkl missing — health may fail predict check but files partially present",
            "components": ["artifact store", "EngineRegistry sha256"],
            "risk": "CRITICAL",
        },
        {
            "id": "shadow_rebuilds_artifacts",
            "description": "ShadowEngine and KernelShadowRunner can invoke freeze without acceptance gate",
            "components": ["ShadowEngine", "KernelShadowRunner"],
            "risk": "CRITICAL",
        },
        {
            "id": "pipeline_cache_no_rebuild",
            "description": "PipelineCache uses build_if_missing=False — does NOT trigger rebuild (safe read path)",
            "components": ["PipelineCache"],
            "risk": "SAFE",
        },
        {
            "id": "robustness_score_in_metadata",
            "description": "metadata.robustness_score read from report JSON at freeze time; stale if report updated without re-freeze",
            "components": ["freeze_phase9_9_artifacts", "_load_phase99_score"],
            "risk": "MEDIUM",
        },
        {
            "id": "engine_registry_double_load",
            "description": "EngineRegistry loads bundle twice: load_phase9_9_bundle + RangeEngineAdapter.load (separate bundle instances)",
            "components": ["EngineRegistry.build_default", "RangeEngineAdapter"],
            "risk": "MEDIUM",
        },
    ]

    return {
        "phase": "22AC",
        "couplings": couplings,
        "count_by_risk": {
            "CRITICAL": sum(1 for c in couplings if c["risk"] == "CRITICAL"),
            "HIGH": sum(1 for c in couplings if c["risk"] == "HIGH"),
            "MEDIUM": sum(1 for c in couplings if c["risk"] == "MEDIUM"),
            "SAFE": sum(1 for c in couplings if c["risk"] == "SAFE"),
        },
    }


def build_impact_radius(*, usage_scan: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """STEP 7 — classify every dependency by change risk."""
    load_hits = usage_scan.get("load_phase9_9_bundle", [])
    production_paths = {
        "tradingbot/ml/phase15a/engine_registry.py",
        "tradingbot/ml/integration/health_gate.py",
        "tradingbot/ml/integration/pipeline_cache.py",
        "tradingbot/ml/research/regime_router/range_engine_adapter.py",
        "tradingbot/ml/shadow/ml_adapter.py",
        "tradingbot/ml/paper_trading/shadow_engine.py",
        "tradingbot/ml/integration/kernel_shadow_runner.py",
        "tradingbot/ml/paper/config.py",
        "tradingbot/ml/paper_trading/model_registry.py",
    }

    classifications: list[dict[str, Any]] = []
    for path in sorted(production_paths):
        if "model_registry.py" in path:
            classifications.append(
                {"path": path, "classification": "CRITICAL", "why": "Single freeze/load implementation; DEFAULT_CONFIG anchor"}
            )
        elif "kernel_shadow_runner" in path or "shadow_engine" in path:
            classifications.append(
                {"path": path, "classification": "CRITICAL", "why": "Can auto-freeze/overwrite artifacts without acceptance"}
            )
        elif "range_engine_adapter" in path:
            classifications.append(
                {"path": path, "classification": "HIGH", "why": "Production RANGE inference; hardcoded base_dir=None load path"}
            )
        elif "health_gate" in path or "engine_registry" in path or "pipeline_cache" in path:
            classifications.append(
                {"path": path, "classification": "HIGH", "why": "Live kernel pipeline load/validate path"}
            )
        elif "paper/config" in path:
            classifications.append(
                {"path": path, "classification": "HIGH", "why": "EXPECTED_FEATURES tied to DEFAULT_CONFIG not dynamic artifact"}
            )
        else:
            classifications.append({"path": path, "classification": "MEDIUM", "why": "Runtime consumer of frozen bundle"})

    research_count = sum(1 for h in load_hits if "/research/" in h["file"] or h["file"].startswith("tradingbot/ml/research/"))
    test_count = sum(1 for h in load_hits if h["file"].startswith("tests/"))

    classifications.extend(
        [
            {"path": "tradingbot/ml/research/** (forensics)", "classification": "SAFE", "why": f"{research_count} read-only research references"},
            {"path": "tests/**", "classification": "MEDIUM", "why": f"{test_count} references; temp-dir freeze in pytest"},
            {"path": "scripts/train_model.py --phase9-9", "classification": "MEDIUM", "why": "Selection reports only; no freeze coupling"},
            {"path": "data/ml/research/phase9_9_best/", "classification": "CRITICAL", "why": "Production artifact store; partial state possible"},
        ]
    )

    return {
        "phase": "22AC",
        "classifications": classifications,
        "load_phase9_9_bundle_reference_count": len(load_hits),
        "freeze_change_blast_radius": "CRITICAL — affects RANGE engine, health gate, shadow, paper validation",
    }


def determine_verdict(authority: dict[str, Any], couplings: dict[str, Any]) -> str:
    """Return exactly one final verdict token."""
    if not authority.get("authorities"):
        return "INSUFFICIENT_EVIDENCE"
    if authority.get("single_authority") is True:
        return "MODEL_REGISTRY_IS_SINGLE_AUTHORITY"
    critical = couplings.get("count_by_risk", {}).get("CRITICAL", 0)
    if not authority.get("single_authority") and critical >= 2:
        return "MULTIPLE_AUTHORITIES_EXIST"
    if critical >= 1:
        return "HIDDEN_RUNTIME_COUPLING"
    return "MULTIPLE_AUTHORITIES_EXIST"


def run_investigation(*, base_dir: str | None = None) -> dict[str, Any]:
    usage = scan_repository_usage()
    architecture = build_model_registry_architecture(base_dir=base_dir)
    authority = build_authority_analysis(base_dir=base_dir)
    write_paths = build_artifact_write_paths()
    graph = build_dependency_graph()
    couplings = build_hidden_couplings()
    impact = build_impact_radius(usage_scan=usage)
    verdict = determine_verdict(authority, couplings)

    return {
        "model_registry_architecture": architecture,
        "repository_usage_index": usage,
        "authority_analysis": authority,
        "artifact_write_paths": write_paths,
        "bundle_dependency_graph": graph,
        "hidden_couplings": couplings,
        "impact_radius": impact,
        "verdict": verdict,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "production_modified": False,
    }
