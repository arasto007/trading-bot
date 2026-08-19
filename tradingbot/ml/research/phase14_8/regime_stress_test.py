"""Phase 14.8 — regime-level stress testing."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.config import REGIMES
from tradingbot.ml.research.phase14_7.regime_analyzer import detect_regime_collapse


def run_regime_stress_test(records: list[dict[str, Any]]) -> dict[str, Any]:
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

    collapse = detect_regime_collapse({"regimes": per_regime, "total_accepted": total_accepted}, max_dominance=0.90)
    return {
        "phase": "14.8",
        "regimes": per_regime,
        "total_accepted": total_accepted,
        "collapse_check": collapse,
        "fake_dominance": collapse.get("unrealistic_dominance", False),
    }
