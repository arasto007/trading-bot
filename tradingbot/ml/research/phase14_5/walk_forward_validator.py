"""Phase 14.5 — yearly walk-forward validation."""

from __future__ import annotations

from typing import Any

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_5.config import WF_YEARS
from tradingbot.ml.research.phase14_5.pipeline_runner import RegimeConfidencePolicy, run_pipeline_with_policy, sweep_metrics

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
    *,
    confidence_threshold: float,
    regime_policy: RegimeConfidencePolicy | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quick: bool = False,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
) -> dict[str, Any]:
    years = WF_YEARS[:2] if quick else WF_YEARS
    windows: list[dict[str, Any]] = []

    for year in years:
        test_c, test_ds = _slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            windows.append({"year": year, "skipped": True, "shuffle": False})
            continue
        records = run_pipeline_with_policy(
            test_c,
            test_ds,
            confidence_threshold=confidence_threshold,
            regime_policy=regime_policy,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            stride=3,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=None,
        )
        metrics = sweep_metrics(records, stride=3)
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
    robustness = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)

    return {
        "phase": "14.5",
        "windows": windows,
        "robustness_score": robustness,
        "mean_profit_factor": round(float(np.mean(pfs)), 4) if pfs else 0.0,
        "chronological": True,
        "shuffle": False,
    }
