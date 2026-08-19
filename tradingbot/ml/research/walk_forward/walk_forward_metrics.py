"""Phase 9.8 — aggregate walk-forward metrics and stability statistics."""

from __future__ import annotations

from typing import Any

import numpy as np


def _values(windows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(w.get(key, 0.0) or 0.0) for w in windows]


def aggregate_window_metrics(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute mean/std and stability metrics across walk-forward windows."""
    if not windows:
        return {
            "mean_metrics": {},
            "stability_score": {"consistency_score": 0.0, "std_profit_factor": 0.0},
        }

    keys = (
        "roc_auc",
        "precision",
        "recall",
        "f1",
        "win_rate",
        "profit_factor",
        "expectancy",
        "max_drawdown",
        "total_return",
        "sharpe_proxy",
        "num_trades",
    )
    mean_metrics: dict[str, float] = {}
    std_metrics: dict[str, float] = {}
    for key in keys:
        vals = _values(windows, key)
        mean_metrics[key] = round(float(np.mean(vals)), 4) if vals else 0.0
        std_metrics[key] = round(float(np.std(vals)), 4) if len(vals) > 1 else 0.0

    pf_vals = _values(windows, "profit_factor")
    exp_vals = _values(windows, "expectancy")
    wr_vals = _values(windows, "win_rate")

    best_idx = int(np.argmax(pf_vals)) if pf_vals else 0
    worst_idx = int(np.argmin(pf_vals)) if pf_vals else 0

    mean_pf = mean_metrics.get("profit_factor", 0.0)
    std_pf = std_metrics.get("profit_factor", 0.0)
    consistency = 0.0
    if mean_pf > 0:
        consistency = round(max(0.0, 1.0 - min(1.0, std_pf / mean_pf)), 4)

    positive_pf = sum(1 for v in pf_vals if v >= 1.0)
    positive_exp = sum(1 for v in exp_vals if v > 0.0)

    return {
        "mean_metrics": mean_metrics,
        "std_metrics": std_metrics,
        "stability_score": {
            "consistency_score": consistency,
            "std_profit_factor": std_pf,
            "std_expectancy": std_metrics.get("expectancy", 0.0),
            "std_win_rate": std_metrics.get("win_rate", 0.0),
            "windows_profit_factor_ge_1": positive_pf,
            "windows_expectancy_positive": positive_exp,
            "window_count": len(windows),
        },
        "best_window": windows[best_idx] if windows else None,
        "worst_window": windows[worst_idx] if windows else None,
    }


def summarize_for_report(windows: list[dict[str, Any]], aggregate: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact per-window rows for the main walk-forward report."""
    rows: list[dict[str, Any]] = []
    for w in windows:
        rows.append(
            {
                "window_id": w.get("window_id"),
                "start": w.get("validation_start"),
                "end": w.get("validation_end"),
                "trades": w.get("num_trades", 0),
                "win_rate": w.get("win_rate", 0.0),
                "profit_factor": w.get("profit_factor", 0.0),
                "expectancy": w.get("expectancy", 0.0),
                "drawdown": w.get("max_drawdown", 0.0),
                "roc_auc": w.get("roc_auc", 0.0),
            }
        )
    return rows
