"""Phase 14.10 — adaptive regime-aware policy research (not production)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import BASELINE_THRESHOLD, MIN_YEAR_BARS, WF_YEARS, slice_year

REGIME_THRESHOLD_MAP = {
    "TREND": 0.28,
    "RANGE": 0.35,
    "HIGH_VOLATILITY": 0.50,
    "NO_TRADE": 0.55,
}


def _refilter_records(
    records: list[dict[str, Any]],
    threshold_fn: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        rec = dict(r)
        if rec.get("raw_signal") not in ("BUY", "SELL"):
            rec["allowed"] = False
            out.append(rec)
            continue
        conf = float(rec.get("confidence", 0))
        th = threshold_fn(rec)
        block = str(rec.get("block_reason") or "")
        non_conf_block = block in ("risk", "quality", "hold_action")
        rec["allowed"] = conf >= th and not non_conf_block
        rec["research_threshold"] = th
        out.append(rec)
    return out


def research_regime_policy(
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
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    years = years or WF_YEARS
    per_year: dict[str, Any] = {}
    static_pfs: list[float] = []
    policy_pfs: list[float] = []

    for year in years:
        test_c, test_ds = slice_year(candles, dataset, year)
        if test_c.empty or len(test_c) < MIN_YEAR_BARS:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        records = run_adaptive_router_pipeline(
            test_c, test_ds, calibration_method,
            confidence_threshold=0.25,
            symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
            range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        )
        static_records = _refilter_records(records, lambda _: BASELINE_THRESHOLD)
        policy_records = _refilter_records(
            records,
            lambda r: REGIME_THRESHOLD_MAP.get(str(r.get("regime", "NO_TRADE")), BASELINE_THRESHOLD),
        )
        static_m = analyze_performance(static_records, stride=stride)
        policy_m = analyze_performance(policy_records, stride=stride)
        static_pfs.append(float(static_m["profit_factor"]))
        policy_pfs.append(float(policy_m["profit_factor"]))

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "static_pf": static_m["profit_factor"],
            "regime_policy_pf": policy_m["profit_factor"],
            "static_trades": static_m["trades"],
            "regime_policy_trades": policy_m["trades"],
            "threshold_map": REGIME_THRESHOLD_MAP,
        }

    return {
        "phase": "14.10",
        "research_only": True,
        "policy": REGIME_THRESHOLD_MAP,
        "per_year": per_year,
        "static_mean_pf": round(sum(static_pfs) / len(static_pfs), 4) if static_pfs else 0.0,
        "policy_mean_pf": round(sum(policy_pfs) / len(policy_pfs), 4) if policy_pfs else 0.0,
        "recommendation": "Regime-aware confidence may reduce year-to-year PF variance without raising global PF target.",
    }
