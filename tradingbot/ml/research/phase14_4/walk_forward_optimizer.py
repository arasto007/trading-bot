"""Phase 14.4 — walk-forward threshold validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.config import WF_WINDOWS
from tradingbot.ml.research.phase14_4.pipeline_simulator import PipelineThresholds, run_pipeline_records, trade_metrics_from_records
from tradingbot.ml.research.phase14_4.robustness_validator import pf_stability


def _slice_candles(candles: pd.DataFrame, *, start_year: int, end_year: int) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    mask = (c.index.year >= start_year) & (c.index.year <= end_year)
    return c.loc[mask].sort_index()


def run_walk_forward_optimization(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    thresholds: PipelineThresholds,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    quick: bool = False,
) -> dict[str, Any]:
    windows_cfg = WF_WINDOWS[:2] if quick else WF_WINDOWS
    windows: list[dict[str, Any]] = []

    for test_year, train_start, train_end in windows_cfg:
        if test_year < 2021 or test_year > 2026:
            continue
        test_candles = _slice_candles(candles, start_year=test_year, end_year=test_year)
        if test_candles.empty:
            windows.append({"test_year": test_year, "skipped": True, "shuffle": False})
            continue

        test_ds = None
        if dataset is not None and not dataset.empty:
            ds = dataset.copy()
            ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)
            test_ds = ds[ds["timestamp"].dt.year == test_year]

        records = run_pipeline_records(
            test_candles,
            test_ds,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            thresholds=thresholds,
            stride=5,
        )
        metrics = trade_metrics_from_records(records)
        windows.append(
            {
                "window_id": f"train_{train_start}_{train_end}_test_{test_year}",
                "test_year": test_year,
                "train_years": [train_start, train_end],
                "metrics": metrics,
                "trades": metrics["trades"],
                "profit_factor": metrics["profit_factor"],
                "shuffle": False,
            }
        )

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["profit_factor"]) for w in active]
    stability = pf_stability(pfs)

    return {
        "phase": "14.4",
        "method": "expanding_window",
        "windows": windows,
        "robustness_score": stability,
        "mean_profit_factor": round(float(sum(pfs) / len(pfs)), 4) if pfs else 0.0,
        "chronological": True,
        "shuffle": False,
    }
