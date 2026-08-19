"""Phase 13.3 — trend entry rules (TREND regime only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

ADX_MIN = 25.0
HH_MIN = 2
LL_MIN = 2


def _higher_high_structure(row: pd.Series) -> bool:
    return int(row.get("higher_high_count", 0)) >= HH_MIN or int(row.get("higher_high_count", 0)) > int(
        row.get("lower_low_count", 0)
    )


def _lower_low_structure(row: pd.Series) -> bool:
    return int(row.get("lower_low_count", 0)) >= LL_MIN or int(row.get("lower_low_count", 0)) > int(
        row.get("higher_high_count", 0)
    )


def evaluate_trend_rules(row: pd.Series, *, regime: str) -> str:
    """Return BUY, SELL, or HOLD. Only active when regime == TREND."""
    if regime != "TREND":
        return "HOLD"

    ema20 = float(row.get("ema20", 0))
    ema50 = float(row.get("ema50", 0))
    ema50_slope = float(row.get("ema50_slope", 0))
    adx = float(row.get("adx", 0))

    if adx <= ADX_MIN:
        return "HOLD"

    if ema20 > ema50 and ema50_slope > 0 and _higher_high_structure(row):
        return "BUY"
    if ema20 < ema50 and ema50_slope < 0 and _lower_low_structure(row):
        return "SELL"
    return "HOLD"


def scan_signals(frame: pd.DataFrame, regimes: pd.Series) -> list[dict[str, Any]]:
    """Scan chronological bars; regimes aligned to frame index."""
    signals: list[dict[str, Any]] = []
    for i, row in frame.iterrows():
        regime = str(regimes.iloc[i]) if i < len(regimes) else "RANGE"
        direction = evaluate_trend_rules(row, regime=regime)
        if direction != "HOLD":
            signals.append({"index": int(i), "direction": direction, "regime": regime})
    return signals
