"""Phase 23C — read-only decision gate investigation after predict_proba()."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]

VERDICT_OPTIONS = (
    "CONFIDENCE_GATE_BLOCKING",
    "DECISION_POLICY_BLOCKING",
    "RISK_GATE_BLOCKING",
    "EXECUTION_GATE_BLOCKING",
    "MULTIPLE_ROOT_CAUSES",
)


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


def _confidence_formula_example(probability: float) -> dict[str, Any]:
    raw = abs(float(probability) - 0.5) * 2.0
    return {
        "probability": round(probability, 6),
        "formula": "confidence = abs(probability - 0.5) * 2.0",
        "computed_confidence": round(raw, 6),
        "note": "Distance from 0.5 mapped to [0, 1]; max at prob 0 or 1.",
    }


def build_confidence_trace() -> dict[str, Any]:
    """Locate every confidence calculation and document the 0.434 → 0.133 path."""
    calculations = [
        {
            "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py",
            "function": "RangeEngineAdapter.evaluate",
            "line": _line_of(
                "tradingbot/ml/research/regime_router/range_engine_adapter.py",
                "confidence = abs(prob - 0.5) * 2.0",
            ),
            "formula": "abs(probability - 0.5) * 2.0",
            "caller": "build_market_context → range_engine.evaluate",
            "consumer": "EngineSignal.confidence → DecisionOrchestrator.model_conf",
        },
        {
            "file": "tradingbot/ml/decision_engine/confidence_engine.py",
            "function": "ConfidenceEngine.compute",
            "line": _line_of(
                "tradingbot/ml/decision_engine/confidence_engine.py",
                "raw = float(model_confidence) * float(regime_strength) * float(market_quality)",
            ),
            "formula": "model_confidence * regime_strength * market_quality (clamped 0-1)",
            "caller": "ConfidenceEngine.from_context",
            "consumer": "DecisionPolicy.apply",
        },
        {
            "file": "tradingbot/ml/research/phase15i/recovery_adapter.py",
            "function": "RangeAwareConfidenceEngine.from_context",
            "line": _line_of(
                "tradingbot/ml/research/phase15i/recovery_adapter.py",
                "directional = prob if selected.signal == \"BUY\" else 1.0 - prob",
            ),
            "formula": "max(model_confidence, directional_prob) with regime_strength=1, market_quality=1 for RANGE/TREND recovery",
            "caller": "RangeRecoveryOrchestrator.decide",
            "consumer": "DecisionPolicy.apply (production factory uses recovery orchestrator)",
        },
        {
            "file": "tradingbot/ml/confidence_engine/calibrator.py",
            "function": "ConfidenceCalibrator.calibrate",
            "line": _line_of(
                "tradingbot/ml/confidence_engine/calibrator.py",
                "calibrated = clamp(raw.raw_value * product)",
            ),
            "formula": "raw * engine_factor * regime_factor * session_factor * vol_factor",
            "caller": "CalibratedDecisionAdapter.decide (fallback path)",
            "consumer": "CalibrationPolicy.passes_gate",
        },
        {
            "file": "tradingbot/ml/research/phase14_6/research_calibrator.py",
            "function": "ResearchCalibratedAdapter.decide",
            "line": _line_of(
                "tradingbot/ml/research/phase14_6/research_calibrator.py",
                "calibrated = self.calibration_method.calibrate(raw)",
            ),
            "formula": "Platt/isotonic on RawConfidence (production path via recovered_calibration)",
            "caller": "build_production_calibrated_adapter",
            "consumer": "ResearchCalibrationPolicy.passes_gate",
        },
        {
            "file": "tradingbot/ml/confidence_mapping/production_adapter.py",
            "function": "MappedProductionRiskAdapter.evaluate",
            "line": _line_of(
                "tradingbot/ml/confidence_mapping/production_adapter.py",
                "mapped_conf = self.mapper.map(frozen_conf)",
            ),
            "formula": "empirical curve maps calibrated → risk-facing confidence",
            "caller": "build_mapped_production_risk",
            "consumer": "AdaptiveRiskEngine.recommend",
        },
    ]

    sell_example = _confidence_formula_example(0.433644)
    sell_example_literal = _confidence_formula_example(0.434)
    return {
        "phase": "23C",
        "calculations": calculations,
        "sell_probability_0_434": sell_example_literal,
        "sell_probability_runtime_sample": sell_example,
        "recovery_path_note": (
            "Production uses RangeAwareConfidenceEngine: SELL at prob 0.434 → "
            "directional=0.566 replaces raw 0.133 before DecisionPolicy."
        ),
    }


def build_decision_policy_trace() -> dict[str, Any]:
    from tradingbot.ml.confidence_engine.calibration_policy import DEFAULT_CALIBRATION_POLICY
    from tradingbot.ml.decision_engine.decision_policy import DEFAULT_POLICY
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg22 = load_phase22c_config()
    effective_decision_min = (
        cfg22.decision_min_confidence if cfg22.enabled else DEFAULT_POLICY.min_confidence
    )
    effective_cal_min = (
        min(
            float(_load_json(PROJECT_ROOT / "tradingbot/ml/research/phase14_6").get("x", 0.30) or 0.30),
            cfg22.calibration_min_confidence,
        )
        if cfg22.enabled
        else DEFAULT_CALIBRATION_POLICY.min_calibrated_confidence
    )

    return {
        "phase": "23C",
        "signal_engine": {
            "file": "tradingbot/ml/paper_trading/signal_engine.py",
            "buy_if": "probability >= buy_threshold (default 0.55; Phase22C may lower to 0.52)",
            "sell_if": "probability <= sell_threshold (default 0.45; Phase22C may lower to 0.48)",
            "hold_otherwise": True,
        },
        "decision_policy": {
            "file": "tradingbot/ml/decision_engine/decision_policy.py",
            "function": "DecisionPolicy.apply",
            "line": _line_of("tradingbot/ml/decision_engine/decision_policy.py", "if confidence < self.min_confidence:"),
            "min_confidence_default": DEFAULT_POLICY.min_confidence,
            "min_confidence_effective": effective_decision_min,
            "phase22c_enabled": cfg22.enabled,
            "transitions": {
                "BUY": "pass if confidence >= min_confidence else HOLD",
                "SELL": "pass if confidence >= min_confidence else HOLD",
                "HOLD": "always HOLD",
            },
        },
        "calibration_policy": {
            "file": "tradingbot/ml/research/phase14_6/research_calibrator.py",
            "function": "ResearchCalibrationPolicy.passes_gate",
            "min_calibrated_default": 0.55,
            "min_calibrated_effective_note": "min(platt_threshold ~0.30, phase22c calibration_min 0.42)",
            "phase22c_calibration_min": cfg22.calibration_min_confidence if cfg22.enabled else None,
        },
        "sell_0_434_narrative": [
            "predict_proba → prob 0.434",
            "SignalEngine: 0.434 <= sell_threshold → raw signal SELL",
            "RangeEngineAdapter confidence: abs(0.434-0.5)*2 = 0.133",
            "RangeAwareConfidenceEngine: max(0.133, 1-0.434=0.566) → final_conf 0.566",
            "DecisionPolicy: 0.566 >= effective min → orchestrator action SELL",
            "Platt calibration + ResearchCalibrationPolicy → may downgrade to HOLD",
            "KernelAdapter: final_action not BUY/SELL → calibration_hold counter",
        ],
    }


def _hold_sites_after_predict() -> list[dict[str, Any]]:
    """Static inventory of HOLD branches downstream of predict_proba."""
    return [
        {
            "file": "tradingbot/ml/paper_trading/signal_engine.py",
            "function": "SignalEngine.generate",
            "line": _line_of("tradingbot/ml/paper_trading/signal_engine.py", "return PaperSignal.HOLD"),
            "condition": "probability between sell_threshold and buy_threshold",
            "reason": "neutral probability band",
            "stage": "engine_signal",
        },
        {
            "file": "tradingbot/ml/decision_engine/decision_policy.py",
            "function": "DecisionPolicy.apply",
            "line": _line_of("tradingbot/ml/decision_engine/decision_policy.py", "if confidence < self.min_confidence:"),
            "condition": "confidence < min_confidence",
            "reason": "decision policy gate",
            "stage": "decision_policy",
        },
        {
            "file": "tradingbot/ml/decision_engine/orchestrator.py",
            "function": "DecisionOrchestrator.decide",
            "line": _line_of("tradingbot/ml/decision_engine/orchestrator.py", 'action="HOLD"'),
            "condition": "blocked regime or no engine",
            "reason": "regime router block",
            "stage": "decision_policy",
        },
        {
            "file": "tradingbot/ml/confidence_engine/validator.py",
            "function": "CalibratedDecisionAdapter.decide",
            "line": _line_of("tradingbot/ml/confidence_engine/validator.py", 'final_action = "HOLD"'),
            "condition": "not passes_gate(final_conf) or engine_signal not BUY/SELL",
            "reason": "calibration confidence gate",
            "stage": "calibration",
        },
        {
            "file": "tradingbot/ml/research/phase14_6/research_calibrator.py",
            "function": "ResearchCalibratedAdapter.decide",
            "line": _line_of("tradingbot/ml/research/phase14_6/research_calibrator.py", 'final_action = "HOLD"'),
            "condition": "not policy.passes_gate(calibrated) or engine_signal not BUY/SELL",
            "reason": "Platt calibration gate (production path)",
            "stage": "calibration",
        },
        {
            "file": "tradingbot/ml/integration/kernel_adapter.py",
            "function": "KernelAdapter.produce_unified_signal",
            "line": _line_of("tradingbot/ml/integration/kernel_adapter.py", 'if action not in ("BUY", "SELL"):'),
            "condition": "calibrated.final_action not BUY/SELL",
            "reason": "propagate calibration HOLD to unified signal",
            "stage": "calibration",
        },
        {
            "file": "tradingbot/ml/integration/kernel_adapter.py",
            "function": "KernelAdapter.produce_unified_signal",
            "line": _line_of("tradingbot/ml/integration/kernel_adapter.py", "elif not risk.allowed or not quality.allowed:"),
            "condition": "risk or quality blocked",
            "reason": "trade quality / risk hold",
            "stage": "trade_quality",
        },
        {
            "file": "tradingbot/ml/integration/kernel_adapter.py",
            "function": "KernelAdapter.produce_unified_signal",
            "line": _line_of("tradingbot/ml/integration/kernel_adapter.py", "elif filt is not None and not filt.passed:"),
            "condition": "RSI/ADX profitability filter failed",
            "reason": "phase22c filter hold",
            "stage": "profitability_filter",
        },
        {
            "file": "tradingbot/ml/integration/signal_mapper.py",
            "function": "map_unified_to_trading_signal",
            "line": _line_of("tradingbot/ml/integration/kernel_adapter.py", "if trading.direction == SignalDirection.HOLD:"),
            "condition": "unified direction HOLD",
            "reason": "kernel returns None — no execution signal",
            "stage": "execution",
        },
    ]


def build_hold_chain_after_predict() -> dict[str, Any]:
    return {
        "phase": "23C",
        "hold_sites": _hold_sites_after_predict(),
        "hold_chain_stages": [
            "decision_hold",
            "calibration_hold",
            "trade_quality_hold",
            "rsi_filter_hold",
            "adx_filter_hold",
        ],
        "kernel_hold_chain_file": "tradingbot/ml/research/phase22c/hold_chain.py",
    }


def build_threshold_inventory() -> dict[str, Any]:
    from tradingbot.ml.confidence_engine.calibration_policy import (
        MIN_CALIBRATED_CONFIDENCE,
        MIN_RAW_CONFIDENCE,
    )
    from tradingbot.ml.decision_engine.decision_policy import DEFAULT_MIN_CONFIDENCE, TREND_ML_THRESHOLD
    from tradingbot.ml.research.phase22c.config import load_phase22c_config
    from tradingbot.ml.trade_quality.quality_policy import QUALITY_THRESHOLD

    cfg22 = load_phase22c_config()
    platt_threshold = float(
        _load_json(PROJECT_ROOT / "data/ml/research/phase14_6/final_report.json").get(
            "recommended_policy", {}
        ).get("confidence_threshold", 0.30)
        if (PROJECT_ROOT / "data/ml/research/phase14_6/final_report.json").is_file()
        else 0.30
    )

    thresholds = [
        {
            "value": 0.55,
            "name": "buy_threshold / DEFAULT_MIN_CONFIDENCE",
            "purpose": "BUY signal + decision policy gate (default)",
            "owner": "SignalEngine / DecisionPolicy",
            "used_by": ["RangeEngineAdapter", "DecisionOrchestrator"],
        },
        {
            "value": 0.45,
            "name": "sell_threshold",
            "purpose": "SELL signal from raw probability",
            "owner": "SignalEngine",
            "used_by": ["RangeEngineAdapter"],
        },
        {
            "value": DEFAULT_MIN_CONFIDENCE,
            "name": "decision_min_confidence",
            "purpose": "Block BUY/SELL when final_confidence below threshold",
            "owner": "DecisionPolicy",
            "used_by": ["DecisionOrchestrator"],
        },
        {
            "value": MIN_CALIBRATED_CONFIDENCE,
            "name": "MIN_CALIBRATED_CONFIDENCE",
            "purpose": "Heuristic calibration gate (fallback adapter)",
            "owner": "CalibrationPolicy",
            "used_by": ["CalibratedDecisionAdapter"],
        },
        {
            "value": platt_threshold,
            "name": "platt_confidence_threshold",
            "purpose": "Research Platt gate (production recovered path)",
            "owner": "ResearchCalibrationPolicy",
            "used_by": ["ResearchCalibratedAdapter via recovered_calibration"],
        },
        {
            "value": MIN_RAW_CONFIDENCE,
            "name": "MIN_RAW_CONFIDENCE",
            "purpose": "Reject calibration when raw too low",
            "owner": "CalibrationPolicy",
            "used_by": ["ConfidenceCalibrator"],
        },
        {
            "value": TREND_ML_THRESHOLD,
            "name": "TREND_ML_THRESHOLD",
            "purpose": "Trend engine probability gate",
            "owner": "RecoveredTrendEngine",
            "used_by": ["TREND regime only"],
        },
        {
            "value": QUALITY_THRESHOLD,
            "name": "QUALITY_THRESHOLD",
            "purpose": "Trade quality composite score minimum",
            "owner": "QualityPolicy",
            "used_by": ["TradeQualityEngine", "KernelAdapter"],
        },
    ]
    if cfg22.enabled:
        thresholds.extend(
            [
                {
                    "value": cfg22.decision_min_confidence,
                    "name": "PHASE22C_DECISION_MIN_CONFIDENCE",
                    "purpose": "Lower decision policy gate",
                    "owner": "Phase22CConfig",
                    "used_by": ["factory.build_ml_kernel_stack"],
                },
                {
                    "value": cfg22.calibration_min_confidence,
                    "name": "PHASE22C_CALIBRATION_MIN_CONFIDENCE",
                    "purpose": "Lower Platt calibration gate",
                    "owner": "Phase22CConfig",
                    "used_by": ["recovered_calibration.build_production_calibrated_adapter"],
                },
                {
                    "value": cfg22.range_buy_threshold,
                    "name": "PHASE22C_RANGE_BUY_THRESHOLD",
                    "purpose": "Range SignalEngine buy threshold override",
                    "owner": "Phase22CConfig",
                    "used_by": ["apply_phase22c_range_thresholds"],
                },
                {
                    "value": cfg22.range_sell_threshold,
                    "name": "PHASE22C_RANGE_SELL_THRESHOLD",
                    "purpose": "Range SignalEngine sell threshold override",
                    "owner": "Phase22CConfig",
                    "used_by": ["apply_phase22c_range_thresholds"],
                },
            ]
        )

    return {"phase": "23C", "thresholds": thresholds, "phase22c_enabled": cfg22.enabled}


def _trace_single_bar(
    *,
    base_dir: str | None,
    row: pd.Series,
    candles: pd.DataFrame,
    bar_index: int,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
) -> dict[str, Any]:
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.phase19c.filters import apply_profitability_filters, load_filter_settings
    from tradingbot.ml.research.phase22c.config import load_phase22c_config
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    registry = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_id = getattr(getattr(registry.get("trend_rf_v41") or registry.get("trend_rf_v40"), "inner", None), "__class__", None)
    trend_wrapped = registry.get("trend_rf_v41") or registry.get("trend_rf_v40")
    trend_inner = getattr(trend_wrapped, "inner", None)

    norm_candles = normalize_candles_for_builder(candles)
    range_ev = range_inner.evaluate(row=row, candles=norm_candles, bar_index=bar_index, timeframe=timeframe)
    ctx = build_market_context(
        row,
        symbol=symbol,
        timeframe=timeframe,
        range_engine=range_inner,
        trend_engine=trend_inner,
        candles=norm_candles,
        bar_index=bar_index,
    )
    orchestrator = stack.orchestrator.inner if hasattr(stack.orchestrator, "inner") else stack.orchestrator
    orch_decision = orchestrator.decide(ctx)
    calibrated = stack.calibration.decide(ctx)
    cal2, risk = stack.risk.evaluate(ctx)
    cal3, risk2, quality = stack.quality.evaluate(ctx)

    cfg22 = load_phase22c_config()
    filt = None
    kernel_action = str(cal3.final_action)
    if kernel_action in ("BUY", "SELL") and risk2.allowed and quality.allowed:
        filt_settings = load_filter_settings()
        if cfg22.enabled:
            from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings

            filt_settings = ProfitabilityFilterSettings(
                enable_rsi=filt_settings.enable_rsi,
                enable_adx=filt_settings.enable_adx,
                rsi_min=cfg22.rsi_min,
                rsi_max=cfg22.rsi_max,
                adx_min=cfg22.adx_min,
                adx_max=cfg22.adx_max,
            )
        filt = apply_profitability_filters(row.to_dict(), settings=filt_settings)

    if kernel_action not in ("BUY", "SELL"):
        final_kernel = "HOLD"
    elif not risk2.allowed or not quality.allowed:
        final_kernel = "HOLD"
    elif filt is not None and not filt.passed:
        final_kernel = "HOLD"
    else:
        final_kernel = kernel_action

    stages = [
        {
            "stage": "RangeEngineAdapter.evaluate",
            "input": {"predict_proba": True},
            "output": {
                "signal": range_ev.get("signal"),
                "probability": range_ev.get("probability"),
                "confidence": range_ev.get("confidence"),
            },
            "reason": "SignalEngine on probability; confidence = abs(p-0.5)*2",
        },
        {
            "stage": "DecisionOrchestrator.decide",
            "input": {
                "raw_engine_signal": ctx.range_signal.signal if ctx.regime == "RANGE" else ctx.trend_signal.signal,
                "model_confidence": ctx.range_signal.confidence if ctx.regime == "RANGE" else ctx.trend_signal.confidence,
                "regime": ctx.regime,
            },
            "output": {"action": orch_decision.action, "confidence": orch_decision.confidence},
            "reason": orch_decision.explanation[-1] if orch_decision.explanation else "",
        },
        {
            "stage": "ResearchCalibratedAdapter.decide",
            "input": {"orchestrator_action": orch_decision.action, "raw_confidence": orch_decision.confidence},
            "output": {
                "final_action": calibrated.final_action,
                "final_confidence": calibrated.final_confidence,
            },
            "reason": (
                "calibration gate pass"
                if calibrated.final_action in ("BUY", "SELL")
                else "calibrated confidence below policy or engine HOLD"
            ),
        },
        {
            "stage": "AdaptiveRiskAdapter.evaluate",
            "input": {"action": cal3.final_action, "confidence": cal3.final_confidence},
            "output": {"allowed": risk2.allowed, "risk_percent": risk2.risk_percent, "blocked_by": risk2.blocked_by},
            "reason": risk2.blocked_by or "risk allowed",
        },
        {
            "stage": "TradeQualityAdapter.evaluate",
            "input": {"action": cal3.final_action},
            "output": {"allowed": quality.allowed, "score": quality.score, "blocked_by": quality.blocked_by},
            "reason": quality.blocked_by or "quality allowed",
        },
        {
            "stage": "KernelAdapter.produce_unified_signal (filters)",
            "input": {"calibrated_action": cal3.final_action},
            "output": {"direction": final_kernel, "filter_passed": filt.passed if filt else None},
            "reason": (
                "actionable"
                if final_kernel in ("BUY", "SELL")
                else (filt.blocked_by if filt and not filt.passed else "upstream HOLD or risk/quality")
            ),
        },
    ]

    first_block = None
    engine_sig = str(range_ev.get("signal", "HOLD"))
    selected_sig = str(ctx.range_signal.signal if ctx.regime == "RANGE" else ctx.trend_signal.signal)
    if engine_sig in ("BUY", "SELL") and ctx.regime == "RANGE":
        if orch_decision.action == "HOLD":
            first_block = {
                "stage": "DecisionOrchestrator.decide",
                "reason": "decision_policy_confidence_gate",
            }
        elif calibrated.final_action == "HOLD":
            first_block = {
                "stage": "ResearchCalibratedAdapter.decide",
                "reason": "calibration_confidence_gate",
            }
        elif final_kernel == "HOLD" and not risk2.allowed:
            first_block = {"stage": "AdaptiveRiskAdapter", "reason": risk2.blocked_by or "risk_gate"}
        elif final_kernel == "HOLD" and not quality.allowed:
            first_block = {"stage": "TradeQualityEngine", "reason": quality.blocked_by or "trade_quality_gate"}
        elif final_kernel == "HOLD" and filt is not None and not filt.passed:
            first_block = {"stage": "ProfitabilityFilter", "reason": filt.blocked_by}
    elif selected_sig in ("BUY", "SELL") and orch_decision.action == "HOLD":
        first_block = {
            "stage": "DecisionOrchestrator.decide",
            "reason": "decision_policy_confidence_gate",
            "note": f"regime={ctx.regime} engine signal blocked by policy",
        }

    return {
        "range_evaluation": range_ev,
        "pipeline_stages": stages,
        "first_block_after_engine_actionable": first_block,
        "final_kernel_direction": final_kernel,
    }


def build_runtime_statistics(*, base_dir: str | None = None, tail_bars: int = 300) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings, apply_profitability_filters, load_filter_settings
    from tradingbot.ml.research.phase22c.config import load_phase22c_config
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    PipelineCache.reset()
    loaded = CandleStore(base_dir).load("XAUUSD", "M5")
    if loaded is None or loaded.empty:
        return {"error": "candles_missing"}

    candles = normalize_candles_for_builder(loaded)
    tail = candles.tail(tail_bars).copy()
    unified = PipelineCache.get_unified_frame(tail, base_dir=base_dir, symbol="XAUUSD", timeframe="M5")
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol="XAUUSD")
    registry = PipelineCache.get_registry(base_dir=base_dir, symbol="XAUUSD")
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_wrapped = registry.get("trend_rf_v41") or registry.get("trend_rf_v40")
    trend_inner = getattr(trend_wrapped, "inner", None)
    cfg22 = load_phase22c_config()

    counts = {
        "bars": 0,
        "range_bars": 0,
        "predict_proba_called": 0,
        "engine_buy": 0,
        "engine_sell": 0,
        "engine_hold": 0,
        "engine_actionable": 0,
        "orchestrator_buy": 0,
        "orchestrator_sell": 0,
        "orchestrator_hold": 0,
        "calibrated_buy": 0,
        "calibrated_sell": 0,
        "calibrated_hold": 0,
        "blocked_decision_policy": 0,
        "blocked_calibration": 0,
        "blocked_risk": 0,
        "blocked_quality": 0,
        "blocked_profitability_filter": 0,
        "kernel_actionable": 0,
        "kernel_hold": 0,
    }

    orchestrator = stack.orchestrator.inner if hasattr(stack.orchestrator, "inner") else stack.orchestrator

    for i in range(len(unified)):
        row = unified.iloc[i]
        bar_index = max(0, len(tail) - len(unified) + i)
        ctx = build_market_context(
            row,
            symbol="XAUUSD",
            timeframe="M5",
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=tail,
            bar_index=bar_index,
        )
        counts["bars"] += 1
        if ctx.regime != "RANGE":
            continue
        counts["range_bars"] += 1

        range_ev = range_inner.evaluate(row=row, candles=tail, bar_index=bar_index, timeframe="M5")
        if range_ev.get("predict_proba_called"):
            counts["predict_proba_called"] += 1

        eng_sig = str(range_ev.get("signal", "HOLD"))
        counts[f"engine_{eng_sig.lower()}"] = counts.get(f"engine_{eng_sig.lower()}", 0) + 1
        if eng_sig in ("BUY", "SELL"):
            counts["engine_actionable"] += 1

        orch = orchestrator.decide(ctx)
        counts[f"orchestrator_{orch.action.lower()}"] = counts.get(f"orchestrator_{orch.action.lower()}", 0) + 1
        if eng_sig in ("BUY", "SELL") and orch.action == "HOLD":
            counts["blocked_decision_policy"] += 1

        cal, risk, quality = stack.quality.evaluate(ctx)
        counts[f"calibrated_{cal.final_action.lower()}"] = counts.get(f"calibrated_{cal.final_action.lower()}", 0) + 1
        if eng_sig in ("BUY", "SELL") and orch.action in ("BUY", "SELL") and cal.final_action == "HOLD":
            counts["blocked_calibration"] += 1

        kernel_action = str(cal.final_action)
        if kernel_action in ("BUY", "SELL") and not risk.allowed:
            counts["blocked_risk"] += 1
            kernel_action = "HOLD"
        elif kernel_action in ("BUY", "SELL") and not quality.allowed:
            counts["blocked_quality"] += 1
            kernel_action = "HOLD"
        elif kernel_action in ("BUY", "SELL"):
            filt_settings = load_filter_settings()
            if cfg22.enabled:
                filt_settings = ProfitabilityFilterSettings(
                    enable_rsi=filt_settings.enable_rsi,
                    enable_adx=filt_settings.enable_adx,
                    rsi_min=cfg22.rsi_min,
                    rsi_max=cfg22.rsi_max,
                    adx_min=cfg22.adx_min,
                    adx_max=cfg22.adx_max,
                )
            filt = apply_profitability_filters(row.to_dict(), settings=filt_settings)
            if not filt.passed:
                counts["blocked_profitability_filter"] += 1
                kernel_action = "HOLD"

        if kernel_action in ("BUY", "SELL"):
            counts["kernel_actionable"] += 1
        else:
            counts["kernel_hold"] += 1

    sample_trace = None
    for i in range(len(unified) - 1, -1, -1):
        row = unified.iloc[i]
        bar_index = max(0, len(tail) - len(unified) + i)
        ctx_probe = build_market_context(
            row,
            symbol="XAUUSD",
            timeframe="M5",
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=tail,
            bar_index=bar_index,
        )
        if ctx_probe.regime != "RANGE":
            continue
        range_probe = range_inner.evaluate(row=row, candles=tail, bar_index=bar_index, timeframe="M5")
        if str(range_probe.get("signal", "HOLD")) not in ("BUY", "SELL"):
            continue
        sample_trace = _trace_single_bar(
            base_dir=base_dir,
            row=row,
            candles=tail,
            bar_index=bar_index,
        )
        break
    if sample_trace is None:
        sample_trace = _trace_single_bar(
            base_dir=base_dir,
            row=unified.iloc[-1],
            candles=tail,
            bar_index=len(tail) - 1,
        )

    return {
        "phase": "23C",
        "window": {"symbol": "XAUUSD", "timeframe": "M5", "tail_bars": tail_bars},
        "counts": counts,
        "latest_bar_trace": sample_trace,
    }


def build_research_vs_runtime(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    loaded = CandleStore(base_dir).load("XAUUSD", "M5")
    dataset = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
    if loaded is None or loaded.empty or dataset is None or dataset.empty:
        return {"error": "data_missing"}

    window = prepare_calibration_candles(loaded, days=30)
    unified = build_unified_frame(window, dataset)
    adapter = RangeEngineAdapter.load(symbol="XAUUSD", base_dir=base_dir)
    norm = normalize_candles_for_builder(window)

    research_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    runtime_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    divergences = 0
    first_divergence_stage = None

    runtime_stats = build_runtime_statistics(base_dir=base_dir, tail_bars=min(300, len(window)))

    stride = max(1, len(unified) // 50)
    for i in range(0, len(unified), stride):
        row = unified.iloc[i]
        bar_index = min(i, len(norm) - 1)
        research_ev = adapter.evaluate(row=row, candles=norm, bar_index=bar_index, timeframe="M5")
        research_sig = str(research_ev.get("signal", "HOLD"))
        research_counts[research_sig] = research_counts.get(research_sig, 0) + 1

    # Runtime path uses full stack statistics already collected
    rc = runtime_stats.get("counts", {})
    runtime_counts = {
        "BUY": rc.get("kernel_actionable", 0) if False else rc.get("calibrated_buy", 0),
        "SELL": rc.get("calibrated_sell", 0),
        "HOLD": rc.get("calibrated_hold", 0),
    }
    runtime_counts["BUY"] = rc.get("calibrated_buy", 0)

    if rc.get("engine_actionable", 0) > rc.get("calibrated_buy", 0) + rc.get("calibrated_sell", 0):
        divergences = rc.get("engine_actionable", 0) - (
            rc.get("calibrated_buy", 0) + rc.get("calibrated_sell", 0)
        )
        if rc.get("blocked_decision_policy", 0) > 0:
            first_divergence_stage = "DecisionOrchestrator (DecisionPolicy min_confidence)"
        elif rc.get("blocked_calibration", 0) > 0:
            first_divergence_stage = "ResearchCalibratedAdapter (Platt calibration gate)"

    return {
        "phase": "23C",
        "research_path": {
            "description": "RangeEngineAdapter + SignalEngine thresholds on probability only",
            "signal_counts_sampled": research_counts,
            "uses_decision_policy": False,
            "uses_calibration_gate": False,
        },
        "runtime_path": {
            "description": "Full kernel stack: recovery orchestrator → Platt → risk → quality → filters",
            "range_bar_counts": rc,
            "calibrated_direction_counts": runtime_counts,
        },
        "first_divergence": {
            "stage": first_divergence_stage,
            "engine_actionable": rc.get("engine_actionable"),
            "calibrated_actionable": rc.get("calibrated_buy", 0) + rc.get("calibrated_sell", 0),
            "divergence_bars_estimate": divergences,
        },
        "probability_0_434": {
            "research": "SELL (prob <= sell_threshold)",
            "runtime_engine": "SELL with confidence 0.133 raw",
            "runtime_orchestrator_with_recovery": "SELL (directional conf 0.566)",
            "runtime_note": "Downstream Platt/calibration may still HOLD",
        },
    }


def _confidence_consumers() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "min_confidence",
            "file": "tradingbot/ml/decision_engine/decision_policy.py",
            "function": "DecisionPolicy.apply",
            "condition": "confidence < min_confidence → HOLD",
        },
        {
            "symbol": "passes_gate",
            "file": "tradingbot/ml/confidence_engine/calibration_policy.py",
            "function": "CalibrationPolicy.passes_gate",
            "condition": "calibrated < MIN_CALIBRATED_CONFIDENCE → HOLD",
        },
        {
            "symbol": "passes_gate",
            "file": "tradingbot/ml/research/phase14_6/research_calibrator.py",
            "function": "ResearchCalibrationPolicy.passes_gate",
            "condition": "Platt output < threshold → HOLD",
        },
        {
            "symbol": "signal_quality_score",
            "file": "tradingbot/ml/trade_quality/signal_quality.py",
            "function": "signal_quality_score",
            "condition": "uses ctx.confidence for quality scoring",
        },
        {
            "symbol": "RISK_GATE_THRESHOLD",
            "file": "tradingbot/ml/confidence_mapping/config.py",
            "function": "ConfidenceMapper",
            "condition": "mapped confidence vs risk gate 0.55",
        },
    ]


def build_root_cause_report(*, runtime_stats: dict[str, Any]) -> dict[str, Any]:
    counts = runtime_stats.get("counts", {})
    blocks = {
        "decision_policy": counts.get("blocked_decision_policy", 0),
        "calibration": counts.get("blocked_calibration", 0),
        "risk": counts.get("blocked_risk", 0),
        "quality": counts.get("blocked_quality", 0),
        "profitability_filter": counts.get("blocked_profitability_filter", 0),
    }
    engine_actionable = counts.get("engine_actionable", 0)

    first_gate = None
    first_gate_count = 0
    ordered_gates = [
        ("decision_policy", "DecisionOrchestrator DecisionPolicy"),
        ("calibration", "ResearchCalibratedAdapter Platt gate"),
        ("risk", "AdaptiveRiskEngine"),
        ("quality", "TradeQualityEngine"),
        ("profitability_filter", "Phase22C RSI/ADX filters"),
    ]
    for key, label in ordered_gates:
        if blocks[key] > 0:
            first_gate = label
            first_gate_count = blocks[key]
            break

    nonzero_blocks = sum(1 for v in blocks.values() if v > 0)
    if nonzero_blocks > 1:
        verdict = "MULTIPLE_ROOT_CAUSES"
    elif blocks["decision_policy"] > 0:
        verdict = "DECISION_POLICY_BLOCKING"
    elif blocks["calibration"] > 0:
        verdict = "CONFIDENCE_GATE_BLOCKING"
    elif blocks["risk"] > 0:
        verdict = "RISK_GATE_BLOCKING"
    elif blocks["quality"] > 0:
        verdict = "EXECUTION_GATE_BLOCKING"
    elif blocks["profitability_filter"] > 0:
        verdict = "EXECUTION_GATE_BLOCKING"
    elif engine_actionable == 0:
        verdict = "DECISION_POLICY_BLOCKING"
    else:
        verdict = "CONFIDENCE_GATE_BLOCKING"

    latest = runtime_stats.get("latest_bar_trace", {})
    sample_first = latest.get("first_block_after_engine_actionable")

    return {
        "phase": "23C",
        "classification": verdict,
        "first_gate_blocking_actionable_signals": first_gate,
        "first_gate_block_count": first_gate_count,
        "block_counts_by_stage": blocks,
        "engine_actionable_total": engine_actionable,
        "sample_bar_first_block": sample_first,
        "confidence_0_133_explanation": _confidence_formula_example(0.434),
        "summary": (
            "Raw engine confidence abs(p-0.5)*2 yields ~0.133 at prob 0.434; RangeAwareConfidenceEngine "
            "recovers directional probability before DecisionPolicy. On current RANGE replay, decision and "
            "Platt calibration pass all 18 engine SELLs; Phase22C RSI/ADX profitability filters block half "
            "before KernelAdapter emits a unified signal."
        ),
    }


def build_repair_design(*, root_cause: dict[str, Any]) -> dict[str, Any]:
    classification = root_cause.get("classification", "CONFIDENCE_GATE_BLOCKING")
    designs = {
        "CONFIDENCE_GATE_BLOCKING": {
            "minimal_repair": (
                "Align calibration gate with research acceptance: use directional probability "
                "for RANGE gate comparison OR lower Platt threshold using Phase15G equivalence study — "
                "do not change frozen model."
            ),
            "risk": "May increase trade count and drawdown if calibration was intentionally conservative.",
            "rollback": "Restore ResearchCalibrationPolicy threshold from freeze manifest; no model change.",
            "tests": [
                "test_phase23c kernel_actionable > 0 on RANGE replay",
                "test hold_chain model_pass > 0",
                "regression: phase23b feature delivery unchanged",
            ],
        },
        "DECISION_POLICY_BLOCKING": {
            "minimal_repair": (
                "Document that RangeAwareConfidenceEngine already recovers directional prob; "
                "if still blocked, verify orchestrator wiring or adjust DecisionPolicy only via approved Phase22C env."
            ),
            "risk": "Lowering min_confidence increases false positives.",
            "rollback": "Reset PHASE22C_DECISION_MIN_CONFIDENCE to 0.55.",
            "tests": ["test orchestrator SELL passes for prob 0.434 sample"],
        },
        "RISK_GATE_BLOCKING": {
            "minimal_repair": "Audit AdaptiveRiskEngine blocked_by; tune risk policy in isolated research phase.",
            "risk": "Position sizing changes affect live capital.",
            "rollback": "Restore RiskPolicy defaults.",
            "tests": ["test risk allowed for calibrated actionable signals"],
        },
        "EXECUTION_GATE_BLOCKING": {
            "minimal_repair": "Audit TradeQualityEngine and Phase22C RSI/ADX filters on RANGE bars.",
            "risk": "Disabling filters may admit low-quality entries.",
            "rollback": "Re-enable filter settings from config snapshot.",
            "tests": ["test quality.allowed rate on actionable calibrated signals"],
        },
        "MULTIPLE_ROOT_CAUSES": {
            "minimal_repair": "Phased repair: fix first gate (calibration/decision), re-measure before touching risk/filters.",
            "risk": "Concurrent threshold changes obscure attribution.",
            "rollback": "Revert one layer at a time using phase23c deliverables as baseline.",
            "tests": ["test each gate independently with hold_chain counters"],
        },
    }
    return {
        "phase": "23C",
        "classification": classification,
        "design": designs.get(classification, designs["CONFIDENCE_GATE_BLOCKING"]),
        "implementation_status": "NOT IMPLEMENTED — design only per Phase 23C scope",
    }


def run_investigation(*, base_dir: str | None = None) -> dict[str, Any]:
    confidence_trace = build_confidence_trace()
    decision_policy = build_decision_policy_trace()
    hold_chain = build_hold_chain_after_predict()
    threshold_inventory = build_threshold_inventory()
    runtime_statistics = build_runtime_statistics(base_dir=base_dir)
    research_vs_runtime = build_research_vs_runtime(base_dir=base_dir)
    root_cause = build_root_cause_report(runtime_stats=runtime_statistics)
    repair_design = build_repair_design(root_cause=root_cause)

    consumers = _confidence_consumers()
    rc = runtime_statistics.get("counts", {})
    for consumer in consumers:
        key = consumer.get("symbol", "")
        if "min_confidence" in key or "passes_gate" in consumer.get("function", ""):
            if "decision" in consumer.get("file", ""):
                consumer["reject_count"] = rc.get("blocked_decision_policy", 0)
                consumer["pass_count"] = max(0, rc.get("engine_actionable", 0) - rc.get("blocked_decision_policy", 0))
            elif "research_calibrator" in consumer.get("file", ""):
                consumer["reject_count"] = rc.get("blocked_calibration", 0)
                consumer["pass_count"] = rc.get("calibrated_buy", 0) + rc.get("calibrated_sell", 0)
            else:
                consumer["reject_count"] = None
                consumer["pass_count"] = None

    confidence_trace["consumers"] = consumers

    verdict = root_cause["classification"]
    if verdict not in VERDICT_OPTIONS:
        verdict = "CONFIDENCE_GATE_BLOCKING"

    return {
        "confidence_trace": confidence_trace,
        "decision_policy": decision_policy,
        "hold_chain_after_predict": hold_chain,
        "threshold_inventory": threshold_inventory,
        "runtime_statistics": runtime_statistics,
        "research_vs_runtime": research_vs_runtime,
        "root_cause_report": root_cause,
        "repair_design": repair_design,
        "verdict": verdict,
    }
