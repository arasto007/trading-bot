"""
Phase 24B — static architecture reverse engineering from source code.

All behavior claims cite file:line evidence. No production code is modified.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# --- path helpers ---

def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _line_of(rel: str, needle: str) -> int | None:
    for i, line in enumerate(_read(rel).splitlines(), 1):
        if needle in line:
            return i
    return None


def _fn_line(rel: str, fn_name: str) -> int | None:
    tree = ast.parse(_read(rel))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return node.lineno
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- live startup trace (extends phase22ad) ---

LIVE_ENTRY_BAT = "RUN_DASHBOARD.bat"
LIVE_MODULE = "tradingbot/__main__.py"
LIVE_RUNNER = "tradingbot/application/live_runner.py"
KERNEL = "tradingbot/kernel/trading_kernel.py"
FACTORY = "tradingbot/ml/integration/factory.py"
KERNEL_ADAPTER = "tradingbot/ml/integration/kernel_adapter.py"
ML_REGISTRY = "tradingbot/ml/integration/ml_kernel_registry.py"
PIPELINE_CACHE = "tradingbot/ml/integration/pipeline_cache.py"
HEALTH_GATE = "tradingbot/ml/integration/health_gate.py"
ENGINE_REGISTRY = "tradingbot/ml/phase15a/engine_registry.py"
MODEL_REGISTRY = "tradingbot/ml/paper_trading/model_registry.py"
RANGE_ADAPTER = "tradingbot/ml/research/regime_router/range_engine_adapter.py"
MT5_EXEC = "tradingbot/adapters/mt5_execution.py"
MT5_DATA = "tradingbot/adapters/mt5_market_data.py"
RISK_STAGE = "tradingbot/pipeline/risk_stage.py"
EXEC_STAGE = "tradingbot/pipeline/execution_stage.py"
SIGNAL_STAGE = "tradingbot/pipeline/signal_stage.py"
DATA_STAGE = "tradingbot/pipeline/data_stage.py"
IND_STAGE = "tradingbot/pipeline/indicator_stage.py"
ORCHESTRATOR = "tradingbot/ml/decision_engine/orchestrator.py"
VALIDATION = "tradingbot/ml/decision_engine/validation.py"
UNIFIED_FEATURES = "tradingbot/ml/research/phase13_9/unified_features.py"
REGIME_CLASSIFIER = "tradingbot/ml/research/regime_detector/regime_classifier.py"
FILTERS = "tradingbot/ml/phase19c/filters.py"
REGIME_FILTERS = "tradingbot/ml/integration/regime_filter_profiles.py"
HOLD_CHAIN = "tradingbot/ml/research/phase22c/hold_chain.py"
TRADE_QUALITY = "tradingbot/ml/trade_quality/adapter.py"


def build_live_pipeline_trace(*, base_dir: str | None = None) -> dict[str, Any]:
    """Complete startup → order_send call sequence with line numbers."""
    from tradingbot.ml.research.phase22ad.runtime_trace import (
        build_runtime_sequence,
        _artifact_state,
    )

    seq = build_runtime_sequence(base_dir=base_dir)
    execution_tail = [
        {
            "order": 21,
            "phase": "Kernel pipeline",
            "file": RISK_STAGE,
            "function": "RiskStage.run",
            "action": "risk.evaluate(signal, snap) — IRiskGate legacy RiskManager",
            "line": _line_of(RISK_STAGE, "self._risk.evaluate"),
            "input": "TradingSignal + portfolio_snapshot + ohlcv + htf_bias",
            "output": "RiskDecision on ctx.risk; blocks if not allowed",
        },
        {
            "order": 22,
            "phase": "Kernel pipeline",
            "file": EXEC_STAGE,
            "function": "ExecutionStage.run",
            "action": "executor.execute(signal, lot)",
            "line": _line_of(EXEC_STAGE, "self._executor.execute"),
            "input": "TradingSignal, lot (signal.lot_size or default 0.01)",
            "output": "ExecutionResult on ctx.execution",
        },
        {
            "order": 23,
            "phase": "MT5 execution",
            "file": MT5_EXEC,
            "function": "Mt5ExecutionAdapter.execute",
            "action": "dry_run / paper / live branch",
            "line": _fn_line(MT5_EXEC, "execute"),
            "branches": [
                {"condition": "TRADINGBOT_DRY_RUN=1", "line": 44, "result": "success=True, no order_send"},
                {"condition": "TRADINGBOT_PAPER=1", "line": 68, "result": "journal simulated fill"},
                {"condition": "live", "line": 88, "result": "_place_market_order → mt5.order_send"},
            ],
        },
        {
            "order": 24,
            "phase": "MT5 execution",
            "file": MT5_EXEC,
            "function": "_place_market_order → _order_send_with_retry",
            "action": "mt5.order_send(request) with retry on retcodes 10004,10006,...",
            "line": _line_of(MT5_EXEC, "result = mt5.order_send(request)"),
            "guards": [
                {"fn": "order_logic.validate_order", "line": 138},
                {"fn": "order_logic.check_order_risk", "line": 143},
            ],
        },
    ]
    ml_inner = [
        {
            "order": "15a",
            "file": KERNEL_ADAPTER,
            "function": "produce_unified_signal",
            "action": "PipelineCache.get_unified_frame → build_market_context → quality.evaluate",
            "line": _fn_line(KERNEL_ADAPTER, "produce_unified_signal"),
        },
        {
            "order": "15b",
            "file": VALIDATION,
            "function": "build_market_context",
            "action": "rule_classify_row → range_engine.evaluate → trend_engine.evaluate",
            "line": _fn_line(VALIDATION, "build_market_context"),
        },
        {
            "order": "15c",
            "file": TRADE_QUALITY,
            "function": "TradeQualityAdapter.evaluate",
            "action": "risk_adapter.evaluate → quality_engine.evaluate (chains calibration+risk+quality)",
            "line": _fn_line(TRADE_QUALITY, "evaluate"),
        },
        {
            "order": "15d",
            "file": KERNEL_ADAPTER,
            "function": "produce_unified_signal",
            "action": "select_profitability_filter_settings → apply_profitability_filters → action HOLD gates",
            "line": _line_of(KERNEL_ADAPTER, "apply_profitability_filters"),
        },
        {
            "order": "15e",
            "file": KERNEL_ADAPTER,
            "function": "generate_signal",
            "action": "map_unified_to_trading_signal; return None if HOLD",
            "line": _fn_line(KERNEL_ADAPTER, "generate_signal"),
        },
    ]
    return {
        "phase": "24B",
        "method": "static_source_trace",
        "entry_points": [
            {"path": LIVE_ENTRY_BAT, "note": "batch → verify_ml_live_ready → watchdog"},
            {"path": LIVE_MODULE, "line": _line_of(LIVE_MODULE, "run_live_loop"), "cli": "python -m tradingbot --loop [--execute|--paper]"},
            {"path": LIVE_RUNNER, "line": _fn_line(LIVE_RUNNER, "run"), "function": "LiveRunner.run → asyncio.run(_run)"},
        ],
        "startup_wiring": {
            "file": LIVE_RUNNER,
            "lines": "65-83",
            "components": [
                "Mt5MarketDataAdapter",
                "Mt5ExecutionAdapter",
                "create_risk_gate",
                "Mt5PositionManager",
                "TradingKernel(strategies=build_strategy_registry(...))",
            ],
        },
        "kernel_loop": {
            "file": KERNEL,
            "run_forever": {"line": _fn_line(KERNEL, "run_forever"), "calls": "run_global_cycle + sleep(interval)"},
            "run_global_cycle": {"line": _fn_line(KERNEL, "run_global_cycle"), "steps": [
                "ensure_connected",
                "check_mt5_health",
                "market_data.update_all",
                "run_market_cycle per market",
                "executor.manage_open_positions",
                "position_manager.manage_all",
            ]},
            "pipeline_order": ["DATA", "INDICATORS", "SIGNALS", "RISK", "EXECUTION"],
            "pipeline_constructed_at": {"file": KERNEL, "line": 81},
        },
        "ml_path_when_use_ml_kernel": seq["steps"] + ml_inner + execution_tail,
        "legacy_path_when_use_ml_kernel_false": [
            {"file": FACTORY, "line": 139, "action": "return LegacyStrategyRegistry"},
            {"file": SIGNAL_STAGE, "line": 35, "action": "legacy.generate_signal"},
        ],
        "terminal_live_order": {"file": MT5_EXEC, "function": "mt5.order_send", "line": 240},
        "artifact_state": _artifact_state(base_dir=base_dir),
        "generated_utc": _utc_now(),
    }


def build_module_inventory() -> dict[str, Any]:
    modules = [
        {
            "id": "LiveRunner",
            "path": LIVE_RUNNER,
            "why": "Owns MT5 lifecycle, background services, kill switch, kernel.run_forever loop",
            "called_by": ["tradingbot/__main__.py:run_live_loop"],
            "calls": ["TradingKernel", "build_strategy_registry", "Mt5MarketDataAdapter", "Mt5ExecutionAdapter"],
            "inputs": ["KernelSettings", "dry_run/paper flags"],
            "outputs": ["async live loop until stop/emergency"],
            "assumptions": ["MT5 reachable", "legacy config loaded"],
            "failure_modes": ["MT5 not connected → abort _run line 98-99"],
            "downstream": ["TradingKernel"],
        },
        {
            "id": "TradingKernel",
            "path": KERNEL,
            "why": "Central orchestrator — only place that runs full market cycle pipeline",
            "called_by": ["LiveRunner", "bootstrap.build_kernel_live"],
            "calls": ["DataStage", "IndicatorStage", "SignalStage", "RiskStage", "ExecutionStage"],
            "inputs": ["IMarketDataProvider", "IStrategyRegistry", "IRiskGate", "IOrderExecutor"],
            "outputs": ["CycleContext per market", "TradeJournal entries"],
            "assumptions": ["Pipeline stages run in fixed order", "portfolio snapshot available"],
            "failure_modes": ["Stage returns False → pipeline stops", "EMERGENCY_STOP skips cycle"],
            "downstream": ["All pipeline stages"],
        },
        {
            "id": "MLKernelRegistry",
            "path": ML_REGISTRY,
            "why": "IStrategyRegistry routing ML vs legacy with fallback on KernelFallbackError",
            "called_by": ["SignalStage.run line 35"],
            "calls": ["KernelAdapter.generate_signal", "LegacyStrategyRegistry.generate_signal"],
            "inputs": ["MarketKey", "closed OHLCV DataFrame"],
            "outputs": ["TradingSignal or None"],
            "assumptions": ["USE_ML_KERNEL env", "adapter injected at factory time"],
            "failure_modes": ["KernelFallbackError → legacy fallback", "HOLD → None (no signal)"],
            "downstream": ["KernelAdapter", "RiskStage"],
        },
        {
            "id": "KernelAdapter",
            "path": KERNEL_ADAPTER,
            "why": "Production ML signal path — unified frame → decision stack → TradingSignal mapping",
            "called_by": ["MLKernelRegistry.generate_signal"],
            "calls": ["require_health", "PipelineCache", "build_market_context", "TradeQualityAdapter.evaluate", "apply_profitability_filters"],
            "inputs": ["MarketKey", "OHLCV DataFrame"],
            "outputs": ["TradingSignal or None", "UnifiedSignal internally"],
            "assumptions": ["≥250 bars for non-empty unified frame (dataset merge)", "500ms pipeline timeout"],
            "failure_modes": ["unified_frame_empty", "pipeline_timeout", "health fail → KernelFallbackError"],
            "downstream": ["SignalStage", "RiskStage"],
        },
        {
            "id": "PipelineCache",
            "path": PIPELINE_CACHE,
            "why": "Thread-safe singleton for EngineRegistry, unified features, prediction dedup",
            "called_by": ["factory.build_ml_kernel_stack", "KernelAdapter.produce_unified_signal"],
            "calls": ["EngineRegistry.build_default", "DatasetStore.load_v2", "build_unified_frame"],
            "inputs": ["candles tail(300)", "base_dir", "symbol", "timeframe"],
            "outputs": ["unified DataFrame", "cached UnifiedSignal payload"],
            "assumptions": ["dataset_v2 parquet exists on disk for phase99 merge"],
            "failure_modes": ["empty dataset → unified may lack phase99 columns", "cache key mismatch rebuilds"],
            "downstream": ["KernelAdapter", "HealthGate registry probe"],
        },
        {
            "id": "HealthGate",
            "path": HEALTH_GATE,
            "why": "Pre-decision artifact integrity + registry health; triggers legacy fallback",
            "called_by": ["KernelAdapter.produce_unified_signal lines 172-193"],
            "calls": ["run_pre_decision_health", "load_phase9_9_bundle(build_if_missing=False)"],
            "inputs": ["EngineRegistry", "optional unified_row"],
            "outputs": ["HealthGateResult or KernelFallbackError"],
            "assumptions": ["Frozen artifacts on disk match EXPECTED_DATASET_FINGERPRINT"],
            "failure_modes": ["checksum invalid", "missing feature_order", "registry health FAIL"],
            "downstream": ["KernelAdapter — blocks ML path"],
        },
        {
            "id": "DecisionOrchestrator",
            "path": ORCHESTRATOR,
            "why": "Select engine by regime, apply confidence policy, emit FinalDecision",
            "called_by": ["CalibratedDecisionAdapter (via risk/quality chain)"],
            "calls": ["select_engine", "select_signal", "ConfidenceEngine.from_context", "DecisionPolicy.apply"],
            "inputs": ["MarketContext"],
            "outputs": ["FinalDecision BUY/SELL/HOLD"],
            "assumptions": ["regime from rule_classify_row", "engine signals pre-computed"],
            "failure_modes": ["BLOCKED_REGIMES → HOLD", "confidence below min_confidence → HOLD"],
            "downstream": ["Calibration", "Risk", "Quality", "Filters"],
        },
        {
            "id": "Mt5ExecutionAdapter",
            "path": MT5_EXEC,
            "why": "Broker order execution with dry-run/paper/live modes",
            "called_by": ["ExecutionStage.run"],
            "calls": ["order_logic.validate_order", "order_logic.check_order_risk", "mt5.order_send"],
            "inputs": ["TradingSignal", "lot"],
            "outputs": ["ExecutionResult"],
            "assumptions": ["MT5 connected for live", "TRADINGBOT_DRY_RUN/PAPER env"],
            "failure_modes": ["validate_order fail", "MT5 retcode not DONE"],
            "downstream": ["TradeJournal", "record_live_entry"],
        },
    ]
    return {
        "phase": "24B",
        "module_count": len(modules),
        "modules": modules,
        "generated_utc": _utc_now(),
    }


def build_call_graph() -> dict[str, Any]:
    edges = [
        {"from": "main()", "to": "run_live_loop()", "file": LIVE_MODULE, "line": 79},
        {"from": "run_live_loop()", "to": "LiveRunner.__init__", "file": LIVE_RUNNER, "line": 147},
        {"from": "LiveRunner.__init__", "to": "build_strategy_registry()", "file": LIVE_RUNNER, "line": 76},
        {"from": "build_strategy_registry()", "to": "build_kernel_adapter()", "file": FACTORY, "line": 141},
        {"from": "build_kernel_adapter()", "to": "build_ml_kernel_stack()", "file": FACTORY, "line": 119},
        {"from": "build_ml_kernel_stack()", "to": "PipelineCache.get_registry()", "file": FACTORY, "line": 61},
        {"from": "LiveRunner._run()", "to": "TradingKernel.run_forever()", "file": LIVE_RUNNER, "line": 113},
        {"from": "run_forever()", "to": "run_global_cycle()", "file": KERNEL, "line": 222},
        {"from": "run_global_cycle()", "to": "run_market_cycle()", "file": KERNEL, "line": 158},
        {"from": "run_market_cycle()", "to": "PipelineStage.run() x5", "file": KERNEL, "line": 184},
        {"from": "SignalStage.run()", "to": "MLKernelRegistry.generate_signal()", "file": SIGNAL_STAGE, "line": 35},
        {"from": "MLKernelRegistry.generate_signal()", "to": "KernelAdapter.generate_signal()", "file": ML_REGISTRY, "line": 64},
        {"from": "KernelAdapter.generate_signal()", "to": "produce_unified_signal()", "file": KERNEL_ADAPTER, "line": 292},
        {"from": "produce_unified_signal()", "to": "require_health()", "file": KERNEL_ADAPTER, "line": 172},
        {"from": "produce_unified_signal()", "to": "PipelineCache.get_unified_frame()", "file": KERNEL_ADAPTER, "line": 178},
        {"from": "produce_unified_signal()", "to": "build_market_context()", "file": KERNEL_ADAPTER, "line": 208},
        {"from": "produce_unified_signal()", "to": "TradeQualityAdapter.evaluate()", "file": KERNEL_ADAPTER, "line": 219},
        {"from": "TradeQualityAdapter.evaluate()", "to": "AdaptiveRiskAdapter.evaluate()", "file": TRADE_QUALITY, "line": 64},
        {"from": "produce_unified_signal()", "to": "apply_profitability_filters()", "file": KERNEL_ADAPTER, "line": 239},
        {"from": "generate_signal()", "to": "map_unified_to_trading_signal()", "file": KERNEL_ADAPTER, "line": 295},
        {"from": "RiskStage.run()", "to": "IRiskGate.evaluate()", "file": RISK_STAGE, "line": 35},
        {"from": "ExecutionStage.run()", "to": "Mt5ExecutionAdapter.execute()", "file": EXEC_STAGE, "line": 21},
        {"from": "Mt5ExecutionAdapter.execute()", "to": "mt5.order_send()", "file": MT5_EXEC, "line": 240},
    ]
    return {"phase": "24B", "edges": edges, "node_count": len({e["from"] for e in edges} | {e["to"] for e in edges}), "generated_utc": _utc_now()}


def build_execution_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "graph_type": "execution_flow",
        "nodes": [
            {"id": "mt5_tick", "owner": "Mt5MarketDataAdapter", "file": MT5_DATA},
            {"id": "parquet_cache", "owner": "Mt5MarketDataAdapter", "note": "live hot path — not CandleStore"},
            {"id": "raw_ohlcv", "owner": "DataStage", "file": DATA_STAGE, "line": 24},
            {"id": "enriched_ohlcv", "owner": "IndicatorStage", "file": IND_STAGE, "line": 21},
            {"id": "trading_signal", "owner": "SignalStage", "file": SIGNAL_STAGE, "line": 40},
            {"id": "risk_decision", "owner": "RiskStage", "file": RISK_STAGE, "line": 36},
            {"id": "execution_result", "owner": "ExecutionStage", "file": EXEC_STAGE, "line": 21},
            {"id": "broker_order", "owner": "Mt5ExecutionAdapter", "file": MT5_EXEC, "line": 172},
        ],
        "edges": [
            {"from": "mt5_tick", "to": "parquet_cache", "fn": "update_all"},
            {"from": "parquet_cache", "to": "raw_ohlcv", "fn": "get_ohlcv"},
            {"from": "raw_ohlcv", "to": "enriched_ohlcv", "fn": "enrich_for_market"},
            {"from": "enriched_ohlcv", "to": "trading_signal", "fn": "generate_signal", "parallel_ml": "KernelAdapter uses same closed df"},
            {"from": "trading_signal", "to": "risk_decision", "fn": "risk.evaluate"},
            {"from": "risk_decision", "to": "execution_result", "fn": "executor.execute", "guard": "allowed=True"},
            {"from": "execution_result", "to": "broker_order", "fn": "order_send", "guard": "not dry_run/paper"},
        ],
        "position_management_parallel": {
            "file": KERNEL,
            "lines": "160-171",
            "actions": ["executor.manage_open_positions", "position_manager.manage_all"],
        },
        "generated_utc": _utc_now(),
    }


def build_feature_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "paths": [
            {
                "name": "live_unified_frame",
                "owner": "PipelineCache.get_unified_frame",
                "file": PIPELINE_CACHE,
                "line": 92,
                "steps": [
                    {"fn": "candles.tail(300)", "purpose": "sliding window"},
                    {"fn": "DatasetStore.load_v2", "purpose": "phase99 dataset merge"},
                    {"fn": "build_unified_frame", "file": UNIFIED_FEATURES, "line": 13},
                    {"fn": "_attach_trend_v41_features", "condition": "TREND_ENGINE_V41_ID active"},
                ],
                "consumers": ["KernelAdapter", "HealthGate feature row validation"],
            },
            {
                "name": "build_unified_frame_internals",
                "file": UNIFIED_FEATURES,
                "line": 13,
                "steps": [
                    "build_ml_features(candles) — trend indicators",
                    "compute_regime_features_from_candles — regime extras",
                    "merge dataset phase99_* via PHASE99_FEATURE_MAP",
                    "attach_regime_labels → regime column",
                ],
                "missing_value_behavior": "phase99 merge miss stays NaN (line 46 comment Phase 23B)",
            },
            {
                "name": "legacy_indicator_path",
                "file": IND_STAGE,
                "line": 20,
                "fn": "TechnicalIndicatorEngine.enrich_for_market",
                "consumers": ["SignalStage closed df", "RiskStage htf_bias uses separate HTF fetch"],
                "note": "Parallel to ML unified frame — legacy strategies use enriched_ohlcv only",
            },
            {
                "name": "phase99_range_inference_features",
                "file": RANGE_ADAPTER,
                "fn": "RangeEngineAdapter.evaluate",
                "mapping": "row_for_phase99_range in unified_features.py line 53",
            },
        ],
        "phase99_feature_map_source": "tradingbot/ml/research/phase13_9/config.py:PHASE99_FEATURE_MAP",
        "generated_utc": _utc_now(),
    }


def build_probability_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "models": [
            {
                "id": "phase9_9",
                "purpose": "RANGE regime ML direction probability",
                "inference_file": MODEL_REGISTRY,
                "inference_fn": "Phase99Bundle.predict_proba",
                "call_site": {"file": RANGE_ADAPTER, "line": _line_of(RANGE_ADAPTER, "predict_proba")},
                "input": "feature vector from row_for_phase99_range + StandardScaler",
                "output": "float proba[1] — positive class probability",
                "threshold_source": "config.json in phase9_9_best artifact (not hardcoded in adapter)",
                "used_by": ["UnifiedRangeWrapper.evaluate → MarketContext.range_signal"],
            },
            {
                "id": "trend_rf_v40/v41",
                "purpose": "TREND regime ML direction probability",
                "inference_file": "tradingbot/ml/phase15a/trend_bundle.py",
                "call_site": "TrendEngineWrapper / RecoveredTrendEngine.evaluate",
                "threshold": {"module": "decision_policy.py", "TREND_ML_THRESHOLD": 0.40, "line": 11},
                "version_env": "TREND_MODEL_VERSION → resolve_bundle_version()",
                "used_by": ["MarketContext.trend_signal"],
            },
        ],
        "flow": [
            "engine.evaluate → EngineSignal(probability, confidence, signal)",
            "DecisionOrchestrator.decide → metadata.probability preserved",
            "ConfidenceEngine.from_context adjusts final_confidence",
            "DecisionPolicy.apply gates action using final_confidence not raw probability",
        ],
        "generated_utc": _utc_now(),
    }


def build_confidence_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "stages": [
            {
                "stage": "model_confidence",
                "source": "EngineSignal.confidence from range/trend evaluate",
                "file": VALIDATION,
                "line": 53,
            },
            {
                "stage": "regime_adjusted_confidence",
                "source": "ConfidenceEngine.from_context",
                "file": "tradingbot/ml/decision_engine/confidence_engine.py",
                "inputs": ["MarketContext", "model_confidence"],
            },
            {
                "stage": "policy_gate",
                "source": "DecisionPolicy.apply",
                "file": "tradingbot/ml/decision_engine/decision_policy.py",
                "line": 23,
                "threshold": "min_confidence — overridden by Phase22C when enabled (factory.py line 67)",
            },
            {
                "stage": "calibration",
                "source": "build_production_calibrated_adapter",
                "file": FACTORY,
                "line": 77,
                "output": "calibrated.final_action, calibrated.final_confidence",
            },
            {
                "stage": "unified_signal_confidence",
                "source": "KernelAdapter UnifiedSignal.confidence",
                "file": KERNEL_ADAPTER,
                "line": 265,
                "value": "float(calibrated.final_confidence)",
            },
            {
                "stage": "trading_signal_confidence",
                "source": "map_unified_to_trading_signal",
                "propagates_to": "TradingSignal.confidence → RiskStage",
            },
        ],
        "generated_utc": _utc_now(),
    }


def build_decision_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "decisions": {
            "BUY": {
                "created_by": [
                    {"module": "RangeEngineAdapter/TrendEngine", "when": "probability/threshold → BUY"},
                    {"module": "DecisionOrchestrator", "when": "policy passes + engine selected"},
                ],
                "modified_by": [
                    {"module": "DecisionPolicy", "can_downgrade_to": "HOLD", "line": "decision_policy.py:26"},
                    {"module": "CalibratedDecisionAdapter", "file": "confidence_engine/validator.py"},
                    {"module": "AdaptiveRiskAdapter", "can_block": True},
                    {"module": "TradeQualityEngine", "can_block": True},
                    {"module": "apply_profitability_filters", "can_downgrade_to": "HOLD", "file": KERNEL_ADAPTER, "line": 247},
                    {"module": "KernelAdapter", "note": "returns None to SignalStage if still HOLD after mapping", "line": 312},
                    {"module": "RiskStage IRiskGate", "can_block": "before execution", "file": RISK_STAGE, "line": 37},
                ],
                "confirmed_by": [
                    {"module": "ExecutionStage", "when": "ctx.execution.success"},
                    {"module": "Mt5ExecutionAdapter", "when": "retcode DONE"},
                ],
            },
            "SELL": {"same_as": "BUY", "symmetric": True},
            "HOLD": {
                "created_by": [
                    {"module": "DecisionOrchestrator", "regimes": ["HIGH_VOLATILITY", "NO_TRADE"], "line": ORCHESTRATOR},
                    {"module": "DecisionPolicy", "reason": "confidence below min_confidence"},
                    {"module": "KernelAdapter", "lines": "243-248", "reasons": ["calibration action not BUY/SELL", "risk/quality blocked", "filter blocked"]},
                ],
                "propagation": "HOLD → generate_signal returns None → SignalStage returns False → pipeline stops before Risk/Execution",
            },
        },
        "generated_utc": _utc_now(),
    }


def build_hold_graph() -> dict[str, Any]:
    holds = [
        {
            "id": "decision_hold",
            "stage": "HoldStage.DECISION",
            "file": HOLD_CHAIN,
            "line": 14,
            "trigger_file": KERNEL_ADAPTER,
            "trigger_line": 138,
            "condition": "raw_action == HOLD from orchestrator (regime block or engine none)",
            "recovery": "Wait for regime/signal change on next bar",
        },
        {
            "id": "calibration_hold",
            "stage": "HoldStage.CALIBRATION",
            "file": HOLD_CHAIN,
            "line": 15,
            "trigger_file": KERNEL_ADAPTER,
            "trigger_line": 141,
            "condition": "calibrated.final_action not in BUY/SELL",
            "recovery": "Calibration adapter may pass on higher confidence bar",
        },
        {
            "id": "trade_quality_hold",
            "stage": "HoldStage.TRADE_QUALITY",
            "file": HOLD_CHAIN,
            "line": 16,
            "trigger_file": KERNEL_ADAPTER,
            "trigger_lines": "245-246",
            "condition": "not risk.allowed or not quality.allowed",
            "filters": ["AdaptiveRiskEngine", "TradeQualityEngine"],
            "recovery": "Next bar re-evaluates quality/risk scores",
        },
        {
            "id": "rsi_filter_hold",
            "stage": "HoldStage.RSI_FILTER",
            "file": HOLD_CHAIN,
            "line": 17,
            "trigger_file": KERNEL_ADAPTER,
            "trigger_line": 247,
            "condition": "filt blocked_by contains rsi_filter",
            "thresholds": "regime_filter_profiles RangeFilterProfile rsi 40-65 or Phase22C 35-65",
        },
        {
            "id": "adx_filter_hold",
            "stage": "HoldStage.ADX_FILTER",
            "file": HOLD_CHAIN,
            "line": 18,
            "condition": "filt blocked_by contains adx_filter",
        },
        {
            "id": "signal_stage_silent_hold",
            "file": SIGNAL_STAGE,
            "line": 38,
            "condition": "signal None or direction HOLD — stage returns False, no ctx.signal",
            "note": "Not recorded in HoldChain — pipeline stops",
        },
        {
            "id": "health_gate_fallback",
            "file": HEALTH_GATE,
            "line": 145,
            "condition": "require_health fails → KernelFallbackError → legacy path or no ML signal",
            "reasons": ["unified_frame_empty", "checksum invalid", "pipeline_timeout"],
        },
        {
            "id": "riskgate_hold",
            "stage": "HoldStage.RISK_GATE",
            "file": HOLD_CHAIN,
            "line": 20,
            "trigger_file": RISK_STAGE,
            "trigger_line": 37,
            "condition": "not decision.allowed",
            "recovery": "recorded via hold_chain if wired post-risk (production RiskStage does not call hold_chain directly)",
        },
        {
            "id": "blocked_regime_hold",
            "file": ORCHESTRATOR,
            "lines": "39-70",
            "regimes": ["HIGH_VOLATILITY", "NO_TRADE"],
            "detection": "rule_classify_row in regime_classifier.py",
        },
    ]
    return {"phase": "24B", "holds": holds, "hold_chain_enabled_default": True, "hold_chain_file": HOLD_CHAIN, "generated_utc": _utc_now()}


def build_filter_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "filters": [
            {
                "id": "rsi_profitability",
                "file": FILTERS,
                "line": 99,
                "why": "Phase 19C — mid-band RSI filter for trade quality",
                "production": True,
                "regime_ownership": "All regimes when enabled; RANGE uses RangeFilterProfile bands when 23G active",
            },
            {
                "id": "adx_profitability",
                "file": FILTERS,
                "line": 101,
                "why": "Phase 19C — ADX band filter",
                "production": True,
            },
            {
                "id": "regime_filter_profile_selector",
                "file": REGIME_FILTERS,
                "line": 187,
                "why": "Phase 23G — regime-conditional RSI/ADX bands",
                "rollback_env": "ENABLE_RANGE_FILTER_PROFILE default true",
                "range_only": "regime RANGE + engine phase9_9 → RangeFilterProfile 40-65 RSI, 15-40 ADX",
            },
            {
                "id": "decision_policy_confidence",
                "file": "tradingbot/ml/decision_engine/decision_policy.py",
                "line": 26,
                "why": "Minimum confidence gate before filters",
            },
            {
                "id": "trade_quality",
                "file": "tradingbot/ml/trade_quality/quality_engine.py",
                "why": "Phase 14.3 — composite quality score threshold",
                "threshold_env": "PHASE22C_QUALITY_THRESHOLD default 0.52",
            },
            {
                "id": "riskgate_legacy",
                "file": "tradingbot/adapters/risk_gate.py",
                "why": "Production RiskManager — separate from ML AdaptiveRiskEngine",
                "stage": "RiskStage after signal emitted",
            },
            {
                "id": "order_logic_guards",
                "file": MT5_EXEC,
                "lines": "138-146",
                "why": "Pre-broker validation",
            },
        ],
        "application_order_in_kernel_adapter": [
            "DecisionOrchestrator + calibration + risk + quality (single evaluate chain)",
            "select_profitability_filter_settings(regime, engine)",
            "apply_profitability_filters if action BUY/SELL and risk+quality allowed",
            "final action HOLD coercion lines 243-248",
        ],
        "generated_utc": _utc_now(),
    }


def build_risk_graph() -> dict[str, Any]:
    return {
        "phase": "24B",
        "layers": [
            {
                "layer": "ML AdaptiveRiskEngine",
                "file": "tradingbot/ml/risk_intelligence/adaptive_risk_engine.py",
                "stage": "inside TradeQualityAdapter.evaluate before quality",
                "output": "RiskRecommendation.allowed, risk_percent",
                "default_max_risk": "DEFAULT_MAX_RISK_PERCENT from phase14_7/config",
            },
            {
                "layer": "CalibratedDecisionAdapter",
                "chains": "orchestrator → calibration mapping",
            },
            {
                "layer": "Production RiskGate (legacy)",
                "file": "tradingbot/adapters/risk_gate.py",
                "factory": "create_risk_gate(legacy_config)",
                "stage": "RiskStage pipeline line 35",
                "can_adjust_lot": "decision.adjusted_lot → ctx.signal.lot_size line 40-41",
            },
            {
                "layer": "KillSwitchService",
                "file": LIVE_RUNNER,
                "line": 92,
                "effect": "kernel.emergency_stop → EMERGENCY_STOP state",
            },
            {
                "layer": "HealthGate",
                "effect": "ML fallback — no trade from ML path",
            },
            {
                "layer": "Mt5ExecutionAdapter guards",
                "functions": ["validate_order", "check_order_risk"],
            },
        ],
        "generated_utc": _utc_now(),
    }


def build_runtime_vs_research() -> dict[str, Any]:
    return {
        "phase": "24B",
        "divergences": [
            {
                "area": "market_data_source",
                "live": "Mt5MarketDataAdapter → ParquetCache",
                "research_batch": "CandleStore + DatasetStore offline builders",
                "intentional": True,
                "evidence": "phase22m — no CandleStore import in live_runner/trading_kernel",
            },
            {
                "area": "feature_builder_live_inference",
                "live": "FeatureBuilder.compute_at inside RangeEngineAdapter for phase99 live path",
                "research_unified": "build_unified_frame merges dataset_v2 parquet",
                "intentional": True,
                "risk": "unified_frame_empty if dataset stale or window < merge requirements",
            },
            {
                "area": "USE_ML_KERNEL",
                "live_default": False,
                "research_tests": "Often force true",
                "env": "USE_ML_KERNEL",
            },
            {
                "area": "execution",
                "live": "Mt5ExecutionAdapter dry_run default via LiveRunner",
                "research": "TRADINGBOT_DRY_RUN=1 in shadow validators",
            },
            {
                "area": "hold_chain",
                "live": "Enabled by default (_ENABLED=True hold_chain.py:110)",
                "research": "Same module — counters in ML path only",
            },
            {
                "area": "artifact_build",
                "live": "build_if_missing=False everywhere in hot path",
                "research_training": "May use build_if_missing=True in shadow/retrain scripts",
                "intentional": True,
            },
            {
                "area": "regime_label",
                "both": "rule_classify_row — not ML regime classifier in production path",
                "note": "TRANSITION is filter-profile bucket only, not rule_classify_row output",
            },
        ],
        "generated_utc": _utc_now(),
    }


def build_ownership_matrix() -> dict[str, Any]:
    rows = [
        {"component": "LiveRunner lifecycle", "owner": "application/live_runner.py", "coupling": "low"},
        {"component": "Pipeline orchestration", "owner": "kernel/trading_kernel.py", "coupling": "high"},
        {"component": "ML signal generation", "owner": "ml/integration/kernel_adapter.py", "coupling": "high"},
        {"component": "Engine registry + bundles", "owner": "ml/phase15a/engine_registry.py", "coupling": "high"},
        {"component": "Frozen phase9_9 artifacts", "owner": "data/ml/research/phase9_9_best/", "coupling": "high"},
        {"component": "Profitability filters", "owner": "ml/integration/regime_filter_profiles.py", "coupling": "medium"},
        {"component": "Broker execution", "owner": "adapters/mt5_execution.py", "coupling": "medium"},
        {"component": "Legacy RiskGate", "owner": "adapters/risk_gate.py", "coupling": "high"},
        {"component": "Research phases", "owner": "ml/research/*", "coupling": "isolated by rule"},
    ]
    return {"phase": "24B", "ownership": rows, "generated_utc": _utc_now()}


def build_dependency_matrix() -> dict[str, Any]:
    deps = {
        "LiveRunner": ["TradingKernel", "Mt5MarketDataAdapter", "Mt5ExecutionAdapter", "create_risk_gate", "build_strategy_registry"],
        "TradingKernel": ["DataStage", "IndicatorStage", "SignalStage", "RiskStage", "ExecutionStage"],
        "build_strategy_registry": ["LegacyStrategyRegistry", "MLKernelRegistry", "KernelAdapter", "is_ml_kernel_enabled"],
        "KernelAdapter": ["PipelineCache", "HealthGate", "DecisionOrchestrator chain", "regime_filter_profiles", "phase19c.filters"],
        "PipelineCache": ["EngineRegistry", "DatasetStore", "build_unified_frame", "load_phase9_9_bundle"],
        "EngineRegistry": ["RangeEngineAdapter", "Trend bundle loaders"],
        "SignalStage": ["IStrategyRegistry only — no direct ML imports"],
        "ExecutionStage": ["IOrderExecutor only"],
    }
    independent = [
        "BackgroundServices (parallel to kernel loop)",
        "KillSwitchService (parallel monitor)",
        "Notifier / TradeJournal (observability)",
        "Research phases under ml/research/ (no execution imports)",
    ]
    tightly_coupled = [
        ["KernelAdapter", "PipelineCache", "EngineRegistry"],
        ["KernelAdapter", "HealthGate", "frozen artifacts"],
        ["factory.build_ml_kernel_stack", "Phase22C config", "DecisionPolicy thresholds"],
        ["SignalStage", "MLKernelRegistry", "KernelAdapter"],
        ["RiskStage", "legacy RiskGate"],
    ]
    return {"phase": "24B", "dependencies": deps, "independent_modules": independent, "tightly_coupled_groups": tightly_coupled, "generated_utc": _utc_now()}


def build_configuration_inventory() -> dict[str, Any]:
    configs = [
        {"name": "USE_ML_KERNEL", "default": False, "file": "ml/integration/config.py", "line": 27, "consumers": ["factory.build_strategy_registry"]},
        {"name": "ENABLE_ML_SHADOW", "default": False, "file": "ml/integration/config.py", "line": 18},
        {"name": "ML_SHADOW_MODE", "default": False, "file": "ml/integration/config.py", "line": 22},
        {"name": "TREND_MODEL_VERSION", "default": "v41", "file": "ml/phase17d/config.py", "consumers": ["resolve_bundle_version", "EngineRegistry"]},
        {"name": "PHASE22C_ENABLED", "default": True, "file": "ml/research/phase22c/config.py", "line": 60},
        {"name": "PHASE22C_DECISION_MIN_CONFIDENCE", "default": 0.48, "file": "phase22c/config.py", "line": 61},
        {"name": "PHASE22C_QUALITY_THRESHOLD", "default": 0.52, "file": "phase22c/config.py", "line": 62},
        {"name": "ENABLE_RANGE_FILTER_PROFILE", "default": True, "file": "regime_filter_profiles.py", "line": 25},
        {"name": "ENABLE_RSI_FILTER", "default": True, "file": "ml/phase19c/config.py"},
        {"name": "ENABLE_ADX_FILTER", "default": True, "file": "ml/phase19c/config.py"},
        {"name": "RSI_MIN/MAX", "default": "40/60", "file": "ml/phase19c/filters.py", "line": 67},
        {"name": "ADX_MIN/MAX", "default": "15/50", "file": "ml/phase19c/filters.py", "line": 69},
        {"name": "TRADINGBOT_DRY_RUN", "default": "set by LiveRunner when dry_run=True", "file": LIVE_RUNNER, "line": 60},
        {"name": "TRADINGBOT_PAPER", "default": "set when paper=True", "file": LIVE_RUNNER, "line": 58},
        {"name": "MT5_LOGIN/PASSWORD/SERVER", "file": "adapters/legacy_loader.py", "line": 88},
        {"name": "BASE_DIR", "source": "legacy config", "consumers": ["artifact paths", "journals"]},
        {"name": "PRICE_ACTION.MIN_BARS", "default": 80, "file": KERNEL, "line": 77},
        {"name": "PRICE_ACTION.FETCH_BARS", "default": 300, "file": KERNEL, "line": 78},
        {"name": "HEALTH_MAX_TICK_AGE_SEC", "default": 120.0, "file": KERNEL, "line": 79},
        {"name": "PIPELINE_TIMEOUT_MS", "default": 500.0, "constant": True, "file": KERNEL_ADAPTER, "line": 41},
    ]
    return {"phase": "24B", "configurations": configs, "dotenv_loader": "tradingbot/config/dotenv_loader.py — loads .env if key not in os.environ", "generated_utc": _utc_now()}


def build_threshold_inventory() -> dict[str, Any]:
    thresholds = [
        {"name": "DEFAULT_MIN_CONFIDENCE", "value": 0.55, "file": "decision_policy.py", "line": 14, "overridden_by": "Phase22C decision_min_confidence 0.48"},
        {"name": "TREND_ML_THRESHOLD", "value": 0.40, "file": "decision_policy.py", "line": 11},
        {"name": "PHASE22C_RANGE_BUY_THRESHOLD", "value": 0.52, "env": True},
        {"name": "PHASE22C_RANGE_SELL_THRESHOLD", "value": 0.48, "env": True},
        {"name": "RangeFilterProfile.rsi", "value": "40-65", "file": REGIME_FILTERS, "line": 34},
        {"name": "RangeFilterProfile.adx", "value": "15-40", "file": REGIME_FILTERS, "line": 37},
        {"name": "TrendFilterProfile.rsi", "value": "35-65", "file": REGIME_FILTERS, "line": 66},
        {"name": "TrendFilterProfile.adx", "value": "10-55", "file": REGIME_FILTERS, "line": 68},
        {"name": "ADX_TREND_MIN", "value": 25.0, "file": REGIME_CLASSIFIER, "line": 14},
        {"name": "ADX_RANGE_MAX", "value": 20.0, "file": REGIME_CLASSIFIER, "line": 15},
        {"name": "ATR_HIGH_VOL", "value": 90.0, "file": REGIME_CLASSIFIER, "line": 16},
        {"name": "SPREAD_ABNORMAL", "value": 8.0, "file": REGIME_CLASSIFIER, "line": 20},
        {"name": "DataStage.min_bars", "value": 80, "file": DATA_STAGE, "line": 13},
        {"name": "ExecutionStage.default_lot", "value": 0.01, "file": EXEC_STAGE, "line": 12},
    ]
    return {"phase": "24B", "thresholds": thresholds, "generated_utc": _utc_now()}


def build_research_pipeline_trace() -> dict[str, Any]:
    return {
        "phase": "24B",
        "typical_research_path": [
            {"step": 1, "module": "CandleStore / collect_ml_data scripts", "purpose": "raw candle persistence"},
            {"step": 2, "module": "DatasetStore / build_ml_dataset", "purpose": "dataset_v2 with phase99 features"},
            {"step": 3, "module": "build_unified_frame", "file": UNIFIED_FEATURES, "purpose": "research feature matrix"},
            {"step": 4, "module": "run_decision_batch / shadow validators", "file": VALIDATION, "line": 180},
            {"step": 5, "module": "phase24a live_shadow_validator", "purpose": "replay with KernelAdapter, no orders"},
        ],
        "isolation_rules": [
            "Research under ml/research/ must not import execution modules",
            "Production integration via factory.py + kernel_adapter.py only",
        ],
        "not_in_live_hot_path": [
            "ShadowEngine",
            "KernelShadowRunner",
            "train_model.py",
            "robustness_optimizer",
        ],
        "generated_utc": _utc_now(),
    }


def build_architecture_overview(*, base_dir: str | None = None) -> dict[str, Any]:
    return {
        "phase": "24B",
        "title": "TradingBot Production Architecture Overview",
        "verdict": "ARCHITECTURE_DOCUMENTED_FROM_SOURCE",
        "live_entry": "python -m tradingbot --loop [--execute|--paper]",
        "architecture_layers": [
            "Market Data (MT5 → ParquetCache)",
            "Kernel Pipeline (Data → Indicators → Signal → Risk → Execution)",
            "ML Stack (optional USE_ML_KERNEL): HealthGate → PipelineCache → Engines → Orchestrator → Calibration → Risk → Quality → Filters",
            "Execution (Mt5ExecutionAdapter → order_send)",
        ],
        "dual_strategy_paths": {
            "ml": "MLKernelRegistry → KernelAdapter",
            "legacy": "LegacyStrategyRegistry → PriceAction strategies",
            "selection": "USE_ML_KERNEL env at factory.build_strategy_registry line 139",
        },
        "regime_detection_production": {
            "function": "rule_classify_row",
            "file": REGIME_CLASSIFIER,
            "labels": ["RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE"],
            "note": "TRANSITION is filter-profile label only, not classifier output",
        },
        "model_inventory_summary": ["phase9_9 RANGE", "trend_rf_v40/v41 TREND"],
        "safety_systems": ["HealthGate", "KernelFallbackError→legacy", "RiskGate", "KillSwitch", "order_logic guards", "pipeline timeout 500ms"],
        "generated_utc": _utc_now(),
        "live_pipeline_ref": "live_pipeline_trace.json",
    }


def build_architecture_findings() -> dict[str, Any]:
    return {
        "phase": "24B",
        "findings": [
            {
                "id": "F1",
                "severity": "operational",
                "title": "Unified frame requires dataset_v2 merge",
                "evidence": "PipelineCache.get_unified_frame calls DatasetStore.load_v2 + build_unified_frame",
                "impact": "Insufficient bars or missing dataset → unified_frame_empty → ML fallback",
            },
            {
                "id": "F2",
                "severity": "operational",
                "title": "500ms kernel adapter timeout",
                "evidence": "kernel_adapter.py PIPELINE_TIMEOUT_MS=500 line 41, check line 226",
                "impact": "Phase24A reported ~11% pipeline timeouts at p95 ~808ms",
            },
            {
                "id": "F3",
                "severity": "architecture",
                "title": "Dual feature paths",
                "evidence": "IndicatorStage enriches for legacy; ML uses PipelineCache unified frame separately",
                "impact": "Legacy and ML paths consume different feature sets",
            },
            {
                "id": "F4",
                "severity": "safety",
                "title": "Live artifact read-only",
                "evidence": "phase22ad artifact_overwrite_trace — build_if_missing=False on all hot-path loaders",
                "impact": "Runtime cannot rewrite frozen models",
            },
            {
                "id": "F5",
                "severity": "coupling",
                "title": "Tight ML stack coupling",
                "evidence": "factory.build_ml_kernel_stack wires registry+orchestrator+calibration+risk+quality atomically",
                "impact": "Changes to one layer require full stack understanding",
            },
            {
                "id": "F6",
                "severity": "regime",
                "title": "RANGE filter profile scope",
                "evidence": "regime_filter_profiles.py lines 228-231",
                "impact": "23G profile applies only RANGE+phase9_9; TREND/TRANSITION use Phase22C bands",
            },
        ],
        "areas_requiring_investigation_before_changes": [
            "TradingKernel pipeline stage order and SignalStage bar dedup",
            "PipelineCache feature cache invalidation (key includes last bar timestamp)",
            "Phase22C threshold interaction with DecisionPolicy",
            "Live dataset_v2 freshness vs MT5 ParquetCache sync",
            "RiskGate vs ML AdaptiveRiskEngine double-gating",
            "Latency budget: unified frame build + quality.evaluate chain",
        ],
        "generated_utc": _utc_now(),
    }


def build_final_report(*, base_dir: str | None = None) -> dict[str, Any]:
    return {
        "phase": "24B",
        "verdict": "ARCHITECTURE_FULLY_TRACED",
        "production_modified": False,
        "generated_utc": _utc_now(),
        "answers": {
            "1_how_system_works": (
                "LiveRunner connects MT5, starts background services, and runs TradingKernel.run_forever. "
                "Each cycle: update market data → for each symbol:timeframe run pipeline "
                "DataStage→IndicatorStage→SignalStage→RiskStage→ExecutionStage. "
                "When USE_ML_KERNEL=true, SignalStage calls MLKernelRegistry→KernelAdapter which builds "
                "unified features, runs health checks, evaluates range/trend engines, orchestrates decision, "
                "applies calibration/risk/quality/filters, maps to TradingSignal. Non-HOLD signals pass "
                "legacy RiskGate then Mt5ExecutionAdapter (dry-run/paper/live)."
            ),
            "2_major_module_responsibilities": "See module_inventory.json — 8 core production modules documented.",
            "3_independent_modules": [
                "BackgroundServices",
                "KillSwitchService",
                "Research phases (ml/research/*)",
                "Backtest engine (separate entry)",
            ],
            "4_tightly_coupled_modules": [
                "KernelAdapter + PipelineCache + EngineRegistry",
                "factory.build_ml_kernel_stack components",
                "MLKernelRegistry + KernelAdapter + HealthGate",
                "SignalStage + strategy registry + RiskStage",
            ],
            "5_architecture_assumptions": [
                "Frozen ML artifacts exist and match fingerprints",
                "dataset_v2 parquet available for phase99 feature merge",
                "MT5 connectivity and tick freshness (HEALTH_MAX_TICK_AGE_SEC)",
                "Chronological bar processing — SignalStage dedups same closed bar",
                "Legacy RiskGate remains authoritative for execution gating",
            ],
            "6_safe_future_modifications": [
                "Research phases under ml/research/ with isolation",
                "Regime filter profile tuning via regime_filter_profiles.py (23G pattern)",
                "Observability/logging additions in integration/monitoring",
                "Phase24 shadow validation expansions",
                "Env toggles with rollback switches (ENABLE_RANGE_FILTER_PROFILE pattern)",
            ],
            "7_dangerous_future_modifications": [
                "TradingKernel pipeline stage reordering",
                "RiskGate core logic changes",
                "Mt5ExecutionAdapter order_send flow",
                "Direct CandleStore wiring into LiveRunner loop without batch design",
                "Automatic model replacement / build_if_missing=True in hot path",
                "Feature pipeline changes without dataset fingerprint update",
                "Removing HealthGate or fallback paths",
            ],
            "8_investigate_before_changes": build_architecture_findings()["areas_requiring_investigation_before_changes"],
        },
    }


def build_all_artifacts(*, base_dir: str | None = None) -> dict[str, Any]:
    """Build all Phase 24B JSON deliverables."""
    live_trace = build_live_pipeline_trace(base_dir=base_dir)
    overview = build_architecture_overview(base_dir=base_dir)
    findings = build_architecture_findings()
    final = build_final_report(base_dir=base_dir)

    return {
        "architecture_overview.json": overview,
        "module_inventory.json": build_module_inventory(),
        "call_graph.json": build_call_graph(),
        "execution_graph.json": build_execution_graph(),
        "feature_graph.json": build_feature_graph(),
        "probability_graph.json": build_probability_graph(),
        "confidence_graph.json": build_confidence_graph(),
        "decision_graph.json": build_decision_graph(),
        "hold_graph.json": build_hold_graph(),
        "filter_graph.json": build_filter_graph(),
        "risk_graph.json": build_risk_graph(),
        "runtime_vs_research.json": build_runtime_vs_research(),
        "ownership_matrix.json": build_ownership_matrix(),
        "dependency_matrix.json": build_dependency_matrix(),
        "configuration_inventory.json": build_configuration_inventory(),
        "threshold_inventory.json": build_threshold_inventory(),
        "live_pipeline_trace.json": live_trace,
        "research_pipeline_trace.json": build_research_pipeline_trace(),
        "architecture_findings.json": findings,
        "phase24b_final_report.json": final,
    }
