"""Phase 17B — shadow kernel replay: frozen RF vs research RF."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.monitoring.statistics import latency_summary, percentile
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase17b.config import DEFAULT_STRIDE, DEFAULT_WARMUP, RF_THRESHOLD
from tradingbot.ml.research.phase17b.research_engine import ResearchTrendEngine
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _replay_path(
    unified: pd.DataFrame,
    *,
    stack: Any,
    range_inner: Any,
    trend_inner: Any,
    symbol: str,
    timeframe: str,
    stride: int,
    warmup: int,
    label: str,
) -> dict[str, Any]:
    kernel_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    range_kernel = trend_kernel = 0
    trend_engine_actionable = range_engine_actionable = 0
    probs: list[float] = []
    confidences: list[float] = []
    latencies: list[float] = []
    returns_proxy: list[float] = []

    start = max(warmup, 0)
    for i in range(start, len(unified), max(1, stride)):
        row = unified.iloc[i]
        regime = rule_classify_row(row)
        t0 = time.perf_counter()
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        _ = stack.orchestrator.decide(ctx)
        calibrated, risk, quality = stack.quality.evaluate(ctx)
        latencies.append((time.perf_counter() - t0) * 1000)

        action = str(calibrated.final_action)
        if action not in ("BUY", "SELL"):
            action = "HOLD"
        if not risk.allowed or not quality.allowed:
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

        if regime == "TREND":
            ev = trend_inner.evaluate(row, regime="TREND")
            prob = float(ev.get("probability", 0.0))
            probs.append(prob)
            if ev.get("signal") in ("BUY", "SELL"):
                trend_engine_actionable += 1
                returns_proxy.append(prob - RF_THRESHOLD)
        elif regime == "RANGE":
            if ctx.range_signal.signal in ("BUY", "SELL"):
                range_engine_actionable += 1

    actionable = kernel_counts["BUY"] + kernel_counts["SELL"]
    wins = sum(1 for r in returns_proxy if r > 0)
    losses = sum(1 for r in returns_proxy if r <= 0)
    pf = round(wins / max(losses, 1), 4) if returns_proxy else 0.0
    expectancy = round(float(np.mean(returns_proxy)), 6) if returns_proxy else 0.0
    warm = latencies[3:] if len(latencies) > 3 else latencies

    return {
        "label": label,
        "bars_evaluated": sum(kernel_counts.values()),
        "kernel": {
            "actionable": actionable,
            "buy": kernel_counts["BUY"],
            "sell": kernel_counts["SELL"],
            "range_contribution": range_kernel,
            "trend_contribution": trend_kernel,
        },
        "engine": {
            "trend_actionable": trend_engine_actionable,
            "range_actionable": range_engine_actionable,
            "trend_max_prob": round(float(max(probs)), 6) if probs else 0.0,
            "trend_mean_prob": round(float(np.mean(probs)), 6) if probs else 0.0,
        },
        "pf_proxy": pf,
        "expectancy_proxy": expectancy,
        "drawdown_proxy": round(float(np.min(np.minimum.accumulate(returns_proxy))) if returns_proxy else 0.0, 6),
        "latency": {
            **latency_summary(warm),
            "p95_ms": round(percentile(warm, 0.95), 3) if warm else 0.0,
        },
    }


def run_shadow_replay(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    research: ResearchRfModel,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, Any]:
    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    # Pre-attach top5 once for research path (avoids per-bar feature recompute latency).
    unified_research = attach_top5_features(unified)
    load_trend_bundle(base_dir=base_dir, build_if_missing=False)

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    range_inner, frozen_trend = adapter._engine_inners()  # noqa: SLF001

    research_trend = ResearchTrendEngine(
        research_model=research,
        rule_fn=evaluate_variant_a,
        symbol=symbol,
    )

    frozen_result = _replay_path(
        unified, stack=stack, range_inner=range_inner, trend_inner=frozen_trend,
        symbol=symbol, timeframe=timeframe, stride=stride, warmup=warmup, label="frozen_rf_v40",
    )
    research_result = _replay_path(
        unified_research, stack=stack, range_inner=range_inner, trend_inner=research_trend,
        symbol=symbol, timeframe=timeframe, stride=stride, warmup=warmup, label="research_rf_top5",
    )

    range_delta = abs(
        frozen_result["kernel"]["range_contribution"] - research_result["kernel"]["range_contribution"]
    )
    return {
        "phase": "17B",
        "days": days,
        "stride": stride,
        "no_execution": True,
        "frozen": frozen_result,
        "research": research_result,
        "comparison": {
            "trend_actionable_delta": (
                research_result["engine"]["trend_actionable"] - frozen_result["engine"]["trend_actionable"]
            ),
            "trend_kernel_delta": (
                research_result["kernel"]["trend_contribution"] - frozen_result["kernel"]["trend_contribution"]
            ),
            "range_kernel_delta": range_delta,
            "range_identical": range_delta == 0,
            "ceiling_delta": round(
                research_result["engine"]["trend_max_prob"] - frozen_result["engine"]["trend_max_prob"], 6,
            ),
            "pf_delta": round(research_result["pf_proxy"] - frozen_result["pf_proxy"], 4),
            "latency_p95_delta_ms": round(
                research_result["latency"]["p95_ms"] - frozen_result["latency"]["p95_ms"], 3,
            ),
        },
    }
