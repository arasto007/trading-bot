"""Phase 14.9 — regime performance audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_9.config import RANGE_ENGINE_ID, TREND_ENGINE_ID

REGIMES = ("RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE")


def audit_regime_performance(records: list[dict[str, Any]]) -> dict[str, Any]:
    per_regime: dict[str, Any] = {}
    per_engine: dict[str, Any] = {}
    total_accepted = sum(1 for r in records if r.get("allowed"))

    for regime in REGIMES:
        subset = [r for r in records if str(r.get("regime")) == regime]
        accepted = [r for r in subset if r.get("allowed")]
        m = trade_metrics_from_records(accepted)
        per_regime[regime] = {
            **m,
            "bars": len(subset),
            "contribution_pct": round(m["trades"] / total_accepted, 4) if total_accepted else 0.0,
        }

    for engine in ("phase9_9", "trend_rf_v40"):
        subset = [r for r in records if r.get("allowed") and str(r.get("engine")) == engine]
        m = trade_metrics_from_records(subset)
        per_engine[engine] = {**m, "contribution_pct": round(m["trades"] / total_accepted, 4) if total_accepted else 0.0}

    dominant = max(per_regime.items(), key=lambda x: x[1]["contribution_pct"], default=(None, {"contribution_pct": 0}))
    dominance_pct = float(dominant[1]["contribution_pct"]) if dominant[0] else 0.0

    return {
        "phase": "14.9",
        "per_regime": per_regime,
        "per_engine": per_engine,
        "total_accepted": total_accepted,
        "regime_dominance": {
            "dominant_regime": dominant[0],
            "dominance_pct": dominance_pct,
            "collapse_risk": dominance_pct >= 0.92,
        },
    }
