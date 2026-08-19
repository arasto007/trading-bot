"""Offline baseline model training — shared helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.models.artifacts import (
    ensure_model_dirs,
    feature_importance_report_path,
    model_metadata_path,
    reports_dir,
    training_timestamp,
    write_metadata,
)
from tradingbot.ml.models.base import BaseModel
from tradingbot.ml.models.dataset_loader import DatasetSplits, load_dataset_splits
from tradingbot.ml.models.evaluator import ModelEvaluator
from tradingbot.ml.models.lightgbm_model import LightGBMModel
from tradingbot.ml.models.logistic_model import LogisticModel
from tradingbot.ml.models.registry import register_model
from tradingbot.ml.models.xgboost_model import XGBoostModel

MODEL_CHOICES = ("logistic", "xgboost", "lightgbm")


def create_model(name: str, params: dict[str, Any] | None = None) -> BaseModel:
    key = name.lower()
    if key == "logistic":
        return LogisticModel(params)
    if key == "xgboost":
        return XGBoostModel(params)
    if key == "lightgbm":
        return LightGBMModel(params)
    raise ValueError(f"Unknown model: {name}. Choose from {MODEL_CHOICES}")


def load_model(name: str, base_dir: str | Path | None = None) -> BaseModel:
    key = name.lower()
    directory = ensure_model_dirs(key, base_dir)
    if key == "logistic":
        return LogisticModel.load(directory)
    if key == "xgboost":
        return XGBoostModel.load(directory)
    if key == "lightgbm":
        return LightGBMModel.load(directory)
    raise ValueError(f"Unknown model: {name}")


def train_baseline_model(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    params: dict[str, Any] | None = None,
    version: str = "1.0",
) -> dict[str, Any]:
    """Train, evaluate, persist artifact, and register model."""
    splits = load_dataset_splits(symbol, timeframe, base_dir)
    if splits.train.empty:
        raise ValueError("Training split is empty")

    model = create_model(model_name, params)
    eval_set = None
    if not splits.validation.empty:
        eval_set = (splits.X_val, splits.y_val)

    model.fit(splits.X_train, splits.y_train, eval_set=eval_set)

    evaluator = ModelEvaluator()
    val_result = None
    if not splits.validation.empty:
        val_result = evaluator.evaluate(
            model, splits.X_val, splits.y_val, symbol=symbol, timeframe=timeframe, split="validation"
        )
    test_result = None
    if not splits.test.empty:
        test_result = evaluator.evaluate(
            model, splits.X_test, splits.y_test, symbol=symbol, timeframe=timeframe, split="test"
        )

    artifact_dir = ensure_model_dirs(model.name, base_dir)
    model.save(artifact_dir)

    ts = training_timestamp()
    metadata = {
        "name": model.name,
        "version": version,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "training_timestamp_utc": ts,
        "parameters": model.params,
        "feature_columns": model.feature_names_,
        "feature_schema_version": splits.feature_version or FEATURE_SCHEMA_VERSION,
        "dataset_hash": splits.dataset_hash,
        "train_rows": len(splits.train),
        "validation_rows": len(splits.validation),
        "test_rows": len(splits.test),
    }
    if val_result:
        metadata["validation_metrics"] = val_result.metrics
        metadata["validation_trading"] = val_result.trading
    if test_result:
        metadata["test_metrics"] = test_result.metrics
        metadata["test_trading"] = test_result.trading

    write_metadata(model_metadata_path(model.name, base_dir), metadata)

    registry_entry = {
        "name": model.name,
        "version": version,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "dataset_hash": splits.dataset_hash,
        "feature_version": splits.feature_version or FEATURE_SCHEMA_VERSION,
        "training_time": ts,
        "parameters": model.params,
        "metrics": (test_result or val_result).metrics if (test_result or val_result) else {},
    }
    register_model(registry_entry, base_dir)

    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    if test_result:
        evaluator.save_report(test_result, base_dir)
    elif val_result:
        evaluator.save_report(val_result, base_dir)

    importance = model.feature_importances()
    if importance:
        imp_path = feature_importance_report_path(model.name, base_dir)
        imp_path.write_text(json.dumps(importance, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "artifact_dir": str(artifact_dir),
        "metadata": metadata,
        "registry": registry_entry,
        "validation": val_result.to_dict() if val_result else None,
        "test": test_result.to_dict() if test_result else None,
    }
