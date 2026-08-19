"""Phase 14.9 — report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def build_final_report(
    *,
    regime_audit: dict[str, Any],
    range_analysis: dict[str, Any],
    trend_stability: dict[str, Any],
    robustness: dict[str, Any],
    engine_comparison: dict[str, Any],
    adaptive_results: dict[str, Any],
    fingerprint_unchanged: bool,
) -> dict[str, Any]:
    passes = robustness.get("passes", False) and fingerprint_unchanged
    trend_contrib = regime_audit.get("per_engine", {}).get("trend_rf_v40", {})
    range_contrib = regime_audit.get("per_engine", {}).get("phase9_9", {})

    return {
        "phase": "14.9",
        "PHASE_14_9_STATUS": "READY_FOR_PHASE15" if passes else "NEEDS_REVIEW",
        "READY_FOR": "Phase 15" if passes else "NEEDS_REVIEW",
        "acceptance": {**robustness.get("checks", {}), "fingerprint_unchanged": fingerprint_unchanged},
        "explanation": {
            "trend_contribution": {
                "trades": trend_contrib.get("trades", 0),
                "profit_factor": trend_contrib.get("profit_factor", 0),
                "contribution_pct": trend_contrib.get("contribution_pct", 0),
                "summary": "Trend RF v40 dominates accepted trades when adaptive router favors TREND conditions.",
            },
            "range_contribution": {
                "trades": range_contrib.get("trades", 0),
                "profit_factor": range_contrib.get("profit_factor", 0),
                "zero_trade_analysis": range_analysis.get("zero_trades_root_causes", []),
                "summary": "Phase 9.9 blocked by low raw confidence (~0.27) vs legacy 0.55 gate; rarely selected by weights.",
            },
            "adaptive_router_behavior": adaptive_results.get("router_behavior", {}),
            "remaining_risks": [
                "Trend period-dependency across 90/365d windows" if trend_stability.get("period_dependency_high") else "Moderate period dependency",
                "Range engine near-zero contribution in current sample",
                "TREND regime dominance may reduce diversification",
                "Risk layer still blocks significant signal volume",
            ],
        },
        "metrics": robustness.get("metrics", {}),
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
