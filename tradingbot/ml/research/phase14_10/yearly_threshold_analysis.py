"""Phase 14.10 — per-year threshold sweep (no global optimization)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import MIN_YEAR_BARS, THRESHOLD_GRID, WF_YEARS, slice_year


def analyze_yearly_thresholds(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    thresholds: tuple[float, ...] | None = None,
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or THRESHOLD_GRID
    years = years or WF_YEARS
    per_year: dict[str, Any] = {}

    for year in years:
        test_c, test_ds = slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        threshold_results: dict[str, Any] = {}
        for th in thresholds:
            records = run_adaptive_router_pipeline(
                test_c,
                test_ds,
                calibration_method,
                confidence_threshold=th,
                symbol=symbol,
                timeframe=timeframe,
                seed=seed,
                stride=stride,
                range_engine=range_engine,
                trend_engine=trend_engine,
                unified=unified,
            )
            m = analyze_performance(records, stride=stride)
            threshold_results[str(th)] = {
                "threshold": th,
                "profit_factor": m.get("profit_factor", 0.0),
                "expectancy": m.get("expectancy", 0.0),
                "trades": m.get("trades", 0),
                "effective_trades_est": m.get("effective_trades_est", 0),
                "win_rate": m.get("win_rate", 0.0),
                "avg_confidence": m.get("avg_confidence", 0.0),
            }

        best = max(threshold_results.values(), key=lambda x: x["profit_factor"])
        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "thresholds": threshold_results,
            "best_threshold_by_pf": best["threshold"],
            "best_pf": best["profit_factor"],
            "threshold_spread_pf": round(
                max(v["profit_factor"] for v in threshold_results.values())
                - min(v["profit_factor"] for v in threshold_results.values()),
                4,
            ),
        }

    active = [v for v in per_year.values() if not v.get("skipped")]
    optimal_per_year = {str(v["year"]): v["best_threshold_by_pf"] for v in active}
    spread_values = [v["threshold_spread_pf"] for v in active]

    return {
        "phase": "14.10",
        "per_year": per_year,
        "threshold_grid": list(thresholds),
        "optimal_threshold_per_year": optimal_per_year,
        "mean_threshold_spread_pf": round(sum(spread_values) / len(spread_values), 4) if spread_values else 0.0,
        "note": "Per-year optima differ — global static threshold is a stability risk.",
    }
