"""Phase 14.6 — report generation."""

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
    audit: dict[str, Any],
    calibration_comparison: dict[str, Any],
    bucket_analysis: dict[str, Any],
    threshold_search: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    fingerprint_unchanged: bool,
    best_method: str,
    best_threshold: float,
    best_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    compression_solved = any(m.get("compression_resolved") for m in calibration_comparison.get("methods", []))
    trades = int(best_metrics.get("effective_trades_est", 0)) if best_metrics else 0
    pf = float(best_metrics.get("profit_factor", 0)) if best_metrics else 0.0
    exp = float(best_metrics.get("expectancy", 0)) if best_metrics else 0.0
    wf = float(walk_forward.get("robustness_score", 0))
    mc = float(monte_carlo.get("profitable_pct", 0))
    gap = float(best_metrics.get("train_test_gap_penalty", 0)) if best_metrics else 0.0
    overfit_ok = gap < 0.25

    ready = (
        compression_solved
        and trades >= 300
        and pf >= 1.06
        and exp > 0
        and wf > 0.30
        and mc >= 0.95
        and overfit_ok
        and fingerprint_unchanged
    )

    return {
        "phase": "14.6",
        "PHASE_14_6_STATUS": "PASS" if ready else "NEEDS_REVIEW",
        "READY_FOR": "Phase 14.7" if ready else "NEEDS_REVIEW",
        "answers": {
            "1_compression_resolved": compression_solved,
            "2_best_calibration_method": best_method,
            "3_best_operating_threshold": best_threshold,
            "4_trades_at_best": trades,
            "5_expectancy_at_best": exp,
            "6_ready_for_phase14_7": ready,
        },
        "acceptance": {
            "compression_resolved": compression_solved,
            "trades_gte_300": trades >= 300,
            "pf_gte_phase99": pf >= 1.06,
            "expectancy_positive": exp > 0,
            "wf_gt_030": wf > 0.30,
            "mc_gte_95pct": mc >= 0.95,
            "no_overfit": overfit_ok,
            "fingerprint_unchanged": fingerprint_unchanged,
        },
        "recommended_policy": {
            "calibration_method": best_method,
            "confidence_threshold": best_threshold,
            "engine_specific": True,
            "range_engine": "phase9_9",
            "trend_engine": "trend_rf_v40",
        },
        "reason": (
            f"method={best_method}, th={best_threshold}, trades={trades}, pf={pf:.2f}, wf={wf:.2f}, mc={mc:.2%}"
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
