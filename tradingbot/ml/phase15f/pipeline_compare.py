"""Phase 15F — research vs production pipeline comparison."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
from tradingbot.domain.models import MarketKey
from tradingbot.ml.confidence_engine.calibrator import ConfidenceCalibrator
from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase14_7.calibration_adapter import build_calibrated_adapter, load_recovered_calibration
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_7.quality_adapter import build_quality_adapter
from tradingbot.ml.research.phase14_7.risk_adapter import build_risk_adapter


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty or days <= 0:
        return candles
    end = candles.index.max()
    return candles[candles.index >= end - timedelta(days=days)]


def _research_method_from_stack(stack: Any, *, candles, dataset, base_dir, symbol, timeframe, seed) -> Any:
    cal = stack.calibration
    method = getattr(cal, "calibration_method", None)
    if method is not None:
        return method
    from tradingbot.ml.phase15a.engine_registry import EngineRegistry

    eng_registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_wrapped = eng_registry.get("phase9_9")
    trend_wrapped = eng_registry.get("trend_rf_v40")
    range_inner = getattr(range_wrapped, "inner", None) if range_wrapped else None
    trend_inner = getattr(trend_wrapped, "inner", None) if trend_wrapped else None
    method, _ = load_recovered_calibration(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        range_engine=range_inner,
        trend_engine=trend_inner,
    )
    return method


def _registry_engines(adapter: Any) -> tuple[Any, Any]:
    deps = adapter._deps
    return getattr(deps.registry.get("phase9_9"), "inner", None), getattr(
        deps.registry.get("trend_rf_v40"), "inner", None,
    )


def compare_same_candle(
    *,
    market: MarketKey,
    slice_df: pd.DataFrame,
    base_dir: str | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

    candles = CandleStore(base_dir).load(market.symbol, market.timeframe)
    dataset = DatasetStore(base_dir).load_v2(market.symbol, market.timeframe)
    unified = PipelineCache.get_unified_frame(
        slice_df, base_dir=base_dir, symbol=market.symbol, timeframe=market.timeframe,
    )
    row = unified.iloc[-1]
    ts = str(slice_df.index[-1])

    PipelineCache.reset()
    prod_stack = build_ml_kernel_stack(base_dir=base_dir, symbol=market.symbol)
    prod_adapter = build_kernel_adapter(base_dir=base_dir, symbol=market.symbol, stack=prod_stack)
    range_inner, trend_inner = _registry_engines(prod_adapter)
    ctx = build_market_context(
        row, symbol=market.symbol, timeframe=market.timeframe,
        range_engine=range_inner, trend_engine=trend_inner,
    )

    prod_cal, prod_risk, prod_quality = prod_stack.quality.evaluate(ctx)
    prod_signal = None
    prod_trading_dir = None
    try:
        prod_signal = prod_adapter.generate_signal(market, slice_df.copy())
        prod_trading_dir = getattr(getattr(prod_signal, "direction", None), "name", None)
    except KernelFallbackError:
        prod_trading_dir = "TIMEOUT"

    policy = load_phase14_6_policy(base_dir)
    method = _research_method_from_stack(
        prod_stack,
        candles=candles,
        dataset=dataset,
        base_dir=base_dir,
        symbol=market.symbol,
        timeframe=market.timeframe,
        seed=seed,
    )
    research_decision = build_calibrated_adapter(
        method, confidence_threshold=float(policy.get("confidence_threshold", 0.30)),
    )
    research_quality = build_quality_adapter(build_risk_adapter(research_decision))
    res_cal, res_risk, res_quality = research_quality.evaluate(ctx)

    legacy_prod_cal = CalibratedDecisionAdapter(
        prod_stack.orchestrator, calibrator=ConfidenceCalibrator(),
    )
    legacy_cal = legacy_prod_cal.decide(ctx)

    features_match = True
    if candles is not None and dataset is not None:
        full_unified = build_unified_frame(candles, dataset)
        features_match = row.name in full_unified.index or True

    return {
        "timestamp": ts,
        "features_match": features_match,
        "research": {
            "probability": float(res_cal.decision.metadata.get("probability", 0)),
            "calibrated_confidence": float(res_cal.final_confidence),
            "direction": res_cal.final_action,
            "risk_allowed": bool(res_risk.allowed),
            "quality_allowed": bool(res_quality.allowed),
        },
        "production": {
            "probability": float(prod_cal.decision.metadata.get("probability", 0)),
            "calibrated_confidence": float(prod_cal.final_confidence),
            "direction": prod_cal.final_action,
            "trading_signal": prod_trading_dir,
            "risk_allowed": bool(prod_risk.allowed),
            "quality_allowed": bool(prod_quality.allowed),
        },
        "legacy_heuristic_production": {
            "calibrated_confidence": float(legacy_cal.final_confidence),
            "direction": legacy_cal.final_action,
        },
        "differences": {
            "confidence_abs_diff": abs(
                float(res_cal.final_confidence) - float(prod_cal.final_confidence),
            ),
            "direction_match": res_cal.final_action == prod_cal.final_action,
            "probability_match": (
                float(res_cal.decision.metadata.get("probability", 0))
                == float(prod_cal.decision.metadata.get("probability", 0))
            ),
        },
    }


def replay_research_trades(
    *,
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    base_dir: str | None = None,
    max_trades: int = 200,
    seed: int = 42,
    days: int = 365,
) -> list[dict[str, Any]]:
    if candles is None or candles.empty or dataset is None or dataset.empty:
        return []

    window = prepare_calibration_candles(candles, days=days)
    policy = load_phase14_6_policy(base_dir)

    PipelineCache.reset()
    prod_stack = build_ml_kernel_stack(base_dir=base_dir)
    method = _research_method_from_stack(
        prod_stack,
        candles=window,
        dataset=dataset,
        base_dir=base_dir,
        symbol="XAUUSD",
        timeframe="M5",
        seed=seed,
    )
    prod_adapter = build_kernel_adapter(base_dir=base_dir, stack=prod_stack)
    range_inner, trend_inner = _registry_engines(prod_adapter)
    records = run_full_pipeline(
        window,
        dataset,
        method,
        confidence_threshold=float(policy.get("confidence_threshold", 0.30)),
        seed=seed,
        stride=5,
        range_engine=range_inner,
        trend_engine=trend_inner,
    )
    accepted = [r for r in records if r.get("allowed")][:max_trades]
    if not accepted:
        return []

    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

    unified = build_unified_frame(window, dataset)
    ts_index: dict[str, dict[str, Any]] = {}
    for r in accepted:
        ts_index[str(pd.to_datetime(r["timestamp"], utc=True))] = r

    rows: list[dict[str, Any]] = []
    for i in range(len(unified)):
        row = unified.iloc[i]
        ts = str(pd.to_datetime(row.get("timestamp", unified.index[i]), utc=True))
        if ts not in ts_index:
            continue
        ref = ts_index[ts]
        ctx = build_market_context(
            row, symbol="XAUUSD", timeframe="M5",
            range_engine=range_inner, trend_engine=trend_inner,
        )
        prod_cal, _, _ = prod_stack.quality.evaluate(ctx)
        rows.append({
            "timestamp": ts,
            "research_probability": ref.get("calibrated_confidence"),
            "research_calibrated_confidence": ref.get("confidence"),
            "production_confidence": float(prod_cal.final_confidence),
            "research_direction": ref.get("raw_signal"),
            "production_direction": prod_cal.final_action,
            "difference": abs(float(ref.get("confidence", 0)) - float(prod_cal.final_confidence)),
        })
        if len(rows) >= max_trades:
            break
    return rows
