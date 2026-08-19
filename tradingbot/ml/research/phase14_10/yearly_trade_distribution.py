"""Phase 14.10 — yearly trade distribution."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import MIN_YEAR_BARS, WF_YEARS, slice_year


def analyze_trade_distribution(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method,
    *,
    confidence_threshold: float,
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

    for year in years:
        test_c, test_ds = slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        records = run_adaptive_router_pipeline(
            test_c,
            test_ds,
            calibration_method,
            confidence_threshold=confidence_threshold,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            stride=stride,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=unified,
        )
        accepted = [r for r in records if r.get("allowed")]
        by_engine: dict[str, Any] = {}
        for engine in ("trend_rf_v40", "phase9_9"):
            subset = [r for r in accepted if str(r.get("engine")) == engine]
            by_engine[engine] = trade_metrics_from_records(subset)

        by_regime: dict[str, Any] = {}
        for regime in ("TREND", "RANGE", "HIGH_VOLATILITY", "NO_TRADE"):
            subset = [r for r in accepted if str(r.get("regime")) == regime]
            by_regime[regime] = trade_metrics_from_records(subset)

        buy = sum(1 for r in accepted if r.get("raw_signal") == "BUY")
        sell = sum(1 for r in accepted if r.get("raw_signal") == "SELL")

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "total_accepted": len(accepted),
            "buy_pct": round(buy / len(accepted), 4) if accepted else 0.0,
            "sell_pct": round(sell / len(accepted), 4) if accepted else 0.0,
            "by_engine": by_engine,
            "by_regime": by_regime,
            "avg_confidence_accepted": round(
                sum(float(r["confidence"]) for r in accepted) / len(accepted), 4
            ) if accepted else 0.0,
        }

    return {"phase": "14.10", "per_year": per_year}
