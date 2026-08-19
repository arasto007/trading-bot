"""Phase 13.6 — losing trade root-cause analysis."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase11_5.session_optimizer import SESSION_WINDOWS

FAILURE_CATEGORIES: tuple[str, ...] = (
    "wrong_regime_classification",
    "trend_fake_breakout",
    "range_breakout_failure",
    "high_volatility_entry",
    "low_confidence_trades",
    "bad_session",
)


def _session_key(ts: str) -> str:
    hour = pd.Timestamp(ts).hour
    for name, (start, end) in SESSION_WINDOWS.items():
        if start <= hour < end:
            return name
    return "off_hours"


def analyze_failures(trades: list[dict[str, Any]], *, session_pf: dict[str, float] | None = None) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") == "trade"]
    losers = [t for t in executed if float(t.get("pnl", 0)) < 0]
    session_pf = session_pf or {}
    categorized: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for trade in losers:
        regime = str(trade.get("regime", ""))
        adx = float(trade.get("adx", 0.0))
        atr_pct = float(trade.get("atr_percentile", 50.0))
        confidence = float(trade.get("confidence", 0.0))
        duration = int(trade.get("duration_bars", 99))
        session = _session_key(str(trade.get("timestamp", "")))
        reasons: list[str] = []

        if regime == "RANGE" and adx > 28:
            reasons.append("wrong_regime_classification")
        if regime == "TREND" and adx < 22:
            reasons.append("wrong_regime_classification")
        if regime == "TREND" and duration <= 3:
            reasons.append("trend_fake_breakout")
        if regime == "RANGE" and trade.get("result") == "SL":
            reasons.append("range_breakout_failure")
        if regime == "HIGH_VOLATILITY":
            reasons.append("high_volatility_entry")
        if confidence < 0.35:
            reasons.append("low_confidence_trades")
        if session_pf.get(session, 1.0) < 0.9:
            reasons.append("bad_session")
        if not reasons:
            reasons.append("range_breakout_failure")

        primary = reasons[0]
        counts[primary] += 1
        categorized.append({**trade, "failure_categories": reasons, "primary_failure": primary})

    total_loss = sum(float(t.get("pnl", 0)) for t in losers)
    return {
        "losing_trades": len(losers),
        "total_executed": len(executed),
        "loss_rate": round(len(losers) / len(executed), 4) if executed else 0.0,
        "total_loss_pnl": round(total_loss, 4),
        "category_counts": dict(counts),
        "categories": list(FAILURE_CATEGORIES),
        "samples": categorized[:50],
        "top_driver": counts.most_common(1)[0][0] if counts else None,
    }
