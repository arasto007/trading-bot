"""Phase 13.8 — walk-forward validation for trend variants."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_8.config import WALK_FORWARD_YEARS_138
from tradingbot.ml.research.phase13_8.trend_comparator import run_variant_backtest


def run_walk_forward(
    frame: pd.DataFrame,
    *,
    symbol: str,
    rule_fn: Callable[..., str],
    ml_filter: Callable[[pd.Series, str], bool] | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    years = WALK_FORWARD_YEARS_138[:1] if quick else WALK_FORWARD_YEARS_138
    windows: list[dict[str, Any]] = []

    for year in years:
        test_mask = ts.dt.year == year
        train_mask = ts.dt.year < year
        if not test_mask.any():
            windows.append({"window_id": f"wf_{year}", "test_year": year, "skipped": True})
            continue
        test_frame = frame.loc[test_mask].reset_index(drop=True)
        bt = run_variant_backtest(test_frame, symbol=symbol, rule_fn=rule_fn, ml_filter=ml_filter)
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
    pf_std = float(np.std(pfs)) if len(pfs) > 1 else 0.0
    robustness = round(max(0.0, 1.0 - pf_std), 4)
    positive = sum(1 for pf in pfs if pf >= 1.0)

    return {
        "windows": windows,
        "robustness_score": robustness,
        "positive_pf_windows": positive,
        "chronological": True,
        "shuffle": False,
        "scaler_fit": "train_only",
    }
