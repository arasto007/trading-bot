"""Phase 17B — frozen vs research RF comparison."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle
from tradingbot.ml.research.phase17b.config import RF_THRESHOLD
from tradingbot.ml.research.phase17b.dataset import chronological_split, extended_feature_columns
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _prob_stats(probs: np.ndarray) -> dict[str, float]:
    if len(probs) == 0:
        return {"min": 0.0, "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0, "std": 0.0, "spread": 0.0}
    return {
        "min": round(float(np.min(probs)), 6),
        "mean": round(float(np.mean(probs)), 6),
        "median": round(float(np.median(probs)), 6),
        "p95": round(float(np.percentile(probs, 95)), 6),
        "max": round(float(np.max(probs)), 6),
        "std": round(float(np.std(probs)), 6),
        "spread": round(float(np.max(probs) - np.min(probs)), 6),
    }


def _classifier_metrics(y_true: np.ndarray, probs: np.ndarray, *, threshold: float = RF_THRESHOLD) -> dict[str, Any]:
    if len(y_true) == 0:
        return {}
    pred = (probs >= threshold).astype(int)
    cm = confusion_matrix(y_true, pred, labels=[0, 1])
    metrics: dict[str, Any] = {
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 6),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 6),
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 6),
        "confusion_matrix": cm.tolist(),
        "actionable_count": int(pred.sum()),
        "actionable_rate": round(float(pred.mean()), 6),
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = round(float(roc_auc_score(y_true, probs)), 6)
        metrics["pr_auc"] = round(float(average_precision_score(y_true, probs)), 6)
    else:
        metrics["roc_auc"] = 0.5
        metrics["pr_auc"] = 0.0
    try:
        frac_pos, mean_pred = calibration_curve(y_true, probs, n_bins=min(5, max(2, int(len(y_true) / 50))), strategy="quantile")
        metrics["calibration"] = {
            "fraction_positive": [round(float(x), 4) for x in frac_pos],
            "mean_predicted": [round(float(x), 4) for x in mean_pred],
        }
    except ValueError:
        metrics["calibration"] = {}
    return metrics


def _frozen_probs(samples: pd.DataFrame, bundle: TrendRfBundle) -> np.ndarray:
    probs = []
    for _, row in samples.iterrows():
        feats = {k: float(row.get(k, 0.0)) for k in bundle.feature_order}
        probs.append(float(bundle.predict_proba(feats)))
    return np.array(probs, dtype=float)


def _research_probs(samples: pd.DataFrame, research: ResearchRfModel) -> np.ndarray:
    probs = []
    for _, row in samples.iterrows():
        probs.append(research.predict_proba(row))
    return np.array(probs, dtype=float)


def compare_models(
    samples: pd.DataFrame,
    bundle: TrendRfBundle,
    research: ResearchRfModel,
    *,
    threshold: float = RF_THRESHOLD,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, _, test = chronological_split(samples)
    if test.empty:
        test = samples.tail(min(5000, len(samples))).copy()
    y = test["successful_trade"].astype(int).values

    frozen_p = _frozen_probs(test, bundle)
    research_p = _research_probs(test, research)

    frozen_report = {
        "model": "frozen_trend_rf_v40",
        "feature_count": len(bundle.feature_order),
        "test_rows": len(test),
        "probability": _prob_stats(frozen_p),
        "ceiling": round(float(np.max(frozen_p)), 6),
        "metrics": _classifier_metrics(y, frozen_p, threshold=threshold),
    }
    research_report = {
        "model": "research_rf_top5",
        "feature_count": len(research.feature_order),
        "test_rows": len(test),
        "probability": _prob_stats(research_p),
        "ceiling": round(float(np.max(research_p)), 6),
        "metrics": _classifier_metrics(y, research_p, threshold=threshold),
    }

    comparison = {
        "phase": "17B",
        "threshold": threshold,
        "frozen": frozen_report,
        "research": research_report,
        "deltas": {
            "ceiling_delta": round(research_report["ceiling"] - frozen_report["ceiling"], 6),
            "spread_delta": round(
                research_report["probability"]["spread"] - frozen_report["probability"]["spread"], 6,
            ),
            "mean_prob_delta": round(
                research_report["probability"]["mean"] - frozen_report["probability"]["mean"], 6,
            ),
            "actionable_delta": (
                research_report["metrics"].get("actionable_count", 0)
                - frozen_report["metrics"].get("actionable_count", 0)
            ),
            "roc_auc_delta": round(
                research_report["metrics"].get("roc_auc", 0.5) - frozen_report["metrics"].get("roc_auc", 0.5), 6,
            ),
        },
    }
    probability_analysis = {
        "frozen_histogram_bins": _histogram(frozen_p),
        "research_histogram_bins": _histogram(research_p),
        "frozen": frozen_report["probability"],
        "research": research_report["probability"],
    }
    return comparison, probability_analysis


def _histogram(probs: np.ndarray, bins: int = 10) -> list[dict[str, Any]]:
    if len(probs) == 0:
        return []
    edges = np.linspace(0.0, 1.0, bins + 1)
    hist, _ = np.histogram(probs, bins=edges)
    return [
        {"bin_low": round(float(edges[i]), 3), "bin_high": round(float(edges[i + 1]), 3), "count": int(hist[i])}
        for i in range(len(hist))
    ]
