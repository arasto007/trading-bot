"""Phase 14.8 — extended walk-forward validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_8.config import WF_YEARS

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


def _engine_breakdown(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for eng in ("phase9_9", "trend_rf_v40"):
        subset = [r for r in records if r.get("allowed") and str(r.get("engine")) == eng]
        out[eng] = trade_metrics_from_records(subset)
    return out


def run_walk_forward_extended(
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
        records = run_full_pipeline(
            test_c, test_ds, calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=5,
            range_engine=range_engine, trend_engine=trend_engine, unified=None,
        )
        metrics = analyze_performance(records, stride=5)
        windows.append(
            {
                "year": year,
                "metrics": metrics,
                "trades": metrics["trades"],
                "profit_factor": metrics["profit_factor"],
                "expectancy": metrics["expectancy"],
                "engine_breakdown": _engine_breakdown(records),
                "shuffle": False,
            }
        )

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["profit_factor"]) for w in active]
    exps = [float(w["expectancy"]) for w in active]
    trades = [int(w["trades"]) for w in active]

    pf_stab = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)
    exp_stab = round(max(0.0, 1.0 - float(np.std(exps)) if len(exps) > 1 else 0.5), 4)
    trade_stab = round(max(0.0, 1.0 - float(np.std(trades)) / max(np.mean(trades), 1) if len(trades) > 1 else 0.5), 4)
    robustness = round((pf_stab + exp_stab + trade_stab) / 3.0, 4)

    train_test_gap = 0.0
    if len(pfs) >= 2:
        train_test_gap = round(abs(pfs[0] - pfs[-1]) / max(max(pfs), 0.01), 4)

    return {
        "phase": "14.8",
        "windows": windows,
        "pf_stability": pf_stab,
        "expectancy_stability": exp_stab,
        "trade_count_stability": trade_stab,
        "robustness_score": robustness,
        "train_test_gap": train_test_gap,
        "overfit_detected": train_test_gap > 0.5,
        "chronological": True,
        "shuffle": False,
    }
