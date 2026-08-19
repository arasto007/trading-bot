"""Phase 17C — TREND quality comparison (frozen vs research)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle
from tradingbot.ml.research.phase17b.comparison import compare_models
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel


def evaluate_trend_quality(
    samples: pd.DataFrame,
    bundle: TrendRfBundle,
    research: ResearchRfModel,
) -> dict[str, Any]:
    comparison, probability_analysis = compare_models(samples, bundle, research)
    frozen = comparison["frozen"]
    research_r = comparison["research"]
    deltas = comparison["deltas"]

    fm = frozen.get("metrics", {})
    rm = research_r.get("metrics", {})

    return {
        "phase": "17C",
        "frozen": {
            "ceiling": frozen.get("ceiling"),
            "spread": frozen.get("probability", {}).get("spread"),
            "precision": fm.get("precision"),
            "recall": fm.get("recall"),
            "f1": fm.get("f1"),
            "roc_auc": fm.get("roc_auc"),
            "pr_auc": fm.get("pr_auc"),
            "confusion_matrix": fm.get("confusion_matrix"),
            "false_positives": _fp(fm.get("confusion_matrix")),
            "false_negatives": _fn(fm.get("confusion_matrix")),
            "calibration": fm.get("calibration"),
        },
        "research": {
            "ceiling": research_r.get("ceiling"),
            "spread": research_r.get("probability", {}).get("spread"),
            "precision": rm.get("precision"),
            "recall": rm.get("recall"),
            "f1": rm.get("f1"),
            "roc_auc": rm.get("roc_auc"),
            "pr_auc": rm.get("pr_auc"),
            "confusion_matrix": rm.get("confusion_matrix"),
            "false_positives": _fp(rm.get("confusion_matrix")),
            "false_negatives": _fn(rm.get("confusion_matrix")),
            "calibration": rm.get("calibration"),
        },
        "deltas": deltas,
        "probability_analysis": probability_analysis,
        "materially_improved": (
            deltas.get("ceiling_delta", 0) > 0
            and deltas.get("spread_delta", 0) > 0
            and deltas.get("actionable_delta", 0) > 0
        ),
    }


def _fp(cm: list | None) -> int:
    if not cm or len(cm) < 2 or len(cm[0]) < 2:
        return 0
    return int(cm[0][1])


def _fn(cm: list | None) -> int:
    if not cm or len(cm) < 2 or len(cm[1]) < 2:
        return 0
    return int(cm[1][0])
