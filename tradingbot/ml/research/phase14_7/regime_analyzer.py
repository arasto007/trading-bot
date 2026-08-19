"""Phase 14.7 — regime-level breakdown."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.config import REGIMES


def analyze_regimes(records: list[dict[str, Any]]) -> dict[str, Any]:
    per_regime: dict[str, Any] = {}
    total_accepted = sum(1 for r in records if r.get("allowed"))

    for regime in REGIMES:
        subset = [r for r in records if str(r.get("regime")) == regime]
        accepted = [r for r in subset if r.get("allowed")]
        metrics = trade_metrics_from_records(accepted)
        per_regime[regime] = {
            "bars": len(subset),
            "trades": metrics["trades"],
            "profit_factor": metrics["profit_factor"],
            "expectancy": metrics["expectancy"],
            "contribution_pct": round(metrics["trades"] / total_accepted, 4) if total_accepted else 0.0,
        }

    return {"phase": "14.7", "regimes": per_regime, "total_accepted": total_accepted}


def detect_regime_collapse(regime_results: dict[str, Any], *, max_dominance: float) -> dict[str, Any]:
    total = int(regime_results.get("total_accepted", 0))
    if total == 0:
        return {"collapsed": True, "dominant_regime": None, "dominance_pct": 0.0}
    dominant = None
    top_pct = 0.0
    for regime, data in regime_results.get("regimes", {}).items():
        pct = float(data.get("contribution_pct", 0))
        if pct > top_pct:
            top_pct = pct
            dominant = regime
    collapsed = top_pct >= max_dominance and dominant not in (None, "RANGE", "TREND")
    unrealistic = top_pct >= max_dominance and dominant in ("HIGH_VOLATILITY", "NO_TRADE")
    return {
        "collapsed": collapsed or unrealistic,
        "dominant_regime": dominant,
        "dominance_pct": round(top_pct, 4),
        "unrealistic_dominance": unrealistic,
    }
