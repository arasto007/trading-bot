"""Phase 19B — winning trade analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def _mean(trades: list[dict], key: str) -> float:
    vals = [float(t.get(key, 0) or 0) for t in trades]
    return round(float(np.mean(vals)), 6) if vals else 0.0


def analyze_winners(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [t for t in trades if t.get("is_win")]
    losses = [t for t in trades if t.get("is_loss")]

    features = (
        "adx", "atr", "rsi", "spread", "confidence", "quality_score",
        "risk_percent", "duration_bars", "trend_age", "sl_distance",
        "hour", "weekday",
    )
    predictors = []
    for f in features:
        mw = _mean(wins, f)
        ml = _mean(losses, f)
        delta = mw - ml
        predictors.append({
            "feature": f,
            "winner_mean": mw,
            "loser_mean": ml,
            "delta": round(delta, 6),
            "abs_delta": round(abs(delta), 6),
        })
    predictors.sort(key=lambda x: -x["abs_delta"])

    regime_wins = {}
    for t in wins:
        r = str(t.get("regime"))
        regime_wins[r] = regime_wins.get(r, 0) + 1

    session_wins = {}
    for t in wins:
        s = str(t.get("session"))
        session_wins[s] = session_wins.get(s, 0) + 1

    return {
        "phase": "19B",
        "winning_trades": len(wins),
        "mean_win_r": round(float(np.mean([t["r_multiple"] for t in wins])), 4) if wins else 0.0,
        "common_characteristics": {
            "mean_confidence": _mean(wins, "confidence"),
            "mean_quality": _mean(wins, "quality_score"),
            "mean_adx": _mean(wins, "adx"),
            "mean_atr": _mean(wins, "atr"),
            "mean_duration": _mean(wins, "duration_bars"),
            "regime_counts": regime_wins,
            "session_counts": session_wins,
        },
        "ranked_predictors": predictors,
        "top_predictors": predictors[:8],
    }
