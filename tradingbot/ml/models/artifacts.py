"""Model artifact paths and persistence helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root, reports_dir


def models_root(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "models"


def model_artifact_dir(model_name: str, base_dir: str | Path | None = None) -> Path:
    return models_root(base_dir) / model_name.lower()


def model_pkl_path(model_name: str, base_dir: str | Path | None = None) -> Path:
    return model_artifact_dir(model_name, base_dir) / "model.pkl"


def model_metadata_path(model_name: str, base_dir: str | Path | None = None) -> Path:
    return model_artifact_dir(model_name, base_dir) / "metadata.json"


def models_registry_path(base_dir: str | Path | None = None) -> Path:
    return models_root(base_dir) / "registry.json"


def evaluation_report_path(symbol: str, timeframe: str, model_name: str, base_dir: str | Path | None = None) -> Path:
    tf = timeframe.upper()
    return reports_dir(base_dir) / f"{symbol.upper()}_{tf}_{model_name.lower()}_evaluation.json"


def feature_importance_report_path(model_name: str, base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / f"{model_name.lower()}_feature_importance.json"


def shap_summary_report_path(symbol: str, timeframe: str, model_name: str, base_dir: str | Path | None = None) -> Path:
    tf = timeframe.upper()
    return reports_dir(base_dir) / f"{symbol.upper()}_{tf}_{model_name.lower()}_shap_summary.json"


def ensure_model_dirs(model_name: str, base_dir: str | Path | None = None) -> Path:
    root = model_artifact_dir(model_name, base_dir)
    root.mkdir(parents=True, exist_ok=True)
    models_root(base_dir).mkdir(parents=True, exist_ok=True)
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    return root


def write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def training_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
