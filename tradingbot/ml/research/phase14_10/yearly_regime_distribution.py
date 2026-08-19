"""Phase 14.10 — yearly regime distribution."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_10.config import REGIMES, WF_YEARS, slice_year


def analyze_regime_distribution(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    years = years or WF_YEARS
    unified = build_unified_frame(candles, dataset)
    per_year: dict[str, Any] = {}

    for year in years:
        test_c, test_ds = slice_year(candles, dataset, year)
        if test_c.empty:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        u = unified.copy()
        u["timestamp"] = pd.to_datetime(u["timestamp"], utc=True)
        u = u[u["timestamp"].dt.year == year]
        if u.empty or "regime" not in u.columns:
            per_year[str(year)] = {"year": year, "skipped": True}
            continue

        counts = u["regime"].value_counts()
        total = int(counts.sum()) or 1
        dist = {r: round(float(counts.get(r, 0)) / total, 4) for r in REGIMES}
        dominant = max(dist.items(), key=lambda x: x[1])

        per_year[str(year)] = {
            "year": year,
            "skipped": False,
            "bars": total,
            "distribution": dist,
            "dominant_regime": dominant[0],
            "dominant_pct": dominant[1],
            "trend_pct": dist.get("TREND", 0.0),
            "range_pct": dist.get("RANGE", 0.0),
            "high_vol_pct": dist.get("HIGH_VOLATILITY", 0.0),
            "no_trade_pct": dist.get("NO_TRADE", 0.0),
        }

    active = [v for v in per_year.values() if not v.get("skipped")]
    trend_shift = 0.0
    if len(active) >= 2:
        first = active[0]["trend_pct"]
        last = active[-1]["trend_pct"]
        trend_shift = round(last - first, 4)

    return {
        "phase": "14.10",
        "per_year": per_year,
        "regime_shift_summary": {
            "trend_pct_delta_first_to_last": trend_shift,
            "interpretation": "Rising TREND share may explain threshold sensitivity across years.",
        },
    }
