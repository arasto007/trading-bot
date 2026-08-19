"""Phase 13.10 — expanding walk-forward validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_10.config import EXPANDING_WF_WINDOWS
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_router_backtest
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig


def _slice_by_years(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    start_year: int,
    end_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    mask = (c.index.year >= start_year) & (c.index.year <= end_year)
    sliced = c.loc[mask].sort_index()

    ds_out = None
    if dataset is not None and not dataset.empty:
        ds = dataset.copy()
        ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)
        ds_mask = (ds["timestamp"].dt.year >= start_year) & (ds["timestamp"].dt.year <= end_year)
        ds_out = ds.loc[ds_mask].reset_index(drop=True)
    return sliced, ds_out


def _slice_test_year(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    test_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    return _slice_by_years(candles, dataset, start_year=test_year, end_year=test_year)


def quick_wf_score_for_config(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    config: OptimizerConfig,
    trend_adapter: Any = None,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    quick: bool = False,
) -> float:
    windows = EXPANDING_WF_WINDOWS[:1] if quick else EXPANDING_WF_WINDOWS
    pfs: list[float] = []
    for test_year, train_start, train_end in windows:
        test_candles, test_ds = _slice_test_year(candles, dataset, test_year=test_year)
        if test_candles.empty:
            continue
        bt = run_unified_router_backtest(
            test_candles,
            test_ds,
            config=config,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            trend_adapter=trend_adapter,
        )
        pfs.append(float(bt["metrics"].get("profit_factor", 0.0)))
    if not pfs:
        return 0.0
    return round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)


def run_expanding_walk_forward(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    config: OptimizerConfig,
    trend_adapter: Any = None,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    windows_cfg = EXPANDING_WF_WINDOWS[:1] if quick else EXPANDING_WF_WINDOWS
    windows: list[dict[str, Any]] = []

    for test_year, train_start, train_end in windows_cfg:
        train_candles, train_ds = _slice_by_years(candles, dataset, start_year=train_start, end_year=train_end)
        test_candles, test_ds = _slice_test_year(candles, dataset, test_year=test_year)
        if test_candles.empty:
            windows.append(
                {
                    "window_id": f"train_{train_start}_{train_end}_test_{test_year}",
                    "train_years": [train_start, train_end],
                    "test_year": test_year,
                    "skipped": True,
                    "shuffle": False,
                }
            )
            continue

        bt = run_unified_router_backtest(
            test_candles,
            test_ds,
            config=config,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            trend_adapter=trend_adapter,
        )
        m = bt["metrics"]
        windows.append(
            {
                "window_id": f"train_{train_start}_{train_end}_test_{test_year}",
                "train_years": [train_start, train_end],
                "train_rows": len(train_candles),
                "test_year": test_year,
                "test_rows": len(test_candles),
                "metrics": m,
                "trades": int(m.get("trades", 0)),
                "profit_factor": round(float(m.get("profit_factor", 0.0)), 4),
                "expectancy": round(float(m.get("expectancy", m.get("expectancy_r", 0.0))), 4),
                "max_drawdown": round(float(m.get("max_drawdown", 0.0)), 4),
                "shuffle": False,
            }
        )

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["profit_factor"]) for w in active]
    robustness = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)

    return {
        "phase": "13.10",
        "method": "expanding_window",
        "windows": windows,
        "robustness_score": robustness,
        "mean_profit_factor": round(float(np.mean(pfs)), 4) if pfs else 0.0,
        "chronological": True,
        "shuffle": False,
        "dataset": "XAUUSD M5 2021-2026",
    }
