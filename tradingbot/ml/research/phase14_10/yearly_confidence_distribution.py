"""Phase 14.10 — yearly confidence distribution."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import CONFIDENCE_HIST_BINS, MIN_YEAR_BARS, WF_YEARS, slice_year


def _histogram(values: list[float], bins: int = CONFIDENCE_HIST_BINS) -> dict[str, Any]:
    if not values:
        return {"bins": [], "counts": [], "edges": []}
    counts, edges = np.histogram(values, bins=bins, range=(0.0, 1.0))
    return {
        "bins": [round(float((edges[i] + edges[i + 1]) / 2), 3) for i in range(len(counts))],
        "counts": [int(c) for c in counts],
        "edges": [round(float(e), 3) for e in edges],
    }


def analyze_confidence_distribution(
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
        calibrated = [float(r["calibrated_confidence"]) for r in records if r.get("calibrated_confidence") is not None]
        raw = [float(r["raw_confidence"]) for r in records if r.get("raw_confidence") is not None]
        accepted_cal = [float(r["confidence"]) for r in records if r.get("allowed")]

        signals = [r for r in records if r.get("raw_signal") in ("BUY", "SELL")]
        accepted_n = sum(1 for r in signals if r.get("allowed"))
        rejected_n = len(signals) - accepted_n

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "mean_calibrated": round(float(np.mean(calibrated)), 4) if calibrated else 0.0,
            "median_calibrated": round(float(np.median(calibrated)), 4) if calibrated else 0.0,
            "std_calibrated": round(float(np.std(calibrated)), 4) if calibrated else 0.0,
            "mean_raw": round(float(np.mean(raw)), 4) if raw else 0.0,
            "mean_accepted": round(float(np.mean(accepted_cal)), 4) if accepted_cal else 0.0,
            "p50_calibrated": round(float(np.median(calibrated)), 4) if calibrated else 0.0,
            "histogram_calibrated": _histogram(calibrated),
            "histogram_raw": _histogram(raw),
            "histogram_accepted": _histogram(accepted_cal),
            "accepted_pct": round(accepted_n / len(signals), 4) if signals else 0.0,
            "rejected_pct": round(rejected_n / len(signals), 4) if signals else 0.0,
            "above_threshold_pct": round(
                sum(1 for v in calibrated if v >= confidence_threshold) / len(calibrated), 4
            ) if calibrated else 0.0,
        }

    active = [(k, v) for k, v in per_year.items() if not v.get("skipped")]
    year_comparison: dict[str, Any] = {}
    if len(active) >= 2:
        sorted_years = sorted(active, key=lambda x: int(x[0]))
        lowest = sorted_years[0]
        highest = sorted_years[-1]
        year_comparison = {
            "lowest_mean_year": int(lowest[0]),
            "lowest_mean_confidence": lowest[1]["mean_calibrated"],
            "highest_mean_year": int(highest[0]),
            "highest_mean_confidence": highest[1]["mean_calibrated"],
            "confidence_delta": round(highest[1]["mean_calibrated"] - lowest[1]["mean_calibrated"], 4),
        }

    return {
        "phase": "14.10",
        "per_year": per_year,
        "year_comparison": year_comparison,
        "confidence_threshold": confidence_threshold,
    }
