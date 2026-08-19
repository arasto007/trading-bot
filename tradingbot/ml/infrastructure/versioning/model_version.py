"""Model version tracking."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import dataset_path, metadata_root
from tradingbot.ml.deployment.logger import readiness_report_path
from tradingbot.ml.models.artifacts import model_metadata_path, read_metadata


def model_versions_path(base_dir: str | Path | None = None) -> Path:
    return metadata_root(base_dir) / "model_versions.json"


@dataclass
class ModelVersionRecord:
    model_name: str
    model_hash: str
    feature_schema_version: str
    dataset_hash: str
    training_timestamp: str
    validation_score: float
    deployment_readiness_score: float
    symbol: str = ""
    timeframe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelVersionTracker:
    """Track model, feature, and dataset versions."""

    base_dir: str | Path | None = None

    def _file_hash(self, path: Path) -> str:
        if not path.is_file():
            return "missing"
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()[:16]

    def collect(self, symbol: str, timeframe: str, model_name: str = "xgboost") -> ModelVersionRecord:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        meta = read_metadata(model_metadata_path(model_name, self.base_dir))
        ds_path = dataset_path(symbol, timeframe, self.base_dir)
        readiness = {}
        rpath = readiness_report_path(self.base_dir)
        if rpath.is_file():
            readiness = json.loads(rpath.read_text(encoding="utf-8"))

        return ModelVersionRecord(
            model_name=model_name,
            model_hash=self._file_hash(model_metadata_path(model_name, self.base_dir).parent / "model.pkl"),
            feature_schema_version=str(meta.get("feature_version", meta.get("features_version", "2.0"))),
            dataset_hash=self._file_hash(ds_path),
            training_timestamp=str(meta.get("trained_at", meta.get("timestamp", ""))),
            validation_score=float(meta.get("validation_score", meta.get("accuracy", 0.0))),
            deployment_readiness_score=float(readiness.get("score", 0.0)),
            symbol=symbol,
            timeframe=timeframe,
        )

    def write_registry(self, records: list[ModelVersionRecord]) -> Path:
        path = model_versions_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "models": [r.to_dict() for r in records],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def read_registry(self) -> dict[str, Any]:
        path = model_versions_path(self.base_dir)
        if not path.is_file():
            return {"models": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, symbol: str, timeframe: str, model_name: str = "xgboost") -> Path:
        record = self.collect(symbol, timeframe, model_name)
        registry = self.read_registry()
        models = [m for m in registry.get("models", []) if m.get("model_name") != model_name]
        models.append(record.to_dict())
        path = model_versions_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "models": models,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
