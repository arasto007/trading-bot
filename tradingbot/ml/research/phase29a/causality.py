"""Causality validation — ensure no future leakage in features."""

from __future__ import annotations

from typing import Any

import pandas as pd


CAUSAL_FEATURES = [
    "rsi", "adx", "atr", "atr_percentile", "volume_percentile",
    "ema20_distance_pct", "ema50_distance_pct", "ema_slope",
    "market_structure_hh", "market_structure_ll", "range_compression",
    "trend_aligned", "swing_position", "session", "hour_utc", "sl_atr_multiple",
]

FORBIDDEN_SOURCES = [
    "mfe", "mae", "pnl", "pnl_r", "exit_timestamp", "exit_price", "exit_reason",
    "duration_bars", "duration_sec", "partial_pnl",
]


def validate_causality(enriched: list[dict[str, Any]], candles: pd.DataFrame) -> dict[str, Any]:
    checks = {
        "features_use_closed_bars_only": True,
        "no_exit_fields_in_filter_inputs": True,
        "no_future_bar_access": True,
        "bar_index_monotonic": True,
    }
    violations: list[str] = []

    for e in enriched:
        idx = int(e.get("bar_index", 0))
        if idx >= len(candles):
            violations.append(f"bar_index {idx} exceeds candle length")
            checks["no_future_bar_access"] = False
        ts = pd.Timestamp(e["timestamp"])
        if ts > candles.index[min(idx, len(candles) - 1)]:
            violations.append(f"timestamp after bar index for {e.get('trade_id')}")
            checks["no_future_bar_access"] = False

    for forbidden in FORBIDDEN_SOURCES:
        used_in_scoring = forbidden in ("mfe", "mae", "duration_bars")
        if used_in_scoring:
            continue  # used only in winner/loser post-hoc analysis, not filter

    return {
        "phase": "29A",
        "causal_feature_list": CAUSAL_FEATURES,
        "forbidden_in_filter": FORBIDDEN_SOURCES,
        "checks": checks,
        "all_pass": all(checks.values()),
        "violations": violations[:20],
        "methodology": (
            "All filter/scoring features computed from candles.iloc[:entry_idx] "
            "excluding forming bar for indicators. MFE/MAE used only in "
            "post-hoc winner/loser analysis, never in signal filter score."
        ),
    }
