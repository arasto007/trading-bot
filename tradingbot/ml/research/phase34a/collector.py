"""Phase 34A — collect raw ML signals before downstream filters (research only)."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from tradingbot.ml.confidence_engine.volatility_adjuster import classify_volatility
from tradingbot.ml.research.phase22f.config import RapidDataset
from tradingbot.ml.research.phase33d.forensic_context import row_checksum


async def _load_candles(
    dataset: RapidDataset,
    timeframe: str = "M5",
    *,
    use_fullest: bool = False,
) -> pd.DataFrame | None:
    """Load candles from backtest cache; fallback to CandleStore without MT5."""
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset

    if not use_fullest:
        frame = await load_ohlcv_for_dataset(dataset, timeframe)
        if frame is not None and len(frame) >= 500:
            return frame

    base_dir = load_legacy_config().get("BASE_DIR")
    if use_fullest:
        from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles

        raw = resolve_fullest_candles("XAUUSD", timeframe)
    else:
        raw = CandleStore(base_dir).load("XAUUSD", timeframe)
    if raw is None or raw.empty:
        return None
    if not isinstance(raw.index, pd.DatetimeIndex):
        if "timestamp" in raw.columns:
            raw = raw.set_index("timestamp")
    raw.index = pd.to_datetime(raw.index, utc=True)
    start = pd.Timestamp(dataset.start.astimezone(raw.index.tz))
    end = pd.Timestamp(dataset.end.astimezone(raw.index.tz))
    mask = (raw.index >= start) & (raw.index <= end)
    return raw.loc[mask] if mask.any() else raw.tail(4000)


def _engine_ml_signal(ctx, router_engine: str) -> tuple[str, float]:
    """Raw ML engine output before orchestrator / calibration / filters."""
    if router_engine == "phase9_9":
        sig = str(ctx.range_signal.signal)
        prob = float(ctx.range_signal.probability)
    else:
        sig = str(ctx.trend_signal.signal)
        prob = float(ctx.trend_signal.probability)
    if sig not in ("BUY", "SELL"):
        return "HOLD", prob
    return sig, prob


def _first_blocking_filter(
    *,
    ml_direction: str,
    cal_action: str,
    risk_allowed: bool,
    quality_allowed: bool,
    filt_passed: bool | None,
    filt_blocked: list[str],
    kernel_direction: str,
) -> str | None:
    if ml_direction not in ("BUY", "SELL"):
        return "DecisionOrchestrator"
    if cal_action not in ("BUY", "SELL"):
        return "Calibration"
    if not risk_allowed:
        return "AdaptiveRisk"
    if not quality_allowed:
        return "TradeQuality"
    if filt_passed is False:
        if "rsi_filter" in filt_blocked:
            return "RSI Filter"
        if "adx_filter" in filt_blocked:
            return "ADX Filter"
        return "ProfitabilityFilters"
    if kernel_direction not in ("BUY", "SELL"):
        return "KernelInternal"
    return None


def _infer_kernel_direction(
    cal_action: str,
    risk_allowed: bool,
    quality_allowed: bool,
    filt_passed: bool | None,
) -> str:
    """Mirror produce_unified_signal gate logic without calling the full pipeline."""
    if cal_action not in ("BUY", "SELL"):
        return "HOLD"
    if not risk_allowed or not quality_allowed:
        return "HOLD"
    if filt_passed is False:
        return "HOLD"
    return cal_action


async def collect_raw_ml_signals(
    dataset: RapidDataset,
    *,
    timeframe: str = "M5",
    warmup: int = 300,
    use_fullest_candles: bool = False,
) -> dict[str, Any]:
    """Walk every bar; capture calibrated ML direction BEFORE risk/quality/RiskGate/execution."""
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.phase19c.filters import apply_profitability_filters, load_filter_settings
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
    from tradingbot.ml.decision_engine.strategy_selector import select_engine

    PipelineCache.reset()
    legacy = load_legacy_config()
    base_dir = legacy.get("BASE_DIR")
    stack = build_ml_kernel_stack(base_dir=base_dir)
    deps = stack.as_dependencies(base_dir=base_dir)
    adapter = KernelAdapter(deps)

    frame = await _load_candles(dataset, timeframe, use_fullest=use_fullest_candles)
    if frame is None or len(frame) < warmup + 10:
        return {"error": "no_data", "signals": [], "all_bars": []}

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.set_index("timestamp")
    frame.index = pd.to_datetime(frame.index, utc=True)

    trend_id = resolve_active_trend_engine_id()
    signals: list[dict[str, Any]] = []
    all_bars: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    for i in range(warmup, len(frame)):
        window = frame.iloc[: i + 1]
        ts = str(window.index[-1])

        try:
            range_inner, trend_inner = adapter._engine_inners()
            unified_frame = PipelineCache.get_unified_frame(
                window,
                base_dir=base_dir,
                symbol="XAUUSD",
                timeframe=timeframe,
            )
            if unified_frame.empty:
                continue

            row = unified_frame.iloc[-1]
            row_dict = row.to_dict()
            fchk = row_checksum(row_dict)
            atr_pct = float(row_dict.get("atr_percentile", row_dict.get("atr_pct", 50)) or 50)
            vol_state = classify_volatility(atr_pct)

            ctx = build_market_context(
                row,
                symbol="XAUUSD",
                timeframe=timeframe,
                range_engine=range_inner,
                trend_engine=trend_inner,
            )
            regime = str(ctx.regime)
            router_engine = select_engine(regime)
            ml_direction, prob = _engine_ml_signal(ctx, router_engine)

            calibrated, risk, quality = stack.quality.evaluate(ctx)
            raw_action = str(calibrated.decision.action)
            cal_action = str(calibrated.final_action)
            confidence = float(calibrated.final_confidence)
            quality_score = float(quality.score) if hasattr(quality, "score") else 0.0

            filt = None
            filt_blocked: list[str] = []
            if cal_action in ("BUY", "SELL") and risk.allowed and quality.allowed:
                filt = apply_profitability_filters(row_dict, settings=load_filter_settings())
                if not filt.passed:
                    filt_blocked = list(filt.blocked_by)

            kernel_dir = _infer_kernel_direction(
                cal_action, risk.allowed, quality.allowed, filt.passed if filt else None
            )

            first_block = _first_blocking_filter(
                ml_direction=ml_direction,
                cal_action=cal_action,
                risk_allowed=risk.allowed,
                quality_allowed=quality.allowed,
                filt_passed=filt.passed if filt else None,
                filt_blocked=filt_blocked,
                kernel_direction=kernel_dir,
            )
            executed = kernel_dir in ("BUY", "SELL")

            bar_rec = {
                "timestamp": ts,
                "bar_index": i,
                "raw_ml_direction": ml_direction,
                "calibrated_direction": cal_action,
                "kernel_direction": kernel_dir,
                "first_blocking_filter": first_block,
                "executed_path": executed,
                "regime": regime,
                "volatility_state": vol_state,
            }
            all_bars.append(bar_rec)

            if ml_direction not in ("BUY", "SELL"):
                continue

            signals.append({
                "signal_id": f"raw_{len(signals):05d}",
                "timestamp": ts,
                "bar_index": i,
                "symbol": "XAUUSD",
                "timeframe": timeframe,
                "direction": ml_direction,
                "confidence": round(confidence, 4),
                "probability": round(prob, 4),
                "quality_score": round(quality_score, 4),
                "regime": regime,
                "volatility_state": vol_state,
                "engine": router_engine,
                "orchestrator_action": raw_action,
                "calibrated_action": cal_action,
                "kernel_direction": kernel_dir,
                "feature_checksum": fchk,
                "risk_allowed": risk.allowed,
                "quality_allowed": quality.allowed,
                "filters_passed": filt.passed if filt else None,
                "filters_blocked_by": filt_blocked,
                "first_blocking_filter": first_block,
                "would_reach_execution": executed,
                "adx": float(row_dict.get("adx", 0) or 0),
                "atr": float(row_dict.get("atr", 0) or 0),
                "rsi": float(row_dict.get("rsi", 0) or 0),
                "spread_pips": float(row_dict.get("spread_pips", 3.0) or 3.0),
                "active_trend_engine": trend_id,
            })
        except Exception as exc:
            all_bars.append({"timestamp": ts, "bar_index": i, "error": str(exc)})

        if (i - warmup) % 500 == 0 and i > warmup:
            print(f"  scanned {i - warmup}/{len(frame) - warmup} bars, raw_signals={len(signals)}", flush=True)

    return {
        "dataset": dataset.to_dict(),
        "timeframe": timeframe,
        "bars_scanned": len(frame) - warmup,
        "raw_signal_count": len(signals),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "signals": signals,
        "all_bars": all_bars,
    }
