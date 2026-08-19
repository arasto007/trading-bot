"""Phase 13.9 — walk-forward validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_9.config import WALK_FORWARD_YEARS_139
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_router_backtest
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig


def run_walk_forward_unified(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    config: OptimizerConfig,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

    frame = build_unified_frame(candles, dataset)
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    years = WALK_FORWARD_YEARS_139[:1] if quick else WALK_FORWARD_YEARS_139
    windows: list[dict[str, Any]] = []

    for year in years:
        test_mask = ts.dt.year == year
        train_mask = ts.dt.year < year
        if not test_mask.any():
            windows.append({"window_id": f"wf_{year}", "skipped": True})
            continue
        test_idx = frame.index[test_mask]
        test_candles = _slice_candles(candles, frame.loc[test_mask, "timestamp"])
        test_ds = None
        if dataset is not None and not dataset.empty:
            test_ds = dataset[
                pd.to_datetime(dataset["timestamp"], utc=True).isin(
                    pd.to_datetime(frame.loc[test_mask, "timestamp"], utc=True)
                )
            ]
        bt = run_unified_router_backtest(
            test_candles, test_ds, config=config, seed=seed, symbol=symbol, base_dir=base_dir
        )
        m = bt["metrics"]
        windows.append(
            {
                "window_id": f"wf_{year}",
                "test_year": year,
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                "metrics": m,
                "shuffle": False,
            }
        )

    active = [w for w in windows if not w.get("skipped")]
    pfs = [float(w["metrics"]["profit_factor"]) for w in active]
    robustness = round(max(0.0, 1.0 - float(np.std(pfs)) if len(pfs) > 1 else 0.5), 4)
    return {
        "windows": windows,
        "robustness_score": robustness,
        "chronological": True,
        "shuffle": False,
    }


def _slice_candles(candles: pd.DataFrame, timestamps: pd.Series) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    ts_set = set(pd.to_datetime(timestamps, utc=True))
    return c.loc[c.index.isin(ts_set)].sort_index()
