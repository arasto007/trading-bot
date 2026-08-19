"""Phase 14.8 — multi-period validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.baseline_runner import run_baseline_pipeline
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_7.router_runner import run_router_pipeline
from tradingbot.ml.research.phase14_8.config import GRID_STRIDE, MAX_RESEARCH_BARS, VALIDATION_PERIODS
from tradingbot.ml.research.phase14_8.stress_runner import build_atr_meta, run_scenario_stress, summarize_pipelines


def slice_candles(candles: pd.DataFrame, *, days: int) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    cutoff = c.index.max() - pd.Timedelta(days=days)
    c = c.loc[c.index >= cutoff].sort_index()
    if len(c) > MAX_RESEARCH_BARS:
        c = c.iloc[:: max(1, len(c) // MAX_RESEARCH_BARS)]
    return c


def run_multi_period_validation(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    periods: tuple[int, ...] | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | None = None,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    period_list = (90, 180) if quick else (periods or VALIDATION_PERIODS)
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

    per_period: dict[str, Any] = {}
    for days in period_list:
        c = slice_candles(candles, days=days)
        unified = build_unified_frame(c, dataset)
        atr_meta = build_atr_meta(unified)
        cal_method, cal_policy = load_recovered_calibration(
            c, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
            stride=GRID_STRIDE, range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        th = float(cal_policy["confidence_threshold"])
        baseline = run_baseline_pipeline(
            c, dataset, symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        router = run_router_pipeline(
            c, dataset, symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        full = run_full_pipeline(
            c, dataset, cal_method, confidence_threshold=th,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        pipelines = summarize_pipelines(baseline, router, full, stride=GRID_STRIDE)
        per_period[str(days)] = {
            "days": days,
            "pipelines": pipelines,
            "scenarios": run_scenario_stress(baseline, router, full, atr_meta=atr_meta, stride=GRID_STRIDE)["scenarios"],
            "full_positive": float(pipelines["phase14_full"]["expectancy"]) > 0,
        }

    positive_count = sum(1 for p in per_period.values() if p.get("full_positive"))
    return {
        "phase": "14.8",
        "periods": per_period,
        "positive_periods": positive_count,
        "all_periods_positive": positive_count == len(per_period),
    }
