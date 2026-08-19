"""Phase 9.3 — prediction threshold optimization (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import precision_score, recall_score

from tradingbot.ml.data.paths import threshold_analysis_report_path
from tradingbot.ml.research.research_utils import ResearchContext, scaled_split_arrays

BUY_THRESHOLDS: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70)


def _threshold_metrics(
    y_true: np.ndarray,
    proba: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    y_pred = (proba >= threshold).astype(int)
    take_mask = y_pred == 1
    trade_frequency = round(float(take_mask.mean()), 4)
    precision = round(float(precision_score(y_true, y_pred, zero_division=0)), 4)
    recall = round(float(recall_score(y_true, y_pred, zero_division=0)), 4)
    if take_mask.any():
        win_rate_proxy = round(float((y_true[take_mask] == 1).mean()), 4)
    else:
        win_rate_proxy = 0.0
    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "win_rate_proxy": win_rate_proxy,
        "trade_frequency": trade_frequency,
        "signals": int(take_mask.sum()),
    }


def run_threshold_optimization(ctx: ResearchContext) -> dict[str, Any]:
    """Sweep BUY probability thresholds on validation; report test for reference only."""
    arrays = scaled_split_arrays(ctx)
    splits_out: dict[str, Any] = {}

    for split_name in ("validation", "test"):
        X, y = arrays[split_name]
        proba = ctx.model.predict_proba(X)[:, 1]
        rows = [_threshold_metrics(y, proba, t) for t in BUY_THRESHOLDS]
        splits_out[split_name] = rows

    val_rows = splits_out["validation"]
    best_val = max(val_rows, key=lambda r: (r["precision"], r["win_rate_proxy"], -abs(r["trade_frequency"] - 0.15)))

    return {
        "phase": "9.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": ctx.symbol,
        "timeframe": ctx.timeframe,
        "model": ctx.model_metadata.get("model_name", ctx.model.name),
        "thresholds_tested": list(BUY_THRESHOLDS),
        "by_split": splits_out,
        "best_threshold_validation": best_val["threshold"],
        "best_threshold_metrics_validation": best_val,
    }


def select_best_threshold(report: dict[str, Any]) -> float:
    return float(report.get("best_threshold_validation", 0.5))


def save_threshold_analysis_report(
    ctx: ResearchContext,
    base_dir: str | Path | None = None,
) -> Path:
    report = run_threshold_optimization(ctx)
    path = threshold_analysis_report_path(base_dir or ctx.base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
