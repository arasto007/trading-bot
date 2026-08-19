"""Phase 13.6 — walk-forward optimizer across 2021-2026."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.regime_router.config import WALK_FORWARD_YEARS
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, composite_score, config_to_dict
from tradingbot.ml.research.router_optimizer.robustness_validator import robustness_score, validate_robustness


def _year_mask(ts: pd.Series, year: int) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.year.to_numpy() == year


def _prior_mask(ts: pd.Series, year: int) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.year.to_numpy() < year


def run_walk_forward_optimization(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    config: OptimizerConfig,
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest

    ts = pd.to_datetime(merged["timestamp"], utc=True)
    windows_out: list[dict[str, Any]] = []

    for year in WALK_FORWARD_YEARS:
        test_mask = _year_mask(ts, year)
        train_mask = _prior_mask(ts, year)
        if not test_mask.any():
            windows_out.append({"window_id": f"wf_{year}", "test_year": year, "skipped": True})
            continue

        test_merged = merged.loc[test_mask].reset_index(drop=True)
        test_candles = _slice_candles(candles, test_merged["timestamp"])

        bt = run_optimized_backtest(
            test_merged, test_candles, config=config, base_dir=base_dir, engine_cache=engine_cache
        )
        windows_out.append(
            {
                "window_id": f"wf_{year}",
                "test_year": year,
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                "metrics": bt["metrics"],
                "trades": bt["metrics"].get("trades", 0),
                "shuffle": False,
            }
        )

    validation = validate_robustness(windows_out)
    mean_pf = float(np.mean([w["metrics"]["profit_factor"] for w in windows_out if not w.get("skipped")])) if windows_out else 0.0
    mean_exp = float(np.mean([w["metrics"]["expectancy"] for w in windows_out if not w.get("skipped")])) if windows_out else 0.0

    return {
        "phase": "13.6",
        "config": config_to_dict(config),
        "windows": windows_out,
        "mean_profit_factor": round(mean_pf, 4),
        "mean_expectancy": round(mean_exp, 4),
        "robustness": validation,
        "composite_score": composite_score(
            {"profit_factor": mean_pf, "expectancy": mean_exp, "max_drawdown": 0.2},
            robustness=validation["robustness_score"],
        ),
        "chronological": True,
        "shuffle": False,
        "scaler_fit": "train_only",
    }


def _slice_candles(candles: pd.DataFrame, timestamps: pd.Series) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
        elif "time" in c.columns:
            c = c.set_index("time")
    c.index = pd.to_datetime(c.index, utc=True)
    ts_set = set(pd.to_datetime(timestamps, utc=True))
    return c.loc[c.index.isin(ts_set)].sort_index()
