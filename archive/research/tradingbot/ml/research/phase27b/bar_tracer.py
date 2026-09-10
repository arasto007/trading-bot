"""Phase 27B — per-bar read-only pipeline trace (no prediction cache)."""

from __future__ import annotations

import os
import time
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_ml_kernel_stack
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.integration.regime_filter_profiles import select_profitability_filter_settings
from tradingbot.ml.phase19c.filters import (
    ProfitabilityFilterSettings,
    apply_profitability_filters,
)
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder


def _feature_float(row: pd.Series, key: str, default: float = 0.0) -> float:
    val = row.get(key, default)
    try:
        out = float(val)
        if out != out:
            return default
        return out
    except (TypeError, ValueError):
        return default


def _resolve_post_filter(
    *,
    pre_action: str,
    risk_allowed: bool,
    quality_allowed: bool,
    filt_passed: bool | None,
) -> str:
    action = pre_action
    if action not in ("BUY", "SELL"):
        return "HOLD"
    if not risk_allowed or not quality_allowed:
        return "HOLD"
    if filt_passed is False:
        return "HOLD"
    return action


def _hold_stage(
    *,
    raw_action: str,
    pre_action: str,
    risk_allowed: bool,
    quality_allowed: bool,
    blocked_by: list[str],
) -> str | None:
    if raw_action == "HOLD":
        return "decision_hold"
    if pre_action not in ("BUY", "SELL"):
        return "calibration_hold"
    if not quality_allowed or not risk_allowed:
        return "trade_quality_hold"
    if "rsi_filter" in blocked_by:
        return "rsi_filter_hold"
    if "adx_filter" in blocked_by:
        return "adx_filter_hold"
    return None


def trace_bar(
    *,
    bar_index: int,
    window: pd.DataFrame,
    stack: Any,
    range_engine: Any,
    trend_engine: Any,
    symbol: str,
    timeframe: str,
    base_dir: str,
) -> dict[str, Any]:
    ts = pd.to_datetime(window.index[bar_index], utc=True).isoformat()
    candles_slice = window.iloc[: bar_index + 1]
    unified = PipelineCache.get_unified_frame(
        candles_slice,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
    )
    if unified.empty:
        return {"bar_index": bar_index, "timestamp": ts, "error": "unified_frame_empty"}

    row = unified.iloc[-1]
    ctx = build_market_context(
        row,
        symbol=symbol,
        timeframe=timeframe,
        range_engine=range_engine,
        trend_engine=trend_engine,
        candles=candles_slice,
        bar_index=bar_index,
    )
    calibrated, risk, quality = stack.quality.evaluate(ctx)

    raw_action = str(calibrated.decision.action)
    pre_action = str(calibrated.final_action)
    regime = str(calibrated.decision.regime)
    engine = str(calibrated.decision.engine or "")

    filt = None
    filt_settings: ProfitabilityFilterSettings | None = None
    profile_used = ""
    if pre_action in ("BUY", "SELL") and risk.allowed and quality.allowed:
        filt_settings, diag = select_profitability_filter_settings(regime=regime, engine=engine or None)
        profile_used = diag.profile_used
        filt = apply_profitability_filters(row.to_dict(), settings=filt_settings)

    blocked_by = list(filt.blocked_by) if filt and not filt.passed else []
    post_action = _resolve_post_filter(
        pre_action=pre_action,
        risk_allowed=risk.allowed,
        quality_allowed=quality.allowed,
        filt_passed=filt.passed if filt is not None else None,
    )
    reason_parts: list[str] = []
    if blocked_by:
        reason_parts.append(",".join(blocked_by))
    if not risk.allowed:
        reason_parts.append(f"risk:{getattr(risk, 'reason', '')}")
    if not quality.allowed:
        reason_parts.append(f"quality:{getattr(quality, 'blocked_by', '')}")

    return {
        "timestamp": ts,
        "symbol": symbol,
        "bar_index": bar_index,
        "regime": regime,
        "engine": engine,
        "probability": round(float(ctx.range_signal.probability), 6)
        if regime == "RANGE"
        else round(float(ctx.trend_signal.probability), 6),
        "range_probability": round(float(ctx.range_signal.probability), 6),
        "trend_probability": round(float(ctx.trend_signal.probability), 6),
        "confidence": round(float(calibrated.final_confidence), 6),
        "rsi": round(float(filt.rsi), 6) if filt else round(_feature_float(row, "rsi", 50.0), 6),
        "adx": round(float(filt.adx), 6) if filt else round(_feature_float(row, "adx", 0.0), 6),
        "atr": round(_feature_float(row, "atr", 0.0), 6),
        "atr_percentile": round(
            _feature_float(row, "atr_percentile", _feature_float(row, "volatility", 0.0)),
            6,
        ),
        "ema20_slope": round(_feature_float(row, "ema20_slope", 0.0), 6),
        "momentum": round(
            _feature_float(row, "candle_momentum", _feature_float(row, "momentum", 0.0)),
            6,
        ),
        "decision_before_rsi": pre_action,
        "decision_after_rsi": post_action,
        "raw_orchestrator_action": raw_action,
        "risk_allowed": bool(risk.allowed),
        "quality_allowed": bool(quality.allowed),
        "quality_score": round(float(quality.score), 6) if hasattr(quality, "score") else None,
        "filter_profile": profile_used,
        "filter_settings": filt_settings.to_dict() if filt_settings else None,
        "filter_passed": filt.passed if filt is not None else None,
        "blocked_by": blocked_by,
        "hold_stage": _hold_stage(
            raw_action=raw_action,
            pre_action=pre_action,
            risk_allowed=risk.allowed,
            quality_allowed=quality.allowed,
            blocked_by=blocked_by,
        ),
        "reason": ";".join(reason_parts) if reason_parts else "",
    }


def run_bar_trace(
    *,
    days: int = 30,
    warmup_bars: int = 300,
    stride: int = 1,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
) -> dict[str, Any]:
    """Trace production decision stack per bar without PipelineCache prediction reuse."""
    os.environ.setdefault("USE_ML_KERNEL", "1")
    os.environ.setdefault("ALLOW_LEGACY_FALLBACK", "0")

    legacy = load_legacy_config()
    root = base_dir or legacy.get("BASE_DIR")
    PipelineCache.reset()

    candles_raw = CandleStore(root).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError(f"CandleStore unavailable for {symbol} {timeframe}")

    window = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=days))
    if len(window) < warmup_bars + 10:
        raise RuntimeError(f"Insufficient candles: {len(window)}")

    stack = build_ml_kernel_stack(base_dir=root, symbol=symbol)
    ka = KernelAdapter(stack.as_dependencies(base_dir=root, symbol=symbol))
    range_engine, trend_engine = ka._engine_inners()  # noqa: SLF001

    indices = list(range(warmup_bars, len(window), max(1, stride)))
    records: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    for n, bar_index in enumerate(indices, 1):
        records.append(
            trace_bar(
                bar_index=bar_index,
                window=window,
                stack=stack,
                range_engine=range_engine,
                trend_engine=trend_engine,
                symbol=symbol,
                timeframe=timeframe,
                base_dir=str(root),
            )
        )
        if n % 500 == 0:
            elapsed = time.perf_counter() - t0
            print(f"[phase27b] traced {n}/{len(indices)} bars ({elapsed:.1f}s)")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "warmup_bars": warmup_bars,
        "stride": stride,
        "bars_traced": len(records),
        "window_bars": len(window),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "records": records,
    }
