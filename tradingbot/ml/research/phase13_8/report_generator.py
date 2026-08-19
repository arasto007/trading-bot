"""Phase 13.8 — report writers and final answers."""

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


def build_final_answers(
    *,
    audit: dict[str, Any],
    best_variant: str,
    best_label: str,
    best_model: str,
    best_threshold: float,
    trend_metrics: dict[str, Any],
    trend_contribution: int,
    router_rows: list[dict[str, Any]],
    wf_robustness: float,
    mc_positive: bool,
    phase99_pf: float,
) -> dict[str, Any]:
    pf = float(trend_metrics.get("profit_factor", 0.0))
    trades = int(trend_metrics.get("trades", 0))
    pass_trades = trades >= 100
    pass_pf = pf > 1.10
    pass_wf = wf_robustness > 0.30
    pass_mc = mc_positive
    best_router = max(router_rows, key=lambda r: r.get("profit_factor", 0.0)) if router_rows else {}
    pass_router = float(best_router.get("profit_factor", 0.0)) >= phase99_pf * 0.95
    pass_trend = trend_contribution >= 100 or trades >= 100
    ready = all([pass_trades, pass_pf, pass_wf, pass_mc, pass_router, pass_trend])

    return {
        "PHASE_13_8_FINAL_REPORT": {
            "1_why_trend_disappeared": audit.get("answers", {}),
            "2_best_rule_variant": best_variant,
            "3_best_label": best_label,
            "4_best_ml_model": best_model,
            "5_best_threshold": best_threshold,
            "6_trend_contribution_after_recovery": {
                "standalone_trades": trades,
                "router_trend_trades": trend_contribution,
            },
            "7_recommended_architecture": {
                "range_engine": "Phase 9.9",
                "trend_engine": f"Phase 13.8 recovered ({best_variant} + {best_model} @ {best_threshold})",
                "router": "Regime Router policy A",
            },
            "decision": "READY_FOR_PHASE14" if ready else "NEEDS_REVIEW",
            "pass_criteria": {
                "trend_trades_min_100": pass_trades,
                "pf_gt_1_10": pass_pf,
                "wf_robustness_gt_0_30": pass_wf,
                "monte_carlo_positive": pass_mc,
                "router_matches_phase99": pass_router,
                "no_tiny_sample_winners": trades >= 100,
            },
            "router_comparison": router_rows,
        }
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
