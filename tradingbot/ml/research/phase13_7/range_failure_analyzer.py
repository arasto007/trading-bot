"""Phase 13.7 — Phase 9.9 RANGE trade failure analysis."""

from __future__ import annotations

from typing import Any

RANGE_FAILURE_CATEGORIES = (
    "breakout_failure",
    "false_range",
    "volatility_expansion",
    "bad_session",
    "low_confidence",
)


def _session_bucket(ts_str: str) -> str:
    try:
        hour = pd_timestamp_hour(ts_str)
    except Exception:
        return "unknown"
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 13:
        return "london"
    if 13 <= hour < 22:
        return "new_york"
    return "asia"


def pd_timestamp_hour(ts_str: str) -> int:
    import pandas as pd

    return pd.Timestamp(ts_str).hour


def classify_range_failure(trade: dict[str, Any]) -> list[str]:
    cats: list[str] = []
    if trade.get("result") not in ("SL", "TIMEOUT"):
        return cats
    if trade.get("regime") != "RANGE":
        return cats

    conf = float(trade.get("confidence", 0.0))
    atr_pct = float(trade.get("atr_percentile", 50.0))
    adx = float(trade.get("adx", 0.0))

    if conf < 0.25:
        cats.append("low_confidence")
    if atr_pct >= 70:
        cats.append("volatility_expansion")
    if adx >= 22:
        cats.append("false_range")
    if _session_bucket(str(trade.get("timestamp", ""))) in ("asia",):
        cats.append("bad_session")
    if not cats:
        cats.append("breakout_failure")
    return cats


def analyze_range_failures(trades: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") == "trade"]
    range_trades = [t for t in executed if t.get("regime") == "RANGE"]
    losers = [t for t in range_trades if float(t.get("pnl", 0.0)) < 0]

    category_counts: dict[str, int] = {c: 0 for c in RANGE_FAILURE_CATEGORIES}
    samples: list[dict[str, Any]] = []

    for trade in losers:
        cats = classify_range_failure(trade)
        for c in cats:
            category_counts[c] = category_counts.get(c, 0) + 1
        samples.append({**trade, "failure_categories": cats, "primary_failure": cats[0] if cats else "breakout_failure"})

    top = max(category_counts, key=category_counts.get) if category_counts else "breakout_failure"

    return {
        "phase": "13.7",
        "range_trades_total": len(range_trades),
        "range_losers": len(losers),
        "categories": list(RANGE_FAILURE_CATEGORIES),
        "category_counts": category_counts,
        "top_driver": top,
        "samples": samples[:50],
    }
