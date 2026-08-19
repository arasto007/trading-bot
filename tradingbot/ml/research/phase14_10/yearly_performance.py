"""Phase 14.10 — per-year performance metrics."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import MIN_YEAR_BARS, REGIMES, WF_YEARS, regime_pct_from_records, slice_year


def _engine_pct(records: list[dict[str, Any]]) -> dict[str, float]:
    accepted = [r for r in records if r.get("allowed")]
    total = len(accepted) or 1
    trend = sum(1 for r in accepted if str(r.get("engine")) == "trend_rf_v40")
    range_n = sum(1 for r in accepted if str(r.get("engine")) == "phase9_9")
    return {
        "trend_pct": round(trend / total, 4),
        "range_pct": round(range_n / total, 4),
    }


def compute_yearly_metrics(
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
            per_year[str(year)] = {"year": year, "skipped": True, "reason": "insufficient_bars"}
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
        m = analyze_performance(records, stride=stride)
        regime_pct = regime_pct_from_records(records)
        engine_pct = _engine_pct(records)

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "profit_factor": m.get("profit_factor", 0.0),
            "expectancy": m.get("expectancy", 0.0),
            "trades": m.get("trades", 0),
            "effective_trades_est": m.get("effective_trades_est", 0),
            "win_rate": m.get("win_rate", 0.0),
            "max_drawdown": m.get("max_drawdown", 0.0),
            "avg_confidence": m.get("avg_confidence", 0.0),
            "avg_quality_score": m.get("avg_quality_score", 0.0),
            "avg_risk_percent": m.get("avg_risk_percent", 0.0),
            "trend_pct": engine_pct["trend_pct"],
            "range_pct": engine_pct["range_pct"],
            "high_vol_pct": regime_pct.get("HIGH_VOLATILITY", 0.0),
            "no_trade_pct": regime_pct.get("NO_TRADE", 0.0),
            "regime_distribution": regime_pct,
            "block_reasons": m.get("block_reasons", {}),
            "records_count": len(records),
        }

    active = [v for v in per_year.values() if not v.get("skipped")]
    pfs = [float(v["profit_factor"]) for v in active]
    return {
        "phase": "14.10",
        "per_year": per_year,
        "active_years": len(active),
        "years": list(years),
        "regimes_tracked": list(REGIMES),
    }
