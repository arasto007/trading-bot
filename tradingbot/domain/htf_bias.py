"""تعیین bias تایم‌فریم بالاتر برای فیلتر entry."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.price_action import Trend, enrich_price_action, find_swings, infer_trend


def trend_to_bias(trend: Trend) -> int:
    if trend == Trend.BULL:
        return 1
    if trend == Trend.BEAR:
        return -1
    return 0


def compute_htf_bias(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> int:
    """از ساختار همان TF (معمولاً H1) bias برمی‌گرداند: 1 bull, -1 bear, 0 range."""
    if df is None or df.empty or len(df) < 60:
        return 0
    pa_cfg = cfg or {}
    enriched = enrich_price_action(df, pa_cfg, at_index=len(df) - 1)
    swings = enriched.attrs.get("pa_swings") or find_swings(enriched)
    return trend_to_bias(infer_trend(swings))


def htf_timeframe_for(entry_tf: str) -> str:
    tf = entry_tf.upper().replace("M", "M").strip()
    mapping = {
        "M5": "H4",
        "5M": "H4",
        "5m": "H4",
        "M15": "H4",
        "15M": "H4",
        "15m": "H4",
        "H1": "H4",
        "1H": "H4",
        "1h": "H4",
        "H4": "D1",
        "4H": "D1",
        "4h": "D1",
    }
    return mapping.get(entry_tf, mapping.get(tf, "H4"))
