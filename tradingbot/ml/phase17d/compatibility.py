"""Phase 17D — 365d production pipeline compatibility vs Phase 17C."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase17b.research_engine import ResearchTrendEngine
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.shadow_replay import _replay_path
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.phase17d.config import DEFAULT_STRIDE, DEFAULT_WARMUP, REPLAY_DAYS, TREND_VERSION_ENV
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id


def _load_phase17c_baseline(base_dir: str | Path | None) -> dict[str, Any]:
    from tradingbot.ml.data.paths import reports_dir

    path = reports_dir(base_dir) / "phase17c" / "phase17c_final_report.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_compatibility_replay(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = REPLAY_DAYS,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, Any]:
    """
    Replay production pipeline with promoted v41 bundle; compare to Phase 17C research path.
    """
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    unified_v41 = attach_top5_features(unified)

    bundle_v41 = load_trend_bundle(base_dir=base_dir, version="v41")
    research_model = ResearchRfModel(
        model=bundle_v41.model,
        scaler=bundle_v41.scaler,
        feature_order=list(bundle_v41.feature_order),
        seed=int(bundle_v41.metadata.get("seed", 42)),
        train_rows=int(bundle_v41.metadata.get("train_rows", 0)),
    )

    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()
    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        range_inner, v41_trend = adapter._engine_inners()  # noqa: SLF001

        v41_result = _replay_path(
            unified_v41, stack=stack, range_inner=range_inner, trend_inner=v41_trend,
            symbol=symbol, timeframe=timeframe, stride=stride, warmup=warmup, label="production_v41",
        )

        os.environ[TREND_VERSION_ENV] = "v40"
        PipelineCache.reset()
        stack_v40 = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
        adapter_v40 = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack_v40)
        range_inner_v40, v40_trend = adapter_v40._engine_inners()  # noqa: SLF001

        v40_result = _replay_path(
            unified, stack=stack_v40, range_inner=range_inner_v40, trend_inner=v40_trend,
            symbol=symbol, timeframe=timeframe, stride=stride, warmup=warmup, label="production_v40",
        )
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev

    research_trend = ResearchTrendEngine(research_model=research_model, rule_fn=evaluate_variant_a, symbol=symbol)
    research_result = _replay_path(
        unified_v41, stack=stack, range_inner=range_inner, trend_inner=research_trend,
        symbol=symbol, timeframe=timeframe, stride=stride, warmup=warmup, label="phase17c_research",
    )

    range_delta = abs(v41_result["kernel"]["range_contribution"] - v40_result["kernel"]["range_contribution"])
    research_trend_delta = abs(
        v41_result["engine"]["trend_actionable"] - research_result["engine"]["trend_actionable"]
    )
    ceiling_delta = abs(
        v41_result["engine"]["trend_max_prob"] - research_result["engine"]["trend_max_prob"]
    )

    baseline = _load_phase17c_baseline(base_dir)
    baseline_summary = baseline.get("summary", {}).get("365d", {})

    passed = (
        range_delta == 0
        and research_trend_delta == 0
        and ceiling_delta <= 0.01
        and v41_result["engine"]["trend_actionable"] >= v40_result["engine"]["trend_actionable"]
    )

    return {
        "phase": "17D",
        "days": days,
        "passed": passed,
        "production_v41": v41_result,
        "production_v40": v40_result,
        "phase17c_research": research_result,
        "comparison": {
            "range_identical_v40_v41": range_delta == 0,
            "range_kernel_delta": range_delta,
            "trend_actionable_v41": v41_result["engine"]["trend_actionable"],
            "trend_actionable_v40": v40_result["engine"]["trend_actionable"],
            "trend_actionable_research": research_result["engine"]["trend_actionable"],
            "trend_actionable_delta_vs_research": research_trend_delta,
            "ceiling_delta_vs_research": round(ceiling_delta, 6),
            "trend_improved_vs_v40": (
                v41_result["engine"]["trend_actionable"] > v40_result["engine"]["trend_actionable"]
            ),
        },
        "phase17c_baseline": baseline_summary,
        "active_engine": resolve_active_trend_engine_id(),
    }
