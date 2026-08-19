"""Phase 13.8 — trend rule variants (A–E)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

# Variant A mirrors Phase 13.3 rules (read-only reference logic, not modifying 13.3 files).
ADX_MIN_A = 25.0
HH_MIN = 2
LL_MIN = 2


def _hh_structure(row: pd.Series) -> bool:
    return int(row.get("higher_high_count", 0)) >= HH_MIN or int(row.get("higher_high_count", 0)) > int(
        row.get("lower_low_count", 0)
    )


def _ll_structure(row: pd.Series) -> bool:
    return int(row.get("lower_low_count", 0)) >= LL_MIN or int(row.get("lower_low_count", 0)) > int(
        row.get("higher_high_count", 0)
    )


def evaluate_variant_a(row: pd.Series, *, regime: str) -> str:
    if regime != "TREND":
        return "HOLD"
    ema20 = float(row.get("ema20", 0))
    ema50 = float(row.get("ema50", 0))
    ema50_slope = float(row.get("ema50_slope", 0))
    adx = float(row.get("adx", 0))
    if adx <= ADX_MIN_A:
        return "HOLD"
    if ema20 > ema50 and ema50_slope > 0 and _hh_structure(row):
        return "BUY"
    if ema20 < ema50 and ema50_slope < 0 and _ll_structure(row):
        return "SELL"
    return "HOLD"


def evaluate_variant_b(row: pd.Series, *, regime: str) -> str:
    """Relaxed trend: ADX 20, weaker slope."""
    if regime != "TREND":
        return "HOLD"
    ema20 = float(row.get("ema20", 0))
    ema50 = float(row.get("ema50", 0))
    ema50_slope = float(row.get("ema50_slope", 0))
    adx = float(row.get("adx", 0))
    if adx <= 20.0:
        return "HOLD"
    if ema20 > ema50 and ema50_slope > -0.05 and int(row.get("higher_high_count", 0)) >= 1:
        return "BUY"
    if ema20 < ema50 and ema50_slope < 0.05 and int(row.get("lower_low_count", 0)) >= 1:
        return "SELL"
    return "HOLD"


def evaluate_variant_c(row: pd.Series, *, regime: str) -> str:
    """Momentum trend: EMA20>EMA50 + positive momentum + ADX."""
    if regime != "TREND":
        return "HOLD"
    adx = float(row.get("adx", 0))
    if adx <= 22.0:
        return "HOLD"
    mom = float(row.get("candle_momentum", 0))
    ema20 = float(row.get("ema20", 0))
    ema50 = float(row.get("ema50", 0))
    if ema20 > ema50 and mom > 0.1:
        return "BUY"
    if ema20 < ema50 and mom < -0.1:
        return "SELL"
    return "HOLD"


def evaluate_variant_d(row: pd.Series, *, regime: str) -> str:
    """Breakout trend: structure + ATR expansion + breakout distance."""
    if regime != "TREND":
        return "HOLD"
    adx = float(row.get("adx", 0))
    atr_pct = float(row.get("atr_percentile", 0))
    breakout = float(row.get("breakout_distance", 0))
    if adx <= 20.0 or atr_pct < 40.0:
        return "HOLD"
    if breakout > 0.5 and _hh_structure(row):
        return "BUY"
    if breakout < -0.5 and _ll_structure(row):
        return "SELL"
    return "HOLD"


def evaluate_variant_e(row: pd.Series, *, regime: str) -> str:
    """Hybrid: EMA alignment + ADX + momentum + structure."""
    if regime != "TREND":
        return "HOLD"
    adx = float(row.get("adx", 0))
    if adx <= 22.0:
        return "HOLD"
    align = float(row.get("ema_alignment", 0))
    mom = float(row.get("candle_momentum", 0))
    ema20 = float(row.get("ema20", 0))
    ema50 = float(row.get("ema50", 0))
    if ema20 > ema50 and align > 0 and mom > 0 and _hh_structure(row):
        return "BUY"
    if ema20 < ema50 and align < 0 and mom < 0 and _ll_structure(row):
        return "SELL"
    return "HOLD"


VARIANTS: dict[str, tuple[str, Callable[..., str]]] = {
    "variant_a": ("Phase13.3 Original", evaluate_variant_a),
    "variant_b": ("Relaxed Trend", evaluate_variant_b),
    "variant_c": ("Momentum Trend", evaluate_variant_c),
    "variant_d": ("Breakout Trend", evaluate_variant_d),
    "variant_e": ("Hybrid Trend", evaluate_variant_e),
}
