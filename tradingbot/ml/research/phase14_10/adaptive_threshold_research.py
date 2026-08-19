"""Phase 14.10 — adaptive threshold research (research only, not production)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import BASELINE_THRESHOLD, MIN_YEAR_BARS, WF_YEARS, slice_year


def _adaptive_threshold(trend_pct: float, range_pct: float) -> float:
    """Research rule: lower threshold when TREND dominates, higher when RANGE dominates."""
    if trend_pct >= 0.60:
        return 0.28
    if range_pct >= 0.40:
        return 0.35
    return BASELINE_THRESHOLD


def research_adaptive_threshold(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method,
    regime_distribution: dict[str, Any],
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    years = years or WF_YEARS
    per_year: dict[str, Any] = {}
    static_pfs: list[float] = []
    adaptive_pfs: list[float] = []

    for year in years:
        test_c, test_ds = slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        regime_info = regime_distribution.get("per_year", {}).get(str(year), {})
        trend_pct = float(regime_info.get("trend_pct", 0.0))
        range_pct = float(regime_info.get("range_pct", 0.0))
        adaptive_th = _adaptive_threshold(trend_pct, range_pct)

        static_records = run_adaptive_router_pipeline(
            test_c, test_ds, calibration_method,
            confidence_threshold=BASELINE_THRESHOLD,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        adaptive_records = run_adaptive_router_pipeline(
            test_c, test_ds, calibration_method,
            confidence_threshold=adaptive_th,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        static_m = analyze_performance(static_records, stride=stride)
        adaptive_m = analyze_performance(adaptive_records, stride=stride)
        static_pfs.append(float(static_m["profit_factor"]))
        adaptive_pfs.append(float(adaptive_m["profit_factor"]))

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "trend_pct": trend_pct,
            "range_pct": range_pct,
            "static_threshold": BASELINE_THRESHOLD,
            "adaptive_threshold": adaptive_th,
            "static_pf": static_m["profit_factor"],
            "adaptive_pf": adaptive_m["profit_factor"],
            "static_trades": static_m["trades"],
            "adaptive_trades": adaptive_m["trades"],
            "pf_delta": round(float(adaptive_m["profit_factor"]) - float(static_m["profit_factor"]), 4),
        }

    return {
        "phase": "14.10",
        "research_only": True,
        "rule": "IF trend_pct >= 60% THEN threshold=0.28 ELIF range_pct >= 40% THEN 0.35 ELSE 0.30",
        "per_year": per_year,
        "static_mean_pf": round(sum(static_pfs) / len(static_pfs), 4) if static_pfs else 0.0,
        "adaptive_mean_pf": round(sum(adaptive_pfs) / len(adaptive_pfs), 4) if adaptive_pfs else 0.0,
        "improves_stability": len(adaptive_pfs) > 1 and _robustness(adaptive_pfs) > _robustness(static_pfs),
    }


def _robustness(pfs: list[float]) -> float:
    import numpy as np

    if len(pfs) <= 1:
        return 0.5
    return round(max(0.0, 1.0 - float(np.std(pfs))), 4)
