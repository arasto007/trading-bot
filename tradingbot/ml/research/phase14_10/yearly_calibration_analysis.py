"""Phase 14.10 — yearly calibration stability (Platt read-only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import MIN_YEAR_BARS, WF_YEARS, slice_year


def _calibration_bias(raw_vals: list[float], cal_vals: list[float], outcomes: list[float]) -> dict[str, float]:
    if not raw_vals or not cal_vals:
        return {"bias": 0.0, "mean_raw": 0.0, "mean_calibrated": 0.0, "win_rate": 0.0}
    wins = [1.0 if o > 0 else 0.0 for o in outcomes]
    mean_cal = float(np.mean(cal_vals))
    win_rate = float(np.mean(wins)) if wins else 0.0
    bias = round(mean_cal - win_rate, 4)
    label = "overconfident" if bias > 0.05 else ("underconfident" if bias < -0.05 else "stable")
    return {
        "bias": bias,
        "mean_raw": round(float(np.mean(raw_vals)), 4),
        "mean_calibrated": round(mean_cal, 4),
        "win_rate": round(win_rate, 4),
        "calibration_label": label,
    }


def analyze_calibration_stability(
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
        signal_recs = [
            r for r in records
            if r.get("raw_signal") in ("BUY", "SELL")
        ]
        raw_vals = [float(r["raw_confidence"]) for r in signal_recs]
        cal_vals = [float(r["calibrated_confidence"]) for r in signal_recs]
        outcomes = [float(r["r_multiple"]) for r in signal_recs]

        accepted = [r for r in records if r.get("allowed")]
        acc_bias = _calibration_bias(
            [float(r["raw_confidence"]) for r in accepted],
            [float(r["confidence"]) for r in accepted],
            [float(r["r_multiple"]) for r in accepted],
        )

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "all_signals": _calibration_bias(raw_vals, cal_vals, outcomes),
            "accepted_trades": acc_bias,
            "compression_ratio": round(
                float(np.mean(cal_vals)) / float(np.mean(raw_vals)), 4
            ) if raw_vals and np.mean(raw_vals) > 0 else 0.0,
        }

    labels = [
        v.get("accepted_trades", {}).get("calibration_label", "stable")
        for v in per_year.values()
        if not v.get("skipped")
    ]
    unstable = len(set(labels)) > 1 or any(l != "stable" for l in labels)

    return {
        "phase": "14.10",
        "per_year": per_year,
        "platt_global_fit": True,
        "yearly_calibration_unstable": unstable,
        "label_distribution": {l: labels.count(l) for l in set(labels)},
        "interpretation": (
            "Global Platt fit shows year-varying bias — yearly recalibration may improve WF stability."
            if unstable
            else "Platt scaling appears stable across years."
        ),
    }
