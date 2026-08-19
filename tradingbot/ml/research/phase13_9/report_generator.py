"""Phase 13.9 — report writers."""

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


def robust_score(metrics: dict[str, Any], *, wf: float = 0.5, minimum_trades: int = 300) -> float:
    trades = int(metrics.get("trades", 0))
    if trades < minimum_trades:
        return 0.0
    pf = min(float(metrics.get("profit_factor", 0.0)), 3.0) / 3.0
    exp = min(max(float(metrics.get("expectancy", metrics.get("expectancy_r", 0.0))) + 1.0, 0.0), 2.0) / 2.0
    dd = 1.0 - min(float(metrics.get("max_drawdown", 1.0)), 1.0)
    consistency = min(trades / 500.0, 1.0)
    return round(pf * 0.25 + exp * 0.20 + wf * 0.30 + consistency * 0.15 + dd * 0.10, 4)


def build_final_report(
    *,
    parity: dict[str, Any],
    signal_loss: dict[str, Any],
    trend_validation: dict[str, Any],
    comparisons: list[dict[str, Any]],
    best_router: str,
    wf_score: float,
    trend_contribution: int,
) -> dict[str, Any]:
    unified_signals = int(signal_loss.get("unified_signals", 0))
    signal_preservation = unified_signals >= 500 and trend_validation.get("parity_with_phase13_3", False)
    trend_contrib = trend_contribution >= 100
    best_m = next((c for c in comparisons if c.get("model") == best_router), {})
    trades = int(best_m.get("trades", 0))
    ready = signal_preservation and trend_contrib and trades >= 300 and wf_score > 0.30

    return {
        "signal_preservation": signal_preservation,
        "trend_contribution": trend_contrib,
        "best_router": best_router,
        "ready_for_phase14": ready,
        "reason": (
            "Unified pipeline restores trend signal parity; router meets stability gates."
            if ready
            else (
                f"Signal preservation={signal_preservation}, trend trades={trend_contribution}, "
                f"wf={wf_score:.2f}, best trades={trades}."
            )
        ),
        "unified_rule_signals": unified_signals,
        "legacy_rule_signals": signal_loss.get("legacy_signals"),
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
