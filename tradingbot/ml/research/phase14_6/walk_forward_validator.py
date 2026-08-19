"""Phase 14.6 — walk-forward calibration validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod
from tradingbot.ml.research.phase14_6.config import WF_YEARS
from tradingbot.ml.research.phase14_6.pipeline_runner import pipeline_metrics, run_research_pipeline

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
        records = run_research_pipeline(
            test_c,
            test_ds,
            calibration_method=calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            stride=5,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=None,
        )
        metrics = pipeline_metrics(records, stride=5)
        windows.append(
            {
                "year": year,
                "metrics": metrics,
                "trades": metrics["trades"],
                "profit_factor": metrics["profit_factor"],
                "expectancy": metrics["expectancy"],
                "confidence_distribution": metrics.get("confidence_distribution"),
                "shuffle": False,
            }
        )

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["profit_factor"]) for w in active]
    robustness = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)

    return {
        "phase": "14.6",
        "calibration_method": getattr(calibration_method, "name", "unknown"),
        "confidence_threshold": confidence_threshold,
        "windows": windows,
        "robustness_score": robustness,
        "mean_profit_factor": round(float(np.mean(pfs)), 4) if pfs else 0.0,
        "chronological": True,
        "shuffle": False,
    }
