"""Versioned model artifact registry for Phase 8.6."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    training_metadata_path,
    training_model_path,
    training_models_root,
    training_report_path,
    training_scaler_path,
)
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import TrainingModel


@dataclass
class ModelBundle:
    version: str
    model: TrainingModel
    feature_pipeline: FeaturePipeline
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def model_name(self) -> str:
        return str(self.metadata.get("model_name", self.model.name))


def next_version(base_dir: str | Path | None = None) -> str:
    """Return next available model version integer as string."""
    root = training_models_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    versions: list[int] = []
    for path in root.glob("model_v*.pkl"):
        stem = path.stem  # model_v1
        try:
            versions.append(int(stem.split("_v", 1)[1]))
        except (IndexError, ValueError):
            continue
    return str(max(versions, default=0) + 1)


def save_model_bundle(
    bundle: ModelBundle,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Persist model, scaler, metadata, and feature order for a version."""
    ver = str(bundle.version).lstrip("v")
    model_path = training_model_path(ver, base_dir)
    bundle.model.save(model_path)
    scaler_path, order_path = bundle.feature_pipeline.save(ver, base_dir)
    meta_path = training_metadata_path(ver, base_dir)
    meta = {
        **bundle.metadata,
        "version": ver,
        "model_name": bundle.model.name,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "paths": {
            "model": str(model_path),
            "scaler": str(scaler_path),
            "feature_order": str(order_path),
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "model": model_path,
        "scaler": scaler_path,
        "feature_order": order_path,
        "metadata": meta_path,
    }


def load_model_bundle(version: str | int, base_dir: str | Path | None = None) -> ModelBundle:
    """Load a saved model bundle by version."""
    ver = str(version).lstrip("v")
    meta_path = training_metadata_path(ver, base_dir)
    if not meta_path.is_file():
        raise FileNotFoundError(f"Model metadata not found for version v{ver}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    model_path = training_model_path(ver, base_dir)
    model = TrainingModel.load(model_path)
    pipeline = FeaturePipeline.load(ver, base_dir)
    return ModelBundle(version=ver, model=model, feature_pipeline=pipeline, metadata=metadata)


def save_training_report(
    report: dict[str, Any],
    version: str | int,
    base_dir: str | Path | None = None,
) -> Path:
    ver = str(version).lstrip("v")
    path = training_report_path(ver, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def resolve_model_path(model_arg: str, base_dir: str | Path | None = None) -> Path:
    """Resolve CLI --evaluate model argument to a concrete path."""
    path = Path(model_arg)
    if path.is_file():
        return path
    if model_arg.startswith("model_v") and model_arg.endswith(".pkl"):
        candidate = training_models_root(base_dir) / model_arg
        if candidate.is_file():
            return candidate
    if model_arg.isdigit() or model_arg.startswith("v"):
        candidate = training_model_path(model_arg, base_dir)
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Model artifact not found: {model_arg}")
