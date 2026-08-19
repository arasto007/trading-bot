"""Phase 14.9 — robustness validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance, sharpe_like_stability
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_9.config import (
    MIN_MC_PROFITABLE,
    MIN_PF,
    MIN_POSITIVE_PERIODS,
    MIN_TRADE_FLOOR,
    MIN_WF_ROBUSTNESS,
    MONTE_CARLO_SIMS,
    VALIDATION_PERIODS,
    WF_YEARS,
)

MIN_YEAR_BARS = 200


def _slice_year(candles: pd.DataFrame, dataset: pd.DataFrame | None, year: int) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.loc[c.index.year == year]
    ds = None
    if dataset is not None and not dataset.empty:
        ds = dataset.copy()
        ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)
        ds = ds[ds["timestamp"].dt.year == year]
    return c.sort_index(), ds


def _slice_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    cutoff = c.index.max() - pd.Timedelta(days=days)
    return c.loc[c.index >= cutoff].sort_index()


def run_walk_forward(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method,
    *,
    confidence_threshold: float,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quick: bool = False,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
) -> dict[str, Any]:
    years = WF_YEARS[:2] if quick else WF_YEARS
    windows: list[dict[str, Any]] = []
    for year in years:
        test_c, test_ds = _slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            windows.append({"year": year, "skipped": True, "shuffle": False})
            continue
        records = run_adaptive_router_pipeline(
            test_c, test_ds, calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=5,
            range_engine=range_engine, trend_engine=trend_engine,
        )
        m = analyze_performance(records, stride=5)
        windows.append({"year": year, "metrics": m, "shuffle": False})

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["metrics"]["profit_factor"]) for w in active]
    robustness = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)
    return {"phase": "14.9", "windows": windows, "robustness_score": robustness, "shuffle": False}


def run_monte_carlo(records: list[dict[str, Any]], *, simulations: int = MONTE_CARLO_SIMS, seed: int = 42) -> dict[str, Any]:
    from tradingbot.ml.research.phase14_8.monte_carlo_extended import run_monte_carlo_extended

    return run_monte_carlo_extended(records, simulations=simulations, seed=seed)


def run_multi_period(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method,
    *,
    confidence_threshold: float,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quick: bool = False,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
) -> dict[str, Any]:
    periods = (90, 180) if quick else VALIDATION_PERIODS
    per_period: dict[str, Any] = {}
    for days in periods:
        c = _slice_days(candles, days)
        if c.empty:
            continue
        records = run_adaptive_router_pipeline(
            c, dataset, calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=5,
            range_engine=range_engine, trend_engine=trend_engine,
        )
        m = analyze_performance(records, stride=5)
        per_period[str(days)] = {**m, "positive": float(m["expectancy"]) > 0}

    positive = sum(1 for p in per_period.values() if p.get("positive"))
    return {"phase": "14.9", "periods": per_period, "positive_periods": positive}


def validate_robustness(
    records: list[dict[str, Any]],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    multi_period: dict[str, Any],
    *,
    stride: int = 5,
) -> dict[str, Any]:
    m = analyze_performance(records, stride=stride)
    trades_est = int(m.get("effective_trades_est", 0))
    pf = float(m.get("profit_factor", 0))
    wf = float(walk_forward.get("robustness_score", 0))
    mc = float(monte_carlo.get("profitable_pct", 0))
    positive_periods = int(multi_period.get("positive_periods", 0))

    checks = {
        "pf_gt_12": pf >= MIN_PF,
        "trades_gte_300": trades_est >= MIN_TRADE_FLOOR,
        "wf_gt_040": wf > MIN_WF_ROBUSTNESS,
        "mc_gt_95pct": mc >= MIN_MC_PROFITABLE,
        "periods_positive_gte_2": positive_periods >= MIN_POSITIVE_PERIODS,
    }
    return {
        "phase": "14.9",
        "metrics": m,
        "checks": checks,
        "passes": all(checks.values()),
        "sharpe_stability": sharpe_like_stability([float(r["r_multiple"]) for r in records if r.get("allowed")]),
    }
