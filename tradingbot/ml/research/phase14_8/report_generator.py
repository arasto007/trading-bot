"""Phase 14.8 — report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase14_8.config import MIN_MC_PROFITABLE, MIN_POSITIVE_PERIODS, MIN_WF_ROBUSTNESS


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def build_final_report(
    *,
    multi_period: dict[str, Any],
    regime_stress: dict[str, Any],
    risk_audit: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    fingerprint_unchanged: bool,
    full_metrics: dict[str, Any],
) -> dict[str, Any]:
    positive_periods = int(multi_period.get("positive_periods", 0))
    wf = float(walk_forward.get("robustness_score", 0))
    mc = float(monte_carlo.get("profitable_pct", 0))
    risk_ok = bool(risk_audit.get("passes", False))
    no_fake_dom = not regime_stress.get("collapse_check", {}).get("unrealistic_dominance", True)
    no_overfit = not walk_forward.get("overfit_detected", True)

    ready = (
        positive_periods >= MIN_POSITIVE_PERIODS
        and wf > MIN_WF_ROBUSTNESS
        and mc >= MIN_MC_PROFITABLE
        and risk_ok
        and no_fake_dom
        and no_overfit
        and fingerprint_unchanged
        and float(full_metrics.get("expectancy", 0)) > 0
    )

    return {
        "phase": "14.8",
        "PHASE_14_8_STATUS": "PASS" if ready else "NEEDS_REVIEW",
        "READY_FOR": "Phase 15" if ready else "NEEDS_REVIEW",
        "acceptance": {
            "positive_across_periods": positive_periods >= MIN_POSITIVE_PERIODS,
            "wf_robustness_gt_030": wf > MIN_WF_ROBUSTNESS,
            "mc_profitable_gt_95pct": mc >= MIN_MC_PROFITABLE,
            "risk_audit_passes": risk_ok,
            "no_fake_regime_dominance": no_fake_dom,
            "no_overfit_detected": no_overfit,
            "fingerprint_unchanged": fingerprint_unchanged,
        },
        "summary_metrics": {
            "full_pf": full_metrics.get("profit_factor"),
            "full_expectancy": full_metrics.get("expectancy"),
            "full_trades_est": full_metrics.get("effective_trades_est"),
            "walk_forward_robustness": wf,
            "monte_carlo_profitable_pct": mc,
        },
        "reason": (
            f"periods+={positive_periods}, wf={wf:.2f}, mc={mc:.2%}, risk={risk_ok}, overfit={not no_overfit}"
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
