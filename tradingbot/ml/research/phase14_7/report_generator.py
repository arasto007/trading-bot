"""Phase 14.7 — report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_7.config import MIN_PF_IMPROVEMENT, MIN_TRADE_FLOOR, MIN_WF_ROBUSTNESS, MIN_MC_PROFITABLE


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def build_final_report(
    *,
    comparison: dict[str, Any],
    full_metrics: dict[str, Any],
    regime_check: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    fingerprint_unchanged: bool,
    calibration_policy: dict[str, Any],
) -> dict[str, Any]:
    trades = int(full_metrics.get("effective_trades_est", 0))
    pf = float(full_metrics.get("profit_factor", 0))
    baseline_pf = float(comparison.get("baseline_pf", 0))
    pf_improvement = float(comparison.get("pf_improvement_vs_baseline", 0))
    wf = float(walk_forward.get("robustness_score", 0))
    mc = float(monte_carlo.get("profitable_pct", 0))

    ready = (
        comparison.get("full_beats_baseline", False)
        and trades >= MIN_TRADE_FLOOR
        and pf_improvement >= MIN_PF_IMPROVEMENT
        and wf > MIN_WF_ROBUSTNESS
        and mc >= MIN_MC_PROFITABLE
        and not regime_check.get("collapsed", True)
        and not regime_check.get("unrealistic_dominance", True)
        and fingerprint_unchanged
    )

    return {
        "phase": "14.7",
        "PHASE_14_7_STATUS": "PASS" if ready else "NEEDS_REVIEW",
        "READY_FOR": "Phase 14.8" if ready else "NEEDS_REVIEW",
        "answers": {
            "1_full_pipeline_beats_baseline": comparison.get("full_beats_baseline"),
            "2_trades_at_full_pipeline": trades,
            "3_pf_improvement_meaningful": pf_improvement >= MIN_PF_IMPROVEMENT,
            "4_walk_forward_robust": wf > MIN_WF_ROBUSTNESS,
            "5_monte_carlo_robust": mc >= MIN_MC_PROFITABLE,
            "6_no_regime_collapse": not regime_check.get("collapsed", True),
            "7_ready_for_phase14_8": ready,
        },
        "acceptance": {
            "beats_phase99_baseline": comparison.get("full_beats_baseline"),
            "trades_gte_300": trades >= MIN_TRADE_FLOOR,
            "pf_improvement_gte_005": pf_improvement >= MIN_PF_IMPROVEMENT,
            "wf_gt_030": wf > MIN_WF_ROBUSTNESS,
            "mc_gte_95pct": mc >= MIN_MC_PROFITABLE,
            "no_regime_collapse": not regime_check.get("collapsed", True),
            "no_unrealistic_dominance": not regime_check.get("unrealistic_dominance", True),
            "fingerprint_unchanged": fingerprint_unchanged,
            "reports_generated": True,
        },
        "calibration_policy": calibration_policy,
        "metrics_summary": {
            "baseline_pf": baseline_pf,
            "router_pf": comparison.get("router_pf"),
            "full_pf": pf,
            "full_expectancy": full_metrics.get("expectancy"),
        },
        "reason": f"full_pf={pf:.2f}, baseline_pf={baseline_pf:.2f}, trades={trades}, wf={wf:.2f}, mc={mc:.2%}",
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
