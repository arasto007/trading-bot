"""Phase 14.4 — risk cap acceptance analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.config import RISK_CAP_GRID
from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records


def analyze_risk_acceptance(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze how many signals would pass at each risk cap."""
    signal_rows = [r for r in records if r["raw_signal"] in ("BUY", "SELL")]
    caps: list[dict[str, Any]] = []

    for cap in RISK_CAP_GRID:
        filtered = [
            r
            for r in signal_rows
            if r["risk_percent"] > 0
            and r["risk_percent"] <= cap
            and r["confidence"] >= 0.55
        ]
        subset_records = [{**r, "allowed": True} for r in filtered]
        metrics = trade_metrics_from_records(subset_records)
        caps.append(
            {
                "max_risk_percent": cap,
                "eligible_signals": len(filtered),
                **metrics,
            }
        )

    return {
        "phase": "14.4",
        "risk_cap_analysis": caps,
        "current_cap": 0.50,
    }
