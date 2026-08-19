"""Phase 9.4 — research model comparison and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.training.evaluation import EvaluationMetrics

DEFAULT_WEIGHTS = {
    "roc_auc": 0.40,
    "precision": 0.15,
    "recall": 0.15,
    "expectancy_R": 0.15,
    "profit_factor_proxy": 0.15,
}

MODEL_PRIORITY = ("lightgbm", "xgboost", "random_forest", "logistic")


@dataclass
class ModelCandidate:
    model_name: str
    variant_id: str
    validation: EvaluationMetrics
    test: EvaluationMetrics
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    composite_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "variant_id": self.variant_id,
            "hyperparameters": self.hyperparameters,
            "composite_score": round(self.composite_score, 6),
            "validation": self.validation.to_dict(),
            "test": self.test.to_dict(),
        }


def _metric_value(metrics: EvaluationMetrics, key: str) -> float:
    if key in metrics.classification:
        return float(metrics.classification[key])
    if key in metrics.trading:
        return float(metrics.trading[key])
    return 0.0


def composite_score(metrics: EvaluationMetrics, weights: dict[str, float] | None = None) -> float:
    """Weighted score across validation ROC-AUC and trading proxies."""
    w = weights or DEFAULT_WEIGHTS
    roc = _metric_value(metrics, "roc_auc")
    precision = _metric_value(metrics, "precision")
    recall = _metric_value(metrics, "recall")
    expectancy = _metric_value(metrics, "expectancy_R")
    pf = _metric_value(metrics, "profit_factor_proxy")
    expectancy_norm = max(0.0, min(1.0, (expectancy + 1.0) / 3.0))
    pf_norm = max(0.0, min(1.0, pf / 3.0))
    return (
        w["roc_auc"] * roc
        + w["precision"] * precision
        + w["recall"] * recall
        + w["expectancy_R"] * expectancy_norm
        + w["profit_factor_proxy"] * pf_norm
    )


class ModelSelector:
    """Compare research retrain candidates and pick the best on validation metrics."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or dict(DEFAULT_WEIGHTS)

    def score_candidate(self, candidate: ModelCandidate) -> float:
        candidate.composite_score = composite_score(candidate.validation, self.weights)
        return candidate.composite_score

    def rank(self, candidates: list[ModelCandidate]) -> list[ModelCandidate]:
        for c in candidates:
            self.score_candidate(c)

        def sort_key(c: ModelCandidate) -> tuple[float, float, int]:
            val_auc = _metric_value(c.validation, "roc_auc")
            priority = MODEL_PRIORITY.index(c.model_name) if c.model_name in MODEL_PRIORITY else 99
            return (-val_auc, -c.composite_score, priority)

        return sorted(candidates, key=sort_key)

    def select_best(self, candidates: list[ModelCandidate]) -> ModelCandidate:
        ranked = self.rank(candidates)
        if not ranked:
            raise ValueError("No model candidates to select from")
        return ranked[0]

    def comparison_table(self, candidates: list[ModelCandidate]) -> list[dict[str, Any]]:
        ranked = self.rank(candidates)
        rows: list[dict[str, Any]] = []
        for c in ranked:
            rows.append(
                {
                    "model": c.model_name,
                    "variant": c.variant_id,
                    "composite_score": round(c.composite_score, 4),
                    "validation_roc_auc": _metric_value(c.validation, "roc_auc"),
                    "validation_precision": _metric_value(c.validation, "precision"),
                    "validation_recall": _metric_value(c.validation, "recall"),
                    "validation_expectancy_R": _metric_value(c.validation, "expectancy_R"),
                    "validation_profit_factor_proxy": _metric_value(c.validation, "profit_factor_proxy"),
                    "test_roc_auc": _metric_value(c.test, "roc_auc"),
                }
            )
        return rows
