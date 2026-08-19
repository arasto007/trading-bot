"""Phase 16B — full kernel pipeline replay diagnostics (no live execution)."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.models import MarketKey
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.monitoring.statistics import latency_summary, percentile
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase16b.config import DEFAULT_WARMUP, RF_THRESHOLD
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    end = candles.index.max()
    return candles[candles.index >= end - timedelta(days=days)]


def _dist(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0}
    a = np.asarray(vals, dtype=float)
    return {
        "count": int(len(a)),
        "p50": round(float(np.percentile(a, 50)), 6),
        "p95": round(float(np.percentile(a, 95)), 6),
        "max": round(float(np.max(a)), 6),
        "mean": round(float(np.mean(a)), 6),
    }


def replay_kernel_window(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int,
    stride: int,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, Any]:
    """
    Replay full ML pipeline on prebuilt unified frame:

    Regime → Router → FeatureAligner → Engines → DecisionPolicy
    → Calibration → RiskGate → Quality → kernel output (no execution).

    Feature frame is built once (same inputs as KernelAdapter); per-bar path
    mirrors produce_unified_signal after PipelineCache.get_unified_frame.
    """
    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    range_inner, trend_inner = adapter._engine_inners()  # noqa: SLF001

    window = prepare_calibration_candles(candles, days=days)
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    unified = build_unified_frame(window, dataset)

    kernel_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    range_kernel = trend_kernel = 0
    risk_blocked = quality_blocked = 0
    engine_stage = {
        "TREND": {"actionable": 0, "rejected": 0, "probs": [], "buy": 0, "sell": 0},
        "RANGE": {"actionable": 0, "rejected": 0, "probs": [], "buy": 0, "sell": 0},
    }
    latencies: list[float] = []
    confidences: list[float] = []

    start = max(warmup, 0)
    for i in range(start, len(unified), max(1, stride)):
        row = unified.iloc[i]
        regime = rule_classify_row(row)

        t0 = time.perf_counter()
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_inner,
            trend_engine=trend_inner,
        )
        _ = stack.orchestrator.decide(ctx)
        calibrated, risk, quality = stack.quality.evaluate(ctx)
        latencies.append((time.perf_counter() - t0) * 1000)

        action = str(calibrated.final_action)
        if action not in ("BUY", "SELL"):
            action = "HOLD"
        if not risk.allowed or not quality.allowed:
            if action in ("BUY", "SELL"):
                if not risk.allowed:
                    risk_blocked += 1
                elif not quality.allowed:
                    quality_blocked += 1
            action = "HOLD"

        if action in ("BUY", "SELL"):
            kernel_counts[action] += 1
            confidences.append(float(calibrated.final_confidence))
            if calibrated.decision.regime == "RANGE":
                range_kernel += 1
            elif calibrated.decision.regime == "TREND":
                trend_kernel += 1
        else:
            kernel_counts["HOLD"] += 1

        # Engine-level health (aligned TREND path)
        if regime == "TREND":
            aligned_row = (
                trend_inner.aligner.align_row(row)
                if getattr(trend_inner, "aligner", None) is not None
                else row
            )
            ml = apply_trend_ml_filter(
                aligned_row,
                model=bundle.model,
                scaler=bundle.scaler,
                model_name="random_forest",
                threshold=RF_THRESHOLD,
            )
            rule = evaluate_variant_a(row, regime="TREND")
            prob = float(ml["probability"])
            engine_stage["TREND"]["probs"].append(prob)
            if prob >= RF_THRESHOLD and rule in ("BUY", "SELL"):
                engine_stage["TREND"]["actionable"] += 1
                engine_stage["TREND"][rule.lower()] += 1
            else:
                engine_stage["TREND"]["rejected"] += 1
        elif regime == "RANGE":
            sig_r = ctx.range_signal.signal
            prob = float(ctx.range_signal.probability)
            engine_stage["RANGE"]["probs"].append(prob)
            if sig_r in ("BUY", "SELL"):
                engine_stage["RANGE"]["actionable"] += 1
                engine_stage["RANGE"][sig_r.lower()] += 1
            else:
                engine_stage["RANGE"]["rejected"] += 1

    # Latency sample via real adapter path (few bars only)
    market = MarketKey(symbol, timeframe)
    full_window = _filter_days(candles, days)
    sample_idx = list(range(warmup, min(len(full_window), warmup + stride * 20), stride))
    adapter_lat: list[float] = []
    for i in sample_idx:
        full_idx = candles.index.get_loc(full_window.index[i])
        if isinstance(full_idx, slice):
            continue
        sl = candles.iloc[max(0, int(full_idx) - warmup) : int(full_idx) + 1]
        t0 = time.perf_counter()
        try:
            adapter.generate_signal(market, sl.copy())
        except Exception:
            pass
        adapter_lat.append((time.perf_counter() - t0) * 1000)

    bars = sum(kernel_counts.values()) or 1
    actionable = kernel_counts["BUY"] + kernel_counts["SELL"]
    trend_bars = engine_stage["TREND"]["actionable"] + engine_stage["TREND"]["rejected"]
    range_bars = engine_stage["RANGE"]["actionable"] + engine_stage["RANGE"]["rejected"]
    warm_lat = latencies[3:] if len(latencies) > 3 else latencies

    return {
        "days": days,
        "stride": stride,
        "bars_evaluated": bars,
        "kernel": {
            "buy": kernel_counts["BUY"],
            "sell": kernel_counts["SELL"],
            "hold": kernel_counts["HOLD"],
            "actionable": actionable,
            "actionable_rate": round(actionable / bars, 6),
            "range_contribution": range_kernel,
            "trend_contribution": trend_kernel,
            "range_contribution_pct": round(range_kernel / max(actionable, 1), 4),
            "trend_contribution_pct": round(trend_kernel / max(actionable, 1), 4),
            "mean_confidence": round(float(np.mean(confidences)), 6) if confidences else 0.0,
        },
        "engine_health": {
            "TREND": {
                "actionable_rate": round(engine_stage["TREND"]["actionable"] / max(trend_bars, 1), 6),
                "rejection_rate": round(engine_stage["TREND"]["rejected"] / max(trend_bars, 1), 6),
                "buy": engine_stage["TREND"]["buy"],
                "sell": engine_stage["TREND"]["sell"],
                "probability": _dist(engine_stage["TREND"]["probs"]),
            },
            "RANGE": {
                "actionable_rate": round(engine_stage["RANGE"]["actionable"] / max(range_bars, 1), 6),
                "rejection_rate": round(engine_stage["RANGE"]["rejected"] / max(range_bars, 1), 6),
                "buy": engine_stage["RANGE"]["buy"],
                "sell": engine_stage["RANGE"]["sell"],
                "probability": _dist(engine_stage["RANGE"]["probs"]),
            },
        },
        "pipeline_blocks": {
            "risk_blocked": risk_blocked,
            "quality_blocked": quality_blocked,
        },
        "stability_proxy": {
            "expectancy_proxy": round(float(np.mean(confidences)) * actionable / bars, 6) if confidences else 0.0,
            "pf_proxy": round(actionable / max(kernel_counts["HOLD"], 1), 4),
        },
        "latency": {
            **latency_summary(warm_lat),
            "p95_ms": round(percentile(warm_lat, 0.95), 3) if warm_lat else 0.0,
            "adapter_sample_p95_ms": round(percentile(adapter_lat, 0.95), 3) if adapter_lat else 0.0,
        },
    }


def replay_without_aligner_baseline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int,
    stride: int,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
) -> int:
    """Count TREND engine actionable without aligner (inflation baseline)."""
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    count = 0
    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        ml = apply_trend_ml_filter(
            row,
            model=bundle.model,
            scaler=bundle.scaler,
            model_name="random_forest",
            threshold=RF_THRESHOLD,
        )
        rule = evaluate_variant_a(row, regime="TREND")
        if ml["probability"] >= RF_THRESHOLD and rule in ("BUY", "SELL"):
            count += 1
    return count
