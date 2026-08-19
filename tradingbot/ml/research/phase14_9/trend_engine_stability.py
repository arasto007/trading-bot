"""Phase 14.9 — Trend RF v40 period stability analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_9.config import TREND_ENGINE_ID, VALIDATION_PERIODS


def _slice_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    cutoff = c.index.max() - pd.Timedelta(days=days)
    return c.loc[c.index >= cutoff].sort_index()


def analyze_trend_stability(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | None = None,
    periods: tuple[int, ...] | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    period_list = (90, 180) if quick else (periods or VALIDATION_PERIODS)
    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    per_period: dict[str, Any] = {}

    for days in period_list:
        c = _slice_days(candles, days)
        if c.empty:
            continue
        unified = build_unified_frame(c, dataset)
        cal_method, cal_policy = load_recovered_calibration(
            c, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
            stride=5, range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        records = run_adaptive_router_pipeline(
            c, dataset, cal_method,
            confidence_threshold=float(cal_policy["confidence_threshold"]),
            symbol=symbol, timeframe=timeframe, seed=seed, stride=5,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        trend_only = [r for r in records if r.get("allowed") and str(r.get("engine")) == TREND_ENGINE_ID]
        metrics = trade_metrics_from_records(trend_only)
        per_period[str(days)] = {
            "days": days,
            "trend_trades": metrics["trades"],
            "profit_factor": metrics["profit_factor"],
            "expectancy": metrics["expectancy"],
            "positive": float(metrics["expectancy"]) > 0,
        }

    positive = sum(1 for p in per_period.values() if p.get("positive"))
    pfs = [float(p["profit_factor"]) for p in per_period.values()]
    period_dependency = max(pfs) - min(pfs) if len(pfs) > 1 else 0.0

    return {
        "phase": "14.9",
        "engine": TREND_ENGINE_ID,
        "periods": per_period,
        "positive_periods": positive,
        "period_dependency_score": round(period_dependency, 4),
        "period_dependency_high": period_dependency > 2.0,
    }
