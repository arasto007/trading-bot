"""Phase 14.5 — report generation."""

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
    sweep: dict[str, Any],
    opportunity: dict[str, Any],
    regime: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    best_fixed: dict[str, Any] | None,
    baseline_trades: int,
    baseline_pf: float,
    fingerprint_unchanged: bool,
    records_best: list[dict[str, Any]],
) -> dict[str, Any]:
    best_th = best_fixed["confidence_threshold"] if best_fixed else None
    trades = int(best_fixed.get("effective_trades_est", 0)) if best_fixed else 0
    pf = float(best_fixed.get("profit_factor", 0)) if best_fixed else 0.0
    exp = float(best_fixed.get("expectancy", 0)) if best_fixed else 0.0
    wf = float(walk_forward.get("robustness_score", 0))
    mc = float(monte_carlo.get("profitable_pct", 0))

    recovered = max(0, trades - baseline_trades)
    false_pos = int(best_fixed.get("false_acceptance", 0)) if best_fixed else 0

    regime_adaptive = regime.get("combined_metrics", {}).get("accepted_trades", 0) > trades

    ready = (
        trades >= 300
        and pf >= baseline_pf
        and exp > 0
        and wf > 0.30
        and mc >= 0.95
        and fingerprint_unchanged
        and pf >= 1.06
    )

    return {
        "phase": "14.5",
        "PHASE_14_5_STATUS": "PASS" if ready else "NEEDS_REVIEW",
        "READY_FOR": "Phase 14.6" if ready else "NEEDS_REVIEW",
        "answers": {
            "1_optimal_confidence_threshold": best_th,
            "2_fixed_or_regime_adaptive": "regime_adaptive" if regime_adaptive else "fixed",
            "3_trades_recovered": recovered,
            "4_false_positives_added": false_pos,
            "5_expectancy_improved": exp > 0,
            "6_ready_for_phase14_6": ready,
        },
        "acceptance": {
            "trades_gte_300": trades >= 300,
            "pf_gte_phase14_4": pf >= baseline_pf,
            "expectancy_positive": exp > 0,
            "wf_gt_030": wf > 0.30,
            "mc_gte_95pct": mc >= 0.95,
            "no_phase99_degradation": pf >= 1.06,
            "fingerprint_unchanged": fingerprint_unchanged,
        },
        "best_fixed_policy": best_fixed,
        "regime_policy": regime.get("regime_policy"),
        "baseline_phase14_4": {"trades": baseline_trades, "profit_factor": baseline_pf},
        "reason": "Optimal confidence operating point identified." if ready else f"trades={trades}, pf={pf:.2f}, wf={wf:.2f}, mc={mc:.2%}",
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
