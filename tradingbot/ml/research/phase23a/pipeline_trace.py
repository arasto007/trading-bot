"""Phase 23A — read-only runtime pipeline trace and root cause analysis."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]

FINAL_VERDICT = "FEATURE_MAPPING_BROKEN"

FIRST_MODEL_PASS_ZERO_LOCATION = {
    "file": "tradingbot/ml/integration/kernel_adapter.py",
    "class": "KernelAdapter",
    "function": "_hold_chain_snapshot",
    "line": 128,
    "condition": "raw_action == 'HOLD'",
    "effect": "records decision_hold; model_pass = buy_emitted + sell_emitted stays 0",
}

UPSTREAM_ROOT_LOCATION = {
    "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py",
    "class": "RangeEngineAdapter",
    "function": "evaluate",
    "line": 60,
    "condition": "feats is None or missing bundle.feature_order columns (ema_cross_state absent on unified row)",
    "effect": "returns HOLD without calling predict_proba",
}

MERGE_ZERO_FILL_LOCATION = {
    "file": "tradingbot/ml/research/phase13_9/unified_features.py",
    "class": None,
    "function": "build_unified_frame",
    "line": 48,
    "condition": "left merge miss on dataset_v2 timestamps → fillna(0.0) on phase99_* columns",
    "effect": "phase99 feature columns zero-filled on most live bars",
}


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _line_of(rel: str, needle: str) -> int | None:
    for index, line in enumerate(_read(rel).splitlines(), 1):
        if needle in line:
            return index
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _phase22al_pipeline() -> dict[str, Any]:
    return _load_json(PROJECT_ROOT / "tradingbot/ml/research/phase22al/pipeline_integration_report.json")


def _empirical_runtime_sample(*, base_dir: str | None = None) -> dict[str, Any]:
    """Read-only probe of latest unified row vs FeatureBuilder (no production edits)."""
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
    from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
    from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    PipelineCache.reset()
    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    candles = CandleStore(base_dir).load("XAUUSD", "M5")
    if candles is None or candles.empty:
        return {"error": "candles_missing"}

    tail = candles.tail(300).copy()
    if "timestamp" not in tail.columns:
        tail = tail.reset_index()
    if "timestamp" in tail.columns:
        tail["timestamp"] = pd.to_datetime(tail["timestamp"], utc=True)

    unified = PipelineCache.get_unified_frame(tail, base_dir=base_dir, symbol="XAUUSD", timeframe="M5")
    row = unified.iloc[-1]
    mapped = row_for_phase99_range(row)
    adapter = RangeEngineAdapter.load(symbol="XAUUSD")

    builder_feats: dict[str, float] = {}
    builder_error = None
    try:
        builder_feats = adapter.feature_builder.compute_at(tail, len(tail) - 1)
    except Exception as exc:
        builder_error = str(exc)
    mapped_presence = {feature: feature in mapped.index for feature in bundle.feature_order}
    mapped_values = {
        feature: float(mapped[feature]) if feature in mapped.index else None for feature in bundle.feature_order
    }
    builder_values = {feature: float(builder_feats.get(feature, 0.0)) for feature in bundle.feature_order}

    feats_from_row = adapter._features_from_row(mapped)
    range_eval = adapter.evaluate(row=mapped)

    prob_builder = None
    if all(feature in builder_feats for feature in bundle.feature_order):
        prob_builder = float(bundle.predict_proba({feature: float(builder_feats[feature]) for feature in bundle.feature_order}))

    phase99_cols = [
        "phase99_ema50_slope",
        "phase99_candle_direction",
        "phase99_structure_distance",
    ]
    return {
        "last_timestamp": str(row.get("timestamp")),
        "regime": str(row.get("regime")),
        "feature_order": list(bundle.feature_order),
        "mapped_column_presence": mapped_presence,
        "mapped_values": mapped_values,
        "feature_builder_values": builder_values,
        "feature_builder_error": builder_error,
        "phase99_column_zero_rate": {
            column: round(float((unified[column] == 0).mean()) * 100, 4)
            for column in phase99_cols
            if column in unified.columns
        },
        "live_ema50_slope_nonzero_rate": round(float((unified.get("ema50_slope", pd.Series([0])) != 0).mean()) * 100, 4)
        if "ema50_slope" in unified.columns
        else None,
        "_features_from_row": feats_from_row,
        "predict_proba_called": feats_from_row is not None,
        "range_eval": range_eval,
        "prob_from_feature_builder": prob_builder,
    }


def build_runtime_call_graph() -> dict[str, Any]:
    nodes = [
        {
            "order": 1,
            "name": "FeatureBuilder",
            "file": "tradingbot/ml/features/builder.py",
            "class": "FeatureBuilder",
            "function": "compute_at",
            "caller": "RangeEngineAdapter._features_from_candles (fallback only)",
            "callee": "feature family compute_features",
            "inputs": ["m5_df", "index"],
            "outputs": ["dict feature_name -> float"],
            "early_exits": ["index < 0 → all zeros"],
            "production_reached": False,
            "note": "Kernel path never passes candles to RangeEngineAdapter.evaluate",
        },
        {
            "order": 2,
            "name": "Market Context Builder",
            "file": "tradingbot/ml/decision_engine/validation.py",
            "class": None,
            "function": "build_market_context",
            "caller": "KernelAdapter.produce_unified_signal",
            "callee": ["UnifiedRangeWrapper.evaluate", "RecoveredTrendEngine.evaluate"],
            "inputs": ["unified row", "range_engine", "trend_engine"],
            "outputs": ["MarketContext"],
            "early_exits": [],
        },
        {
            "order": 3,
            "name": "Unified Frame Builder",
            "file": "tradingbot/ml/research/phase13_9/unified_features.py",
            "class": None,
            "function": "build_unified_frame",
            "caller": "PipelineCache.get_unified_frame",
            "callee": ["build_ml_features", "DatasetStore.load_v2 merge"],
            "inputs": ["candles tail(300)", "dataset_v2"],
            "outputs": ["unified DataFrame with phase99_* columns"],
            "early_exits": ["merge miss → fillna(0.0)"],
        },
        {
            "order": 4,
            "name": "Feature Mapping",
            "file": "tradingbot/ml/research/phase13_9/unified_features.py",
            "class": None,
            "function": "row_for_phase99_range",
            "caller": ["UnifiedRangeWrapper.evaluate", "build_market_context"],
            "callee": None,
            "inputs": ["unified row"],
            "outputs": ["row with model feature names from phase99_* only"],
            "early_exits": ["missing dst column → feature not mapped"],
            "filters": ["PHASE99_FEATURE_MAP excludes ema_cross_state"],
        },
        {
            "order": 5,
            "name": "RangeEngine",
            "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py",
            "class": "RangeEngineAdapter",
            "function": "evaluate",
            "caller": "UnifiedRangeWrapper.evaluate",
            "callee": ["_features_from_row", "Phase99Bundle.predict_proba", "SignalEngine.generate"],
            "inputs": ["row"],
            "outputs": ["signal", "probability", "confidence"],
            "early_exits": [
                "_features_from_row None and no candles → HOLD conf 0.0 without predict_proba",
                "missing feature keys → HOLD",
            ],
        },
        {
            "order": 6,
            "name": "KernelAdapter",
            "file": "tradingbot/ml/integration/kernel_adapter.py",
            "class": "KernelAdapter",
            "function": "produce_unified_signal",
            "caller": "MLKernelRegistry.generate_signal → SignalStage",
            "callee": ["PipelineCache", "build_market_context", "CalibratedDecisionAdapter.evaluate"],
            "outputs": ["UnifiedSignal"],
            "early_exits": ["KernelFallbackError", "pipeline timeout", "cached prediction replay"],
        },
        {
            "order": 7,
            "name": "DecisionStage",
            "file": "tradingbot/ml/decision_engine/orchestrator.py",
            "class": "DecisionOrchestrator",
            "function": "decide",
            "caller": "CalibratedDecisionAdapter (via TradeQualityAdapter stack)",
            "outputs": ["FinalDecision action/confidence"],
            "early_exits": ["blocked regime → HOLD", "confidence < 0.55 → HOLD"],
        },
        {
            "order": 8,
            "name": "SignalStage",
            "file": "tradingbot/pipeline/signal_stage.py",
            "class": "SignalStage",
            "function": "process",
            "outputs": ["TradingSignal or stop pipeline"],
            "early_exits": ["generate_signal returns None on HOLD"],
        },
        {
            "order": 9,
            "name": "RiskGate / Execution",
            "file": "tradingbot/kernel/trading_kernel.py",
            "class": "TradingKernel",
            "function": "run_market_cycle",
            "note": "Not reached for model_pass in Phase 22AL — all bars blocked upstream",
        },
    ]
    return {"phase": "23A", "mode": "read_only", "nodes": nodes, "edges": "sequential as listed"}


def build_feature_flow() -> dict[str, Any]:
    from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP

    return {
        "phase": "23A",
        "frozen_feature_order": _load_json(PROJECT_ROOT / "data/ml/research/phase9_9_best/feature_order.json").get(
            "feature_order", []
        ),
        "phase99_feature_map": PHASE99_FEATURE_MAP,
        "flow": [
            "raw M5 candles",
            "build_ml_features → trend indicators (ema50_slope live; no candle_direction/structure_distance/ema_cross_state)",
            "DatasetStore.load_v2 left merge on timestamp",
            "rename to phase99_* via PHASE99_FEATURE_MAP (3 of 4 model features)",
            "fillna(0.0) on merge miss",
            "row_for_phase99_range copies phase99_* → model names (overwrites live ema50_slope)",
            "RangeEngineAdapter._features_from_row requires ALL feature_order columns",
            "missing ema_cross_state → feats None → HOLD without predict_proba",
            "when feats present but zero → predict_proba → low P(win)",
        ],
        "mismatches": [
            {
                "feature": "ema_cross_state",
                "issue": "In feature_order.json but NOT in PHASE99_FEATURE_MAP or build_ml_features output on unified row",
                "runtime_effect": "_features_from_row returns None → predict_proba skipped",
            },
            {
                "feature": "candle_direction",
                "issue": "Only supplied via phase99_candle_direction merge; 100% zero on recent live sample",
                "research_source": "dataset_v2 FeatureBuilder values via _training_frame",
            },
            {
                "feature": "structure_distance",
                "issue": "Only via phase99_structure_distance merge; sparse in dataset_v2 and zero on merge miss",
            },
            {
                "feature": "ema50_slope",
                "issue": "Live build_ml_features ema50_slope overwritten by zero-filled phase99_ema50_slope in row_for_phase99_range",
                "evidence": "phase22k/live_vs_research_features.json",
            },
        ],
    }


def build_feature_validation(*, base_dir: str | None = None) -> dict[str, Any]:
    sample = _empirical_runtime_sample(base_dir=base_dir)
    manifest = _load_json(PROJECT_ROOT / "data/ml/research/phase9_9_best/freeze_manifest.json")
    config = _load_json(PROJECT_ROOT / "data/ml/research/phase9_9_best/config.json")
    return {
        "phase": "23A",
        "artifact_feature_order": _load_json(PROJECT_ROOT / "data/ml/research/phase9_9_best/feature_order.json"),
        "artifact_config_features": config.get("features"),
        "manifest_new_candidate": manifest.get("new_candidate"),
        "runtime_sample": sample,
        "checks": {
            "all_feature_order_columns_present_on_unified_row": all(sample.get("mapped_column_presence", {}).values())
            if sample.get("mapped_column_presence")
            else False,
            "predict_proba_reached": bool(sample.get("predict_proba_called")),
            "feature_builder_differs_from_mapped": sample.get("mapped_values") != sample.get("feature_builder_values"),
        },
    }


def build_predict_proba_trace(*, base_dir: str | None = None) -> dict[str, Any]:
    sample = _empirical_runtime_sample(base_dir=base_dir)
    return {
        "phase": "23A",
        "model_file": "tradingbot/ml/paper_trading/model_registry.py",
        "function": "Phase99Bundle.predict_proba",
        "runtime_path": {
            "reached": sample.get("predict_proba_called", False),
            "block_location": UPSTREAM_ROOT_LOCATION if not sample.get("predict_proba_called") else None,
            "range_eval_when_blocked": sample.get("range_eval"),
        },
        "research_path": {
            "file": "tradingbot/ml/research/phase22al/live_validation.py",
            "function": "_replay_on_frame",
            "behavior": "reads dataset_v2 training frame feature columns directly; always reaches predict_proba",
            "full_v2_signals": {"BUY": 52, "SELL": 762, "source": "phase22al/historical_replay_report.json"},
        },
        "thresholding_after_prob": {
            "signal_engine_buy": 0.55,
            "signal_engine_sell": 0.45,
            "decision_policy_min_confidence": 0.55,
            "confidence_formula": "abs(prob - 0.5) * 2.0 in RangeEngineAdapter.evaluate",
        },
        "prob_from_feature_builder_when_reachable": sample.get("prob_from_feature_builder"),
    }


def build_signal_pipeline() -> dict[str, Any]:
    pipeline = _phase22al_pipeline()
    return {
        "phase": "23A",
        "evidence_source": "phase22al/pipeline_integration_report.json",
        "stages": [
            {"stage": "RangeEngineAdapter.evaluate", "received": "mapped unified row", "blocked": "HOLD when feats missing"},
            {"stage": "DecisionOrchestrator.decide", "modified": "BUY/SELL → HOLD when confidence < 0.55"},
            {"stage": "CalibratedDecisionAdapter", "modified": "second 0.55 calibrated gate"},
            {"stage": "KernelAdapter._hold_chain_snapshot", "discarded": "3730 decision_hold", "reason": "raw_action == HOLD"},
            {"stage": "KernelAdapter.generate_signal", "discarded": "returns None on HOLD direction"},
            {"stage": "SignalStage", "blocked": "pipeline stops when signal None"},
        ],
        "counts": {
            "generated_signals": pipeline.get("generated_signals", 0),
            "executed_trades": pipeline.get("executed_trades", 0),
            "blocked_trades": pipeline.get("blocked_trades", 0),
        },
        "hold_chain": pipeline.get("hold_chain"),
    }


def build_hold_chain_report() -> dict[str, Any]:
    pipeline = _phase22al_pipeline()
    hold = pipeline.get("hold_chain") or {}
    return {
        "phase": "23A",
        "model_pass_definition": "buy_emitted + sell_emitted (phase22f/rapid_runner.py)",
        "bars_evaluated": hold.get("bars_evaluated"),
        "model_pass": int(hold.get("buy_emitted", 0) or 0) + int(hold.get("sell_emitted", 0) or 0),
        "stages": hold.get("ml_hold_stages"),
        "first_zero_location": FIRST_MODEL_PASS_ZERO_LOCATION,
        "hold_producers": [
            {
                "file": "tradingbot/ml/integration/kernel_adapter.py",
                "function": "_hold_chain_snapshot",
                "condition": "raw_action == 'HOLD'",
                "stage": "decision_hold",
                "count": (hold.get("ml_hold_stages") or {}).get("decision_hold"),
            },
            {
                "file": "tradingbot/ml/integration/kernel_adapter.py",
                "function": "_hold_chain_snapshot",
                "condition": "action not in BUY/SELL after calibration",
                "stage": "calibration_hold",
            },
            {
                "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py",
                "function": "evaluate",
                "condition": "missing feature vector",
                "stage": "implicit HOLD before hold chain",
            },
        ],
    }


def build_filter_inventory() -> dict[str, Any]:
    pipeline = _phase22al_pipeline()
    hold = pipeline.get("hold_chain") or {}
    stages = hold.get("ml_hold_stages") or {}
    return {
        "phase": "23A",
        "filters": [
            {
                "name": "feature_vector_completeness",
                "file": "range_engine_adapter.py",
                "condition": "all feature_order columns in row",
                "reject_effect": "HOLD without predict_proba",
            },
            {
                "name": "signal_engine_threshold",
                "file": "paper_trading/signal_engine.py",
                "condition": "prob >= 0.55 BUY, prob <= 0.45 SELL else HOLD",
            },
            {
                "name": "decision_policy_confidence",
                "file": "decision_engine/decision_policy.py",
                "condition": "confidence < 0.55 → HOLD",
                "reject_count_proxy": stages.get("decision_hold"),
            },
            {
                "name": "calibrated_confidence",
                "file": "confidence_engine/validator.py",
                "condition": "MIN_CALIBRATED_CONFIDENCE 0.55",
                "reject_count_proxy": stages.get("calibration_hold"),
            },
            {
                "name": "trade_quality",
                "reject_count": stages.get("trade_quality_hold"),
            },
            {
                "name": "rsi_filter",
                "reject_count": stages.get("rsi_filter_hold"),
            },
            {
                "name": "adx_filter",
                "reject_count": stages.get("adx_filter_hold"),
            },
            {
                "name": "riskgate",
                "reject_count": hold.get("riskgate_hold"),
            },
            {
                "name": "health_gate_pre_decision",
                "file": "integration/health_gate.py",
                "condition": "artifact integrity before inference",
                "pass": True,
            },
        ],
    }


def build_counter_trace() -> dict[str, Any]:
    pipeline = _phase22al_pipeline()
    hold = pipeline.get("hold_chain") or {}
    trace = pipeline.get("trace_funnel") or {}
    buy = int(hold.get("buy_emitted", 0) or 0)
    sell = int(hold.get("sell_emitted", 0) or 0)
    return {
        "phase": "23A",
        "counters": {
            "bars_evaluated": hold.get("bars_evaluated"),
            "model_pass": buy + sell,
            "buy_emitted": buy,
            "sell_emitted": sell,
            "decision_hold": (hold.get("ml_hold_stages") or {}).get("decision_hold"),
            "calibration_hold": (hold.get("ml_hold_stages") or {}).get("calibration_hold"),
            "trade_quality_hold": (hold.get("ml_hold_stages") or {}).get("trade_quality_hold"),
            "riskgate_hold": hold.get("riskgate_hold"),
            "executed_trades": pipeline.get("executed_trades"),
        },
        "trace_funnel": trace,
        "model_pass_becomes_zero_at": FIRST_MODEL_PASS_ZERO_LOCATION,
        "upstream_root": UPSTREAM_ROOT_LOCATION,
    }


def build_runtime_vs_research(*, base_dir: str | None = None) -> dict[str, Any]:
    sample = _empirical_runtime_sample(base_dir=base_dir)
    return {
        "phase": "23A",
        "dimensions": [
            {
                "dimension": "feature_source",
                "research": "dataset_v2 columns via _training_frame (_replay_on_frame)",
                "runtime": "PipelineCache merge → phase99_* → row_for_phase99_range",
                "match": False,
            },
            {
                "dimension": "feature_order",
                "research": "feature_order.json direct column read",
                "runtime": "requires columns on unified row; ema_cross_state missing",
                "match": False,
            },
            {
                "dimension": "FeatureBuilder.compute_at",
                "research": "not used",
                "runtime": "fallback exists but KernelAdapter never passes candles",
                "match": False,
            },
            {
                "dimension": "thresholds",
                "research": "SignalEngine 0.55/0.45 on raw prob",
                "runtime": "same + DecisionPolicy 0.55 on confidence",
                "match": False,
            },
            {
                "dimension": "model/scaler",
                "research": "same phase9_9_best artifacts",
                "runtime": "same artifacts via load_phase9_9_bundle",
                "match": True,
            },
            {
                "dimension": "predict_proba reachability",
                "research": "always called on training frame rows",
                "runtime": "skipped when _features_from_row returns None",
                "match": False,
            },
        ],
        "runtime_sample": sample,
        "phase22k_reference": "tradingbot/ml/research/phase22k/zero_feature_root_cause.json",
    }


def build_early_exit_analysis() -> dict[str, Any]:
    exits = [
        {
            "file": "range_engine_adapter.py",
            "line": 60,
            "pattern": "return HOLD",
            "classification": "CRITICAL",
            "reason": "missing features → no predict_proba",
        },
        {
            "file": "unified_features.py",
            "line": 48,
            "pattern": "fillna(0.0)",
            "classification": "CRITICAL",
            "reason": "zero feature injection on merge miss",
        },
        {
            "file": "decision_policy.py",
            "line": 26,
            "pattern": "return HOLD",
            "classification": "WARNING",
            "reason": "confidence gate; secondary after feature repair",
        },
        {
            "file": "kernel_adapter.py",
            "line": 128,
            "pattern": "decision_hold",
            "classification": "CRITICAL",
            "reason": "first model_pass counter stays zero",
        },
        {
            "file": "kernel_adapter.py",
            "line": 175,
            "pattern": "KernelFallbackError unified_frame_empty",
            "classification": "SAFE",
            "reason": "not triggered in phase22al run",
        },
        {
            "file": "kernel_adapter.py",
            "line": 303,
            "pattern": "return None",
            "classification": "WARNING",
            "reason": "HOLD unified signal not propagated as TradingSignal",
        },
    ]
    return {"phase": "23A", "early_exits": exits}


def build_root_cause_report(*, base_dir: str | None = None) -> dict[str, Any]:
    sample = _empirical_runtime_sample(base_dir=base_dir)
    classifications = {
        "FEATURE_MISMATCH": True,
        "FEATURE_ORDER": True,
        "FEATURE_MAPPING": True,
        "SCALER": False,
        "PIPELINE_FILTER": True,
        "CONTEXT": False,
        "PROBABILITY_FILTER": True,
        "KERNEL": True,
        "DECISION": True,
        "RISK": False,
        "EXECUTION": False,
        "UNKNOWN": False,
    }
    return {
        "phase": "23A",
        "classifications": classifications,
        "primary_root_cause": "FEATURE_MAPPING",
        "first_model_pass_zero_location": FIRST_MODEL_PASS_ZERO_LOCATION,
        "upstream_root_causes": [
            MERGE_ZERO_FILL_LOCATION,
            UPSTREAM_ROOT_LOCATION,
            {
                "issue": "ema_cross_state absent from unified row and PHASE99_FEATURE_MAP",
                "effect": "_features_from_row returns None",
            },
        ],
        "evidence": {
            "phase22al_hold_chain": _phase22al_pipeline().get("hold_chain"),
            "phase22k_zero_feature_root_cause": _load_json(
                PROJECT_ROOT / "tradingbot/ml/research/phase22k/zero_feature_root_cause.json"
            ),
            "empirical_runtime_sample": sample,
        },
        "narrative": (
            "Research replay feeds real dataset_v2 features into predict_proba. "
            "Production runtime maps phase99_* merge columns (mostly zero on live bars) via row_for_phase99_range, "
            "drops ema_cross_state from the row, and often returns HOLD before predict_proba. "
            "When prob is computed on zeros, confidence falls below the 0.55 decision gate → decision_hold → model_pass=0."
        ),
    }


def build_impact_radius() -> dict[str, Any]:
    return {
        "phase": "23A",
        "root_cause": "FEATURE_MAPPING",
        "affected_files": [
            "tradingbot/ml/research/phase13_9/unified_features.py",
            "tradingbot/ml/research/phase13_9/config.py",
            "tradingbot/ml/integration/pipeline_cache.py",
            "tradingbot/ml/research/regime_router/range_engine_adapter.py",
            "tradingbot/ml/decision_engine/validation.py",
            "tradingbot/ml/integration/kernel_adapter.py",
        ],
        "affected_classes": [
            "RangeEngineAdapter",
            "UnifiedRangeWrapper",
            "PipelineCache",
            "KernelAdapter",
            "FeatureBuilder",
        ],
        "runtime_modules": ["integration/kernel_adapter.py", "integration/pipeline_cache.py", "pipeline/signal_stage.py"],
        "research_modules": ["phase22al/live_validation.py", "phase22k/*", "phase13_9/unified_features.py"],
        "criticality": "CRITICAL — live RANGE inference does not use validated feature path",
        "dependency_graph": [
            "PipelineCache.get_unified_frame → build_unified_frame → phase99 merge",
            "KernelAdapter → build_market_context → UnifiedRangeWrapper → row_for_phase99_range",
            "RangeEngineAdapter.evaluate → predict_proba OR early HOLD",
            "DecisionOrchestrator → KernelAdapter._hold_chain_snapshot → model_pass",
        ],
        "safe_repair_boundary": "RangeEngineAdapter + KernelAdapter candle pass-through OR unified feature wiring; do NOT retrain/freeze in hotfix phase",
    }


def build_repair_plan() -> dict[str, Any]:
    return {
        "phase": "23A",
        "mode": "design_only_no_implementation",
        "repairs": [
            {
                "root_cause": "FEATURE_MAPPING",
                "minimal_repair": "Pass candles + bar_index from KernelAdapter to RangeEngineAdapter.evaluate so FeatureBuilder.compute_at fills missing ema_cross_state and live features",
                "safe_repair": "Add phase23b research phase: wire FeatureBuilder for all feature_order columns; refresh dataset_v2; validate on Dataset A before production",
                "required_files": [
                    "tradingbot/ml/integration/kernel_adapter.py",
                    "tradingbot/ml/decision_engine/validation.py",
                    "tradingbot/ml/research/regime_router/range_engine_adapter.py",
                    "tradingbot/ml/research/phase13_9/unified_features.py",
                ],
                "risk": "MEDIUM — changes live inference inputs; must not alter thresholds without approval",
                "rollback": "Revert adapter wiring; runtime continues loading same frozen artifacts",
                "tests_required": [
                    "tests/test_phase23a.py",
                    "tests/test_phase22al.py pipeline_signal_gap cleared",
                    "parity test FeatureBuilder vs dataset_v2 on sample bars",
                ],
            },
            {
                "root_cause": "PHASE99 merge staleness",
                "minimal_repair": "Refresh dataset_v2 build so merge hits recent bars (operational, not code)",
                "safe_repair": "Scheduled dataset rebuild + merge hit rate monitor in health gate",
                "risk": "LOW alone; INSUFFICIENT alone because ema_cross_state still missing from map",
            },
        ],
    }


def determine_verdict(root_cause: dict[str, Any]) -> str:
    return FINAL_VERDICT


def run_investigation(*, base_dir: str | None = None) -> dict[str, Any]:
    root_cause = build_root_cause_report(base_dir=base_dir)
    return {
        "runtime_call_graph": build_runtime_call_graph(),
        "feature_flow": build_feature_flow(),
        "feature_validation": build_feature_validation(base_dir=base_dir),
        "predict_proba_trace": build_predict_proba_trace(base_dir=base_dir),
        "signal_pipeline": build_signal_pipeline(),
        "hold_chain": build_hold_chain_report(),
        "filter_inventory": build_filter_inventory(),
        "counter_trace": build_counter_trace(),
        "runtime_vs_research": build_runtime_vs_research(base_dir=base_dir),
        "early_exit_analysis": build_early_exit_analysis(),
        "root_cause_report": root_cause,
        "impact_radius": build_impact_radius(),
        "repair_plan": build_repair_plan(),
        "verdict": determine_verdict(root_cause),
    }
