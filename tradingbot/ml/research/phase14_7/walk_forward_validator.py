"""Phase 14.7 — walk-forward validation for full pipeline."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod
from tradingbot.ml.research.phase14_7.config import WF_YEARS
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline

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


def run_walk_forward_validation(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method: CalibrationMethod,
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
        records = run_full_pipeline(
            test_c,
            test_ds,
            calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            stride=5,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=None,
        )
        metrics = analyze_performance(records, stride=5)
        windows.append(
            {
                "year": year,
                "metrics": metrics,
                "trades": metrics["trades"],
                "profit_factor": metrics["profit_factor"],
                "expectancy": metrics["expectancy"],
                "shuffle": False,
            }
        )

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["profit_factor"]) for w in active]
    exps = [float(w["expectancy"]) for w in active]
    trades = [int(w["trades"]) for w in active]

    pf_stability = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)
    exp_stability = round(max(0.0, 1.0 - float(np.std(exps)) if len(exps) > 1 else 0.5), 4)
    trade_stability = round(max(0.0, 1.0 - float(np.std(trades)) / max(np.mean(trades), 1) if len(trades) > 1 else 0.5), 4)
    robustness = round((pf_stability + exp_stability + trade_stability) / 3.0, 4)

    return {
        "phase": "14.7",
        "windows": windows,
        "pf_stability": pf_stability,
        "expectancy_stability": exp_stability,
        "trade_count_stability": trade_stability,
        "robustness_score": robustness,
        "chronological": True,
        "shuffle": False,
    }
