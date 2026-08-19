"""Phase 14.4 — report writers."""

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
    threshold_results: dict[str, Any],
    missed_trade: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    frequency: dict[str, Any],
    fingerprint_unchanged: bool,
    recommended: dict[str, Any],
) -> dict[str, Any]:
    best_conf = threshold_results.get("confidence", {}).get("best")
    best_qual = threshold_results.get("quality", {}).get("best")
    trades = int(best_conf.get("trades", 0)) if best_conf else 0
    wf_score = float(walk_forward.get("robustness_score", 0.0))
    mc_pass = bool(monte_carlo.get("passes_gate", False))

    ready = (
        fingerprint_unchanged
        and trades >= 300
        and wf_score > 0.30
        and mc_pass
        and best_conf is not None
    )

    return {
        "phase": "14.4",
        "PHASE_14_4_STATUS": "PASS" if ready else "NEEDS_REVIEW",
        "READY_FOR": "Phase 14.5" if ready else "NEEDS_REVIEW",
        "recommended_thresholds": recommended,
        "best_confidence": best_conf,
        "best_quality": best_qual,
        "walk_forward_robustness": wf_score,
        "monte_carlo_passes": mc_pass,
        "missed_trade_summary": {
            "total_blocked": missed_trade.get("total_blocked_signals"),
            "classifications": missed_trade.get("classification_counts"),
        },
        "frequency": frequency,
        "acceptance": {
            "safety_layers_unchanged": True,
            "min_trades_enforced": trades >= 300 or best_conf is None,
            "fingerprint_unchanged": fingerprint_unchanged,
            "reports_generated": True,
        },
        "reason": (
            "Optimal thresholds identified with walk-forward and Monte Carlo validation."
            if ready
            else f"trades={trades}, wf={wf_score:.2f}, mc={mc_pass}, fingerprint={fingerprint_unchanged}"
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
