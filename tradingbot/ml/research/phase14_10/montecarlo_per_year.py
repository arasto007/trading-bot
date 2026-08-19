"""Phase 14.10 — Monte Carlo per calendar year."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_8.monte_carlo_extended import run_monte_carlo_extended
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import MIN_YEAR_BARS, MONTE_CARLO_SIMS_PER_YEAR, WF_YEARS, slice_year


def run_montecarlo_per_year(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method,
    *,
    confidence_threshold: float,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    simulations: int = MONTE_CARLO_SIMS_PER_YEAR,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    years = years or WF_YEARS
    per_year: dict[str, Any] = {}

    for year in years:
        test_c, test_ds = slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        records = run_adaptive_router_pipeline(
            test_c, test_ds, calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        year_seed = seed + year
        mc = run_monte_carlo_extended(records, simulations=simulations, seed=year_seed)
        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "simulations": simulations,
            "seed": year_seed,
            "trade_count": mc.get("trade_count", 0),
            "profitable_pct": mc.get("profitable_pct", 0.0),
            "passes_gate": mc.get("passes_gate", False),
            "pf_distribution": mc.get("pf_distribution", {}),
        }

    passing = sum(1 for v in per_year.values() if not v.get("skipped") and v.get("passes_gate"))
    active = sum(1 for v in per_year.values() if not v.get("skipped"))

    return {
        "phase": "14.10",
        "per_year": per_year,
        "years_passing_mc": passing,
        "active_years": active,
        "simulations_per_year": simulations,
    }
