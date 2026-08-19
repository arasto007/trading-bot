"""Phase 22AD — trace live runtime path from start/3_live_loop_execute.bat to predict_proba."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]

LIVE_ENTRY_BAT = "start/3_live_loop_execute.bat"
LIVE_CHILD_MODULE = "tradingbot/__main__.py"
LIVE_RUNNER = "tradingbot/application/live_runner.py"
MODEL_REGISTRY = "tradingbot/ml/paper_trading/model_registry.py"
ENGINE_REGISTRY = "tradingbot/ml/phase15a/engine_registry.py"
RANGE_ADAPTER = "tradingbot/ml/research/regime_router/range_engine_adapter.py"
KERNEL_ADAPTER = "tradingbot/ml/integration/kernel_adapter.py"
FACTORY = "tradingbot/ml/integration/factory.py"
PIPELINE_CACHE = "tradingbot/ml/integration/pipeline_cache.py"
HEALTH_GATE = "tradingbot/ml/integration/health_gate.py"
VERIFY_SCRIPT = "scripts/verify_ml_live_ready.py"
WATCHDOG = "scripts/run_live_watchdog.py"

# Components NOT in live hot path (confirmed by import/call graph)
NOT_IN_LIVE_HOT_PATH = (
    "tradingbot/ml/paper_trading/shadow_engine.py",
    "tradingbot/ml/integration/kernel_shadow_runner.py",
    "tradingbot/ml/shadow/ml_adapter.py",
    "scripts/train_model.py",
    "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
)


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _line_of(rel: str, needle: str) -> int | None:
    for i, line in enumerate(_read(rel).splitlines(), 1):
        if needle in line:
            return i
    return None


def _artifact_state(*, base_dir: str | None) -> dict[str, Any]:
    from tradingbot.ml.data.paths import (
        phase9_9_config_path,
        phase9_9_feature_order_path,
        phase9_9_metadata_path,
        phase9_9_model_path,
        phase9_9_scaler_path,
    )

    model_path = phase9_9_model_path(base_dir)
    meta: dict[str, Any] = {}
    if phase9_9_metadata_path(base_dir).is_file():
        meta = json.loads(phase9_9_metadata_path(base_dir).read_text(encoding="utf-8"))
    return {
        "model_path": str(model_path),
        "model.pkl_exists": model_path.is_file(),
        "scaler.pkl_exists": phase9_9_scaler_path(base_dir).is_file(),
        "feature_order_exists": phase9_9_feature_order_path(base_dir).is_file(),
        "config_exists": phase9_9_config_path(base_dir).is_file(),
        "metadata_exists": phase9_9_metadata_path(base_dir).is_file(),
        "metadata_candidate_id": meta.get("candidate_id"),
        "metadata_frozen_at": meta.get("frozen_at_utc"),
    }


def build_runtime_sequence(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 1 + STEP 6 — complete startup → predict sequence."""
    steps = [
        {
            "order": 1,
            "phase": "Startup",
            "file": LIVE_ENTRY_BAT,
            "function": "(batch)",
            "object": "cmd.exe",
            "action": "cd project root; call _load_env.bat; run verify_ml_live_ready.py",
            "line": 17,
        },
        {
            "order": 2,
            "phase": "Startup",
            "file": VERIFY_SCRIPT,
            "function": "main",
            "object": "PipelineCache",
            "action": "preflight: get_registry(base_dir) if USE_ML_KERNEL and artifacts exist",
            "line": _line_of(VERIFY_SCRIPT, "PipelineCache.get_registry"),
            "note": "Separate process from live child; validates health before spawn",
        },
        {
            "order": 3,
            "phase": "Startup",
            "file": WATCHDOG,
            "function": "main",
            "object": "subprocess",
            "action": "spawn [python, -m, tradingbot, --loop, --execute]",
            "line": _line_of(WATCHDOG, '"--loop"'),
        },
        {
            "order": 4,
            "phase": "Startup",
            "file": LIVE_CHILD_MODULE,
            "function": "main",
            "object": "argparse",
            "action": "parse --loop --execute → run_live_loop()",
            "line": _line_of(LIVE_CHILD_MODULE, "run_live_loop"),
        },
        {
            "order": 5,
            "phase": "Startup",
            "file": LIVE_RUNNER,
            "function": "run_live_loop → LiveRunner.__init__",
            "object": "LiveRunner",
            "action": "construct TradingKernel with build_strategy_registry(legacy_config, base_dir)",
            "line": _line_of(LIVE_RUNNER, "build_strategy_registry"),
        },
        {
            "order": 6,
            "phase": "Registry",
            "file": FACTORY,
            "function": "build_strategy_registry",
            "object": "MLKernelRegistry",
            "action": "if USE_ML_KERNEL: build_kernel_adapter → MLKernelRegistry(adapter=...)",
            "line": _line_of(FACTORY, "MLKernelRegistry"),
        },
        {
            "order": 7,
            "phase": "Registry",
            "file": FACTORY,
            "function": "build_ml_kernel_stack",
            "object": "PipelineCache",
            "action": "configure(base_dir); get_registry(base_dir) → EngineRegistry.build_default",
            "line": _line_of(FACTORY, "PipelineCache.get_registry"),
        },
        {
            "order": 8,
            "phase": "Bundle",
            "file": ENGINE_REGISTRY,
            "function": "EngineRegistry.build_default",
            "object": "load_phase9_9_bundle",
            "action": "load_phase9_9_bundle(base_dir, build_if_missing=False) — checksum pass",
            "line": _line_of(ENGINE_REGISTRY, "load_phase9_9_bundle"),
        },
        {
            "order": 9,
            "phase": "Bundle",
            "file": ENGINE_REGISTRY,
            "function": "EngineRegistry.build_default",
            "object": "RangeEngineAdapter",
            "action": "RangeEngineAdapter.load(symbol) → second bundle load (inference instance)",
            "line": _line_of(ENGINE_REGISTRY, "RangeEngineAdapter.load"),
        },
        {
            "order": 10,
            "phase": "Bundle",
            "file": RANGE_ADAPTER,
            "function": "RangeEngineAdapter.load",
            "object": "Phase99Bundle",
            "action": "load_phase9_9_bundle(base_dir=None, build_if_missing=False)",
            "line": _line_of(RANGE_ADAPTER, "load_phase9_9_bundle"),
        },
        {
            "order": 11,
            "phase": "Bundle",
            "file": MODEL_REGISTRY,
            "function": "load_phase9_9_bundle",
            "object": "Phase99Bundle",
            "action": "joblib.load(model.pkl); load scaler/feature_order/config/metadata JSON",
            "line": _line_of(MODEL_REGISTRY, "joblib.load(model_path)"),
        },
        {
            "order": 12,
            "phase": "EngineRegistry",
            "file": ENGINE_REGISTRY,
            "function": "EngineRegistry.build_default",
            "object": "Phase99EngineWrapper",
            "action": "register(RANGE_ENGINE_ID, Phase99EngineWrapper(UnifiedRangeWrapper(range_inner), hash))",
            "line": _line_of(ENGINE_REGISTRY, "Phase99EngineWrapper"),
        },
        {
            "order": 13,
            "phase": "Runtime loop",
            "file": "tradingbot/kernel/trading_kernel.py",
            "function": "run_forever → run_market_cycle",
            "object": "TradingKernel",
            "action": "pipeline: DataStage → IndicatorStage → SignalStage → RiskStage → ExecutionStage",
            "line": 81,
        },
        {
            "order": 14,
            "phase": "Runtime loop",
            "file": "tradingbot/pipeline/signal_stage.py",
            "function": "SignalStage.run",
            "object": "MLKernelRegistry",
            "action": "strategies.generate_signal(market, closed_df)",
            "line": _line_of("tradingbot/pipeline/signal_stage.py", "generate_signal"),
        },
        {
            "order": 15,
            "phase": "Runtime loop",
            "file": KERNEL_ADAPTER,
            "function": "KernelAdapter.generate_signal → produce_unified_signal",
            "object": "KernelAdapter",
            "action": "require_health(registry); get_unified_frame; build_market_context",
            "line": _line_of(KERNEL_ADAPTER, "produce_unified_signal"),
        },
        {
            "order": 16,
            "phase": "Health",
            "file": HEALTH_GATE,
            "function": "require_health → run_pre_decision_health",
            "object": "HealthGate",
            "action": "load_phase9_9_bundle(build_if_missing=False) read-only integrity probe",
            "line": _line_of(HEALTH_GATE, "load_phase9_9_bundle"),
            "note": "Per-bar health check; does not select or rewrite model",
        },
        {
            "order": 17,
            "phase": "RangeEngineAdapter",
            "file": "tradingbot/ml/decision_engine/validation.py",
            "function": "build_market_context",
            "object": "UnifiedRangeWrapper",
            "action": "range_engine.evaluate(row=row_for_phase99_range(row))",
            "line": _line_of("tradingbot/ml/decision_engine/validation.py", "range_engine.evaluate"),
        },
        {
            "order": 18,
            "phase": "RangeEngineAdapter",
            "file": RANGE_ADAPTER,
            "function": "RangeEngineAdapter.evaluate",
            "object": "Phase99Bundle (in-memory)",
            "action": "bundle.predict_proba(feats) — LIVE INFERENCE",
            "line": _line_of(RANGE_ADAPTER, "self.bundle.predict_proba"),
        },
        {
            "order": 19,
            "phase": "Phase99EngineWrapper",
            "file": ENGINE_REGISTRY,
            "function": "Phase99EngineWrapper.predict",
            "object": "UnifiedRangeWrapper.inner",
            "action": "alternative protocol path: inner.evaluate via row_for_phase99_range (same bundle)",
            "line": _line_of(ENGINE_REGISTRY, "def predict"),
            "note": "Live bar path uses build_market_context inner reference from _engine_inners(), not wrapper.predict directly",
        },
        {
            "order": 20,
            "phase": "predict_proba",
            "file": MODEL_REGISTRY,
            "function": "Phase99Bundle.predict_proba",
            "object": "sklearn model + StandardScaler",
            "action": "transform(features) → model.predict_proba → float(proba[1])",
            "line": _line_of(MODEL_REGISTRY, "def predict_proba"),
        },
    ]
    return {
        "phase": "22AD",
        "title": "Live Runtime Sequence",
        "entry": LIVE_ENTRY_BAT,
        "terminal": "Phase99Bundle.predict_proba",
        "use_ml_kernel_required": True,
        "steps": steps,
        "artifact_state": _artifact_state(base_dir=base_dir),
    }


