"""Phase 13.7 — report writers and final answers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_7.config import (
    MIN_ROBUSTNESS_PASS,
    MIN_TRADES_PASS,
    PHASE13_5_BASELINE_PF,
    PHASE9_9_BASELINE_PF,
)
from tradingbot.ml.research.router_optimizer.optimizer_types import config_to_dict


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def build_robust_score_comparison(stability: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "13.7",
        "ranking": stability.get("ranking", []),
        "best_variant": stability.get("best_variant"),
        "scoring_weights": {
            "profit_factor": 0.25,
            "expectancy": 0.20,
            "walk_forward": 0.30,
            "trade_consistency": 0.15,
            "drawdown": 0.10,
        },
        "trade_floor": {"soft_reject": 100, "strong_reject": 300},
    }


def _strip_trades(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "trades"}


def build_final_answers(
    *,
    initial_audit: dict[str, Any],
    stability: dict[str, Any],
    trend_debug: dict[str, Any],
    range_failures: dict[str, Any],
    monte_carlo: dict[str, Any],
    phase_comparison: list[dict[str, Any]],
    best_metrics: dict[str, Any],
    wf_robustness: float,
    trend_contribution: dict[str, Any],
) -> dict[str, Any]:
    trades = int(best_metrics.get("trades", 0))
    pf = float(best_metrics.get("profit_factor", 0.0))
    mc_ok = monte_carlo.get("remains_profitable", False)

    pass_trades = trades >= MIN_TRADES_PASS
    pass_wf = wf_robustness > MIN_ROBUSTNESS_PASS
    pass_pf = pf > PHASE13_5_BASELINE_PF
    pass_99 = pf >= PHASE9_9_BASELINE_PF * 0.90
    pass_trend = trend_contribution.get("trend_measurable_in_baseline", False) or trend_contribution.get(
        "best_variant_trend_trades", 0
    ) > 0

    ready = all([pass_trades, pass_wf, mc_ok, pass_pf, pass_99, pass_trend])

    return {
        "PHASE_13_7_FINAL_REPORT": {
            "1_why_phase13_6_overfit": initial_audit.get("why_overfit_happened", []),
            "2_optimizer_fixes": initial_audit.get("fixes_planned", []),
            "3_best_router_configuration": _strip_trades(stability.get("best_config", {})),
            "4_phase_comparison": phase_comparison,
            "5_trend_engine_contribution": trend_contribution,
            "6_recommendation": "READY_FOR_PHASE14" if ready else "NEEDS_REVIEW",
            "pass_criteria": {
                "min_300_trades": pass_trades,
                "walk_forward_robustness_gt_0_30": pass_wf,
                "monte_carlo_profitable": mc_ok,
                "pf_gt_phase13_5": pass_pf,
                "no_major_degradation_vs_phase9_9": pass_99,
                "trend_contribution_measurable": pass_trend,
            },
            "range_failure_top_driver": range_failures.get("top_driver"),
            "trend_debug_summary": trend_debug.get("summary"),
        }
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
    from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig

    if isinstance(obj, OptimizerConfig):
        return config_to_dict(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")
