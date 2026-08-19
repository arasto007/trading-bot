"""Phase 14.10 — regime transition P&L analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import MIN_YEAR_BARS, WF_YEARS, slice_year

TRANSITIONS = (
    ("TREND", "RANGE"),
    ("RANGE", "TREND"),
    ("TREND", "HIGH_VOLATILITY"),
    ("HIGH_VOLATILITY", "TREND"),
    ("RANGE", "HIGH_VOLATILITY"),
    ("HIGH_VOLATILITY", "RANGE"),
)


def _transition_tags(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    prev_regime: str | None = None
    for rec in records:
        regime = str(rec.get("regime", "NO_TRADE"))
        transition = None
        if prev_regime is not None and prev_regime != regime:
            transition = f"{prev_regime}->{regime}"
        tagged.append({**rec, "transition": transition})
        prev_regime = regime
    return tagged


def analyze_regime_transitions(
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
    global_by_transition: dict[str, list[dict[str, Any]]] = {f"{a}->{b}": [] for a, b in TRANSITIONS}
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
        tagged = _transition_tags(records)
        year_trans: dict[str, Any] = {}

        for a, b in TRANSITIONS:
            key = f"{a}->{b}"
            subset = [
                r for r in tagged
                if r.get("transition") == key and r.get("allowed")
            ]
            m = trade_metrics_from_records(subset)
            year_trans[key] = {**m, "bars_at_transition": len(subset)}
            global_by_transition[key].extend(subset)

        per_year[str(year)] = {"year": year, "skipped": False, "transitions": year_trans}

    aggregate: dict[str, Any] = {}
    for key, recs in global_by_transition.items():
        m = trade_metrics_from_records(recs)
        aggregate[key] = {**m, "trade_count": len(recs)}

    losing = sorted(
        [(k, v) for k, v in aggregate.items() if v.get("expectancy", 0) < 0 and v.get("trade_count", 0) > 0],
        key=lambda x: x[1]["expectancy"],
    )
    worst = losing[0] if losing else None

    return {
        "phase": "14.10",
        "per_year": per_year,
        "aggregate_transitions": aggregate,
        "worst_transition": {"name": worst[0], "metrics": worst[1]} if worst else None,
        "losing_transitions": [{"transition": k, "expectancy": v["expectancy"]} for k, v in losing],
    }
