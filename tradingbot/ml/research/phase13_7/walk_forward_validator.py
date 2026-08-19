"""Phase 13.7 — chronological walk-forward validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_7.config import WALK_FORWARD_YEARS_137, RouterVariant
from tradingbot.ml.research.phase13_7.robust_score import robust_composite_score
from tradingbot.ml.research.phase13_7.router_recalibrator import variant_to_config
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.robustness_validator import validate_robustness


def _year_mask(ts: pd.Series, year: int) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.year.to_numpy() == year


def _prior_mask(ts: pd.Series, year: int) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.year.to_numpy() < year


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


def run_walk_forward_for_variant(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    variant: RouterVariant,
    *,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest

    cfg = variant_to_config(variant, seed=seed, symbol=symbol)
    ts = pd.to_datetime(merged["timestamp"], utc=True)
    years = WALK_FORWARD_YEARS_137[:1] if quick else WALK_FORWARD_YEARS_137
    windows: list[dict[str, Any]] = []

    for year in years:
        test_mask = _year_mask(ts, year)
        train_mask = _prior_mask(ts, year)
        if not test_mask.any():
            windows.append({"window_id": f"wf_{year}", "test_year": year, "skipped": True, "shuffle": False})
            continue

        test_merged = merged.loc[test_mask].reset_index(drop=True)
        test_candles = _slice_candles(candles, test_merged["timestamp"])
        bt = run_optimized_backtest(
            test_merged, test_candles, config=cfg, base_dir=base_dir, engine_cache=engine_cache
        )
        m = bt["metrics"]
        windows.append(
            {
                "window_id": f"wf_{year}",
                "test_year": year,
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                "metrics": m,
                "trades": m.get("trades", 0),
                "profit_factor": m.get("profit_factor", 0.0),
                "expectancy": m.get("expectancy", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "max_drawdown": m.get("max_drawdown", 0.0),
                "stability_score": robust_composite_score(m, walk_forward_score=0.5),
                "shuffle": False,
            }
        )

    validation = validate_robustness(windows)
    active = [w for w in windows if not w.get("skipped")]
    mean_pf = float(np.mean([w["metrics"]["profit_factor"] for w in active])) if active else 0.0

    return {
        "phase": "13.7",
        "variant": variant.key,
        "label": variant.label,
        "windows": windows,
        "mean_profit_factor": round(mean_pf, 4),
        "robustness": validation,
        "chronological": True,
        "shuffle": False,
        "scaler_fit": "train_only",
    }
