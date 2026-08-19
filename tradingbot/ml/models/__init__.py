"""Offline baseline ML models — Phase 4.0."""

from tradingbot.ml.models.base import BaseModel
from tradingbot.ml.models.dataset_loader import DatasetSplits, load_dataset_splits
from tradingbot.ml.models.evaluator import EvaluationResult, ModelEvaluator, expected_r_from_proba
from tradingbot.ml.models.registry import get_model_entry, load_registry, register_model
from tradingbot.ml.models.training import MODEL_CHOICES, create_model, load_model, train_baseline_model

__all__ = [
    "BaseModel",
    "DatasetSplits",
    "EvaluationResult",
    "MODEL_CHOICES",
    "ModelEvaluator",
    "create_model",
    "expected_r_from_proba",
    "get_model_entry",
    "load_dataset_splits",
    "load_model",
    "load_registry",
    "register_model",
    "train_baseline_model",
]
