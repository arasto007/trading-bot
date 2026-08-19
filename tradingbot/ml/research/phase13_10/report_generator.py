"""Phase 13.10 — report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_10.config import (
    MIN_MONTE_CARLO_PROFITABLE,
    MIN_TREND_TRADES_PASS,
    MIN_WF_ROBUSTNESS_PASS,
    PHASE99_BASELINE_PF,
)


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def build_final_report(
    *,
    funnel: dict[str, Any],
    threshold_results: dict[str, Any],
    rule_comparison: dict[str, Any],
    router_comparison: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    phase99_metrics: dict[str, Any],
    best_router_bt: dict[str, Any],
    fingerprint_unchanged: bool,
    artifacts_unchanged: bool,
    feature_drift: bool,
    best_policy_key: str,
) -> dict[str, Any]:
    trend_trades = int(funnel.get("funnel", {}).get("router_accepted", 0))
    router_m = best_router_bt.get("metrics", {})
    router_pf = float(router_m.get("profit_factor", 0.0))
    phase99_pf = float(phase99_metrics.get("profit_factor", PHASE99_BASELINE_PF))
    wf_score = float(walk_forward.get("robustness_score", 0.0))
    mc_pct = float(monte_carlo.get("profitable_pct", 0.0))

    trend_adds_value = trend_trades >= MIN_TREND_TRADES_PASS and router_pf > phase99_pf
    router_beats_99 = router_pf >= phase99_pf
    ready = (
        trend_trades >= MIN_TREND_TRADES_PASS
        and router_beats_99
        and wf_score > MIN_WF_ROBUSTNESS_PASS
        and mc_pct >= MIN_MONTE_CARLO_PROFITABLE
        and fingerprint_unchanged
        and artifacts_unchanged
        and not feature_drift
    )

    production_candidate = best_policy_key
    if production_candidate == "router_d" and trend_trades < MIN_TREND_TRADES_PASS:
        production_candidate = next(
            (r["policy"] for r in router_comparison.get("ranking", []) if r.get("trend_trades", 0) >= MIN_TREND_TRADES_PASS),
            best_policy_key,
        )

    return {
        "phase": "13.10",
        "answers": {
            "1_trend_engine_adds_value": trend_adds_value,
            "2_trend_trade_contribution": trend_trades,
            "3_router_outperforms_phase99": router_beats_99,
            "4_production_candidate": production_candidate,
            "5_ready_for_phase14": ready,
        },
        "acceptance": {
            "trend_trades_gte_100": trend_trades >= MIN_TREND_TRADES_PASS,
            "router_pf_gte_phase99": router_beats_99,
            "walk_forward_robustness_gt_030": wf_score > MIN_WF_ROBUSTNESS_PASS,
            "monte_carlo_profitable_gte_95pct": mc_pct >= MIN_MONTE_CARLO_PROFITABLE,
            "no_feature_drift": not feature_drift,
            "fingerprint_unchanged": fingerprint_unchanged,
            "artifacts_unchanged": artifacts_unchanged,
        },
        "status": "PASS" if ready else "NEEDS_REVIEW",
        "metrics": {
            "router_pf": round(router_pf, 4),
            "phase99_pf": round(phase99_pf, 4),
            "walk_forward_robustness": wf_score,
            "monte_carlo_profitable_pct": mc_pct,
            "trend_trades": trend_trades,
            "best_threshold": threshold_results.get("best_threshold"),
            "best_rule_variant": rule_comparison.get("best_variant"),
            "primary_bottleneck": funnel.get("primary_bottleneck"),
        },
        "reason": (
            "All Phase 13.10 acceptance gates passed."
            if ready
            else (
                f"trend_trades={trend_trades}, router_pf={router_pf:.2f} vs phase99={phase99_pf:.2f}, "
                f"wf={wf_score:.2f}, mc={mc_pct:.2%}, bottleneck={funnel.get('primary_bottleneck')}"
            )
        ),
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