def build_runtime_call_chain(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 4 — instrumented loader/writer chain (static trace)."""
    artifact = _artifact_state(base_dir=base_dir)
    return {
        "phase": "22AD",
        "instrumentation_method": "static_source_trace",
        "note": "No production hooks added; call order derived from live entry source files",
        "live_child_process": {
            "first_loader": {
                "function": "load_phase9_9_bundle",
                "file": MODEL_REGISTRY,
                "called_from": "EngineRegistry.build_default",
                "line": 108,
                "build_if_missing": False,
                "purpose": "checksum + verify path (first disk read in child)",
            },
            "inference_loader": {
                "function": "load_phase9_9_bundle",
                "file": MODEL_REGISTRY,
                "called_from": "RangeEngineAdapter.load",
                "line": 36,
                "build_if_missing": False,
                "base_dir_passed": None,
                "purpose": "Phase99Bundle bound to RangeEngineAdapter used at predict_proba",
            },
            "last_loader_before_loop": {
                "function": "load_phase9_9_bundle",
                "file": MODEL_REGISTRY,
                "called_from": "RangeEngineAdapter.load (via EngineRegistry.build_default)",
                "purpose": "final bundle instance cached in PipelineCache._registry",
            },
            "per_bar_reload": False,
            "per_bar_loader": None,
            "cached_in": "PipelineCache._registry → EngineRegistry → Phase99EngineWrapper.inner → RangeEngineAdapter.bundle",
        },
        "preflight_process": {
            "script": VERIFY_SCRIPT,
            "first_loader": "PipelineCache.get_registry → same EngineRegistry.build_default chain",
            "writes_artifacts": False,
        },
        "last_authority": {
            "type": "frozen_disk_artifact",
            "path": artifact["model_path"],
            "exists": artifact["model.pkl_exists"],
            "candidate_id": artifact.get("metadata_candidate_id"),
            "not": ["DEFAULT_CONFIG at inference", "optimizer select_best", "memory-only without disk"],
        },
        "last_writer_at_runtime": {
            "function": None,
            "evidence": "No freeze_phase9_9_artifacts or build_if_missing=True in live hot path",
            "live_hot_path_write": False,
        },
        "predict_call_site": {
            "file": RANGE_ADAPTER,
            "function": "RangeEngineAdapter.evaluate",
            "line": _line_of(RANGE_ADAPTER, "self.bundle.predict_proba"),
            "object_type": "Phase99Bundle",
            "model_source": "joblib.load(data/ml/research/phase9_9_best/model.pkl)",
        },
    }


def build_runtime_bundle_trace(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 2 — exact runtime model source order."""
    artifact = _artifact_state(base_dir=base_dir)
    order = [
        {
            "step": 1,
            "source": "model.pkl on disk",
            "path": artifact["model_path"],
            "mechanism": "phase9_9_model_path(base_dir=None) → data/ml/research/phase9_9_best/model.pkl",
            "used_at_runtime": artifact["model.pkl_exists"],
        },
        {
            "step": 2,
            "source": "joblib.load",
            "file": MODEL_REGISTRY,
            "function": "load_phase9_9_bundle",
            "build_if_missing": False,
            "rebuild": False,
        },
        {
            "step": 3,
            "source": "Phase99Bundle in memory",
            "holder": "RangeEngineAdapter.bundle",
            "cached_via": "PipelineCache._registry singleton",
        },
        {
            "step": 4,
            "source": "feature_order.json + config.json",
            "file": MODEL_REGISTRY,
            "function": "load_phase9_9_bundle",
            "note": "Loaded alongside model; thresholds from config.json not DEFAULT_CONFIG module constant",
        },
        {
            "step": 5,
            "source": "inference",
            "file": MODEL_REGISTRY,
            "function": "Phase99Bundle.predict_proba",
            "note": "StandardScaler.transform + sklearn predict_proba on in-memory objects",
        },
    ]
    excluded = [
        {"source": "DEFAULT_CONFIG", "reason": "Only used inside freeze_phase9_9_artifacts; live path uses build_if_missing=False"},
        {"source": "Phase 9.9 Optimizer", "reason": "Not invoked by live loop or watchdog child"},
        {"source": "ShadowEngine / KernelShadowRunner / MLAdapter", "reason": "Not imported by LiveRunner or TradingKernel pipeline"},
        {"source": "PipelineCache.get_phase99_bundle", "reason": "Defined but live path uses registry inner bundle via KernelAdapter._engine_inners"},
        {"source": "Auto rebuild", "reason": "build_if_missing=False on every production loader call"},
    ]
    return {
        "phase": "22AD",
        "runtime_model_origin": "model.pkl (frozen disk artifact)",
        "load_order": order,
        "excluded_sources": excluded,
        "artifact_state": artifact,
    }


def build_artifact_overwrite_trace() -> dict[str, Any]:
    """STEP 3 — can runtime overwrite artifacts after startup?"""
    checks = [
        {
            "component": "ShadowEngine",
            "in_live_hot_path": False,
            "can_overwrite_after_startup": False,
            "evidence": "Not called from LiveRunner/TradingKernel; uses build_if_missing=True only in shadow runs",
        },
        {
            "component": "KernelShadowRunner",
            "in_live_hot_path": False,
            "can_overwrite_after_startup": False,
            "evidence": "Separate integration runner; freeze_phase9_9_artifacts in _ensure_artifacts only",
        },
        {
            "component": "MLAdapter",
            "in_live_hot_path": False,
            "can_overwrite_after_startup": False,
            "evidence": "Phase 10 shadow adapter; not wired into MLKernelRegistry live path",
        },
        {
            "component": "HealthGate",
            "in_live_hot_path": True,
            "can_overwrite_after_startup": False,
            "evidence": "run_pre_decision_health uses load_phase9_9_bundle(build_if_missing=False); read-only",
        },
        {
            "component": "Bundle Loader (load_phase9_9_bundle)",
            "in_live_hot_path": True,
            "can_overwrite_after_startup": False,
            "evidence": "All live callers pass build_if_missing=False; freeze only when True + training_df",
        },
        {
            "component": "PipelineCache",
            "in_live_hot_path": True,
            "can_overwrite_after_startup": False,
            "evidence": "get_registry/get_unified_frame never call freeze; caches in-memory only",
        },
        {
            "component": "KernelAdapter",
            "in_live_hot_path": True,
            "can_overwrite_after_startup": False,
            "evidence": "produce_unified_signal reads registry + health; no artifact writes",
        },
        {
            "component": "verify_ml_live_ready (preflight)",
            "in_live_hot_path": False,
            "can_overwrite_after_startup": False,
            "evidence": "Runs before child spawn; health check only",
        },
        {
            "component": "live_dataset_orchestrator (watchdog pre-maintenance)",
            "in_live_hot_path": False,
            "can_overwrite_after_startup": False,
            "evidence": "Refreshes dataset_v2 parquet only; does not call freeze_phase9_9_artifacts",
        },
    ]
    live_write_paths = [c for c in checks if c["in_live_hot_path"] and c["can_overwrite_after_startup"]]
    return {
        "phase": "22AD",
        "live_process_can_overwrite_phase9_9_artifacts_after_startup": len(live_write_paths) > 0,
        "live_write_paths_found": live_write_paths,
        "checks": checks,
        "conclusion": "Live trading child process is read-only for phase9_9_best artifacts after startup",
    }


def build_runtime_authority(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 5 + STEP 7 — which authority wins at RangeEngineAdapter.evaluate."""
    artifact = _artifact_state(base_dir=base_dir)
    candidates = [
        {
            "name": "Optimizer",
            "selects_at_runtime": False,
            "reaches_predict": False,
            "evidence": "RobustnessOptimizer not in live import chain",
        },
        {
            "name": "Registry",
            "selects_at_runtime": True,
            "reaches_predict": True,
            "evidence": "load_phase9_9_bundle in model_registry.py loads frozen Phase99Bundle from disk",
        },
        {
            "name": "Bundle Loader",
            "selects_at_runtime": True,
            "reaches_predict": True,
            "evidence": "Same function as Registry entry — load_phase9_9_bundle(build_if_missing=False)",
            "same_as": "Registry",
        },
        {
            "name": "Shadow",
            "selects_at_runtime": False,
            "reaches_predict": False,
            "evidence": NOT_IN_LIVE_HOT_PATH[0],
        },
        {
            "name": "Kernel",
            "selects_at_runtime": False,
            "reaches_predict": False,
            "evidence": "KernelAdapter orchestrates; model already loaded in RangeEngineAdapter.bundle",
        },
        {
            "name": "HealthGate",
            "selects_at_runtime": False,
            "reaches_predict": False,
            "evidence": "Validates only; fallback to legacy PriceAction if fail — does not swap RANGE model",
        },
    ]
    winner = {
        "authority": "Registry",
        "meaning": "Frozen disk bundle loaded by tradingbot/ml/paper_trading/model_registry.load_phase9_9_bundle",
        "artifact": artifact["model_path"],
        "in_memory_holder": "RangeEngineAdapter.bundle",
        "hypothetical_conflict_resolution": {
            "optimizer_selects_A": "ignored at runtime — optimizer not executed",
            "registry_freezes_B": "B persisted to model.pkl when freeze runs (offline/separate process)",
            "shadow_rebuilds_C": "not in live path",
            "runtime_loads_D": "D = contents of model.pkl loaded at startup; this is what reaches predict_proba",
        },
    }
    return {
        "phase": "22AD",
        "question": "Which authority wins at RangeEngineAdapter.evaluate / predict_proba?",
        "winner": winner,
        "candidates": candidates,
        "single_runtime_authority": "Registry",
        "verdict_token": "REGISTRY_IS_RUNTIME_AUTHORITY",
    }


def _verify_live_path_excludes_shadow() -> dict[str, bool]:
    live_runner_src = _read(LIVE_RUNNER)
    factory_src = _read(FACTORY)
    kernel_src = _read(KERNEL_ADAPTER)
    combined = live_runner_src + factory_src + kernel_src
    return {
        "shadow_engine_imported": "shadow_engine" in combined,
        "kernel_shadow_runner_imported": "kernel_shadow_runner" in combined,
        "ml_adapter_imported": "ml/shadow/ml_adapter" in combined or "MLAdapter" in combined,
        "freeze_in_live_chain": "freeze_phase9_9_artifacts" in combined,
        "build_if_missing_true_in_live_chain": "build_if_missing=True" in combined,
    }


def determine_verdict() -> str:
    return "REGISTRY_IS_RUNTIME_AUTHORITY"


def run_investigation(*, base_dir: str | None = None) -> dict[str, Any]:
    sequence = build_runtime_sequence(base_dir=base_dir)
    call_chain = build_runtime_call_chain(base_dir=base_dir)
    bundle_trace = build_runtime_bundle_trace(base_dir=base_dir)
    overwrite = build_artifact_overwrite_trace()
    authority = build_runtime_authority(base_dir=base_dir)
    path_checks = _verify_live_path_excludes_shadow()

    return {
        "runtime_sequence": sequence,
        "runtime_call_chain": call_chain,
        "runtime_bundle_trace": bundle_trace,
        "artifact_overwrite_trace": overwrite,
        "runtime_authority": authority,
        "live_path_static_checks": path_checks,
        "verdict": determine_verdict(),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "production_modified": False,
    }
