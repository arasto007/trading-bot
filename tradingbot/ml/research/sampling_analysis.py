"""Phase 9.3 — event sampling quality analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

from tradingbot.ml.data.paths import sampling_analysis_report_path
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.research_utils import ResearchContext, scaled_split_arrays

EVENT_TYPES = (
    "bos",
    "choch",
    "liquidity_sweep",
    "fvg",
    "order_block",
    "session_transition",
    "trading_session",
)


def _frame_metrics(ctx: ResearchContext, subset: pd.DataFrame) -> dict[str, Any] | None:
    if subset.empty or len(subset) < 5:
        return None
    cols = list(ctx.splits.feature_columns)
    X_sub = subset.loc[:, cols].astype(np.float64)
    y_sub = subset["label"].astype(int)
    if len(y_sub) < 5:
        return {"sample_count": len(y_sub), "accuracy": None, "precision": None, "recall": None, "f1": None, "roc_auc": None}
    X_s = ctx.pipeline.transform(X_sub)
    y_np = y_sub.to_numpy(dtype=int)
    proba = ctx.model.predict_proba(X_s)
    y_pred = (proba[:, 1] >= 0.5).astype(int)
    roc = None
    if len(np.unique(y_np)) > 1:
        roc = round(float(roc_auc_score(y_np, proba[:, 1])), 4)
    return {
        "sample_count": len(y_np),
        "accuracy": round(float(accuracy_score(y_np, y_pred)), 4),
        "precision": round(float(precision_score(y_np, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_np, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_np, y_pred, zero_division=0)), 4),
        "roc_auc": roc,
    }


def _analyze_event_type(ctx: ResearchContext, event_type: str) -> dict[str, Any]:
    combined = pd.concat(
        [ctx.splits.train, ctx.splits.validation, ctx.splits.test],
        ignore_index=True,
    )

    subset = combined.loc[combined["event_type"] == event_type]
    tp = int((subset["label"] == int(Label.TP_FIRST)).sum())
    sl = int((subset["label"] == int(Label.SL_FIRST)).sum())
    resolved = tp + sl
    win_rate = round(tp / resolved, 4) if resolved else 0.0

    model_perf: dict[str, Any] = {}
    for split_name, frame in (
        ("train", ctx.splits.train.loc[ctx.splits.train["event_type"] == event_type]),
        ("validation", ctx.splits.validation.loc[ctx.splits.validation["event_type"] == event_type]),
        ("test", ctx.splits.test.loc[ctx.splits.test["event_type"] == event_type]),
    ):
        metrics = _frame_metrics(ctx, frame.reset_index(drop=True))
        if metrics:
            model_perf[split_name] = metrics

    return {
        "event_type": event_type,
        "sample_count": len(subset),
        "tp_count": tp,
        "sl_count": sl,
        "win_rate": win_rate,
        "model_performance": model_perf,
    }


def run_sampling_analysis(ctx: ResearchContext) -> dict[str, Any]:
    """Compare event sampling quality across SMC event types."""
    arrays = scaled_split_arrays(ctx)
    overall_val = arrays["validation"]
    y_val = overall_val[1]
    X_val = overall_val[0]
    proba = ctx.model.predict_proba(X_val)
    y_pred = (proba[:, 1] >= 0.5).astype(int)
    overall = {
        "validation_accuracy": round(float(accuracy_score(y_val, y_pred)), 4),
        "validation_roc_auc": round(float(roc_auc_score(y_val, proba[:, 1])), 4)
        if len(np.unique(y_val)) > 1
        else 0.0,
    }

    by_type = [_analyze_event_type(ctx, et) for et in EVENT_TYPES]
    present = [e for e in by_type if e["sample_count"] > 0]
    missing = [et for et in EVENT_TYPES if et not in {e["event_type"] for e in present}]

    return {
        "phase": "9.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": ctx.symbol,
        "timeframe": ctx.timeframe,
        "event_types_analyzed": EVENT_TYPES,
        "missing_event_types": missing,
        "overall_model_validation": overall,
        "by_event_type": present,
        "total_samples": sum(e["sample_count"] for e in present),
    }


def save_sampling_analysis_report(
    ctx: ResearchContext,
    base_dir: str | Path | None = None,
) -> Path:
    report = run_sampling_analysis(ctx)
    path = sampling_analysis_report_path(base_dir or ctx.base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
