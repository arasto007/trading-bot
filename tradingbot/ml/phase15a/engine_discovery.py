"""Phase 15A — automatic engine discovery."""

from __future__ import annotations

import importlib
import json
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase9_9_artifacts_root, phase9_9_metadata_path
from tradingbot.ml.phase15a.config import (
    RANGE_ENGINE_ID,
    TREND_ENGINE_ID,
    load_engine_manifests_dir,
    trend_rf_bundle_root,
    trend_rf_metadata_path,
    write_json,
)
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum


@dataclass
class EngineDescriptor:
    engine_id: str
    status: str
    module: str
    artifact_path: str | None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "status": self.status,
            "module": self.module,
            "artifact_path": self.artifact_path,
            "version": self.version,
        }


def _discover_from_artifacts(base_dir: str | Path | None = None) -> list[EngineDescriptor]:
    found: list[EngineDescriptor] = []
    p99_root = phase9_9_artifacts_root(base_dir)
    if p99_root.is_dir() and (p99_root / "model.pkl").is_file():
        version = None
        meta = phase9_9_metadata_path(base_dir)
        if meta.is_file():
            version = json.loads(meta.read_text(encoding="utf-8")).get("phase", "9.9")
        found.append(EngineDescriptor(
            engine_id=RANGE_ENGINE_ID, status="active", module="paper_trading.model_registry",
            artifact_path=str(p99_root), version=str(version),
        ))
    else:
        found.append(EngineDescriptor(
            engine_id=RANGE_ENGINE_ID, status="inactive", module="paper_trading.model_registry",
            artifact_path=None,
        ))

    trend_root = trend_rf_bundle_root(base_dir)
    if trend_root.is_dir() and (trend_root / "model.pkl").is_file():
        chk = validate_trend_checksum(base_dir=base_dir)
        version = None
        meta = trend_rf_metadata_path(base_dir)
        if meta.is_file():
            version = json.loads(meta.read_text(encoding="utf-8")).get("version")
        found.append(EngineDescriptor(
            engine_id=TREND_ENGINE_ID,
            status="active" if chk.get("valid") else "degraded",
            module="phase15a.trend_bundle",
            artifact_path=str(trend_root),
            version=version,
        ))
    else:
        found.append(EngineDescriptor(
            engine_id=TREND_ENGINE_ID, status="inactive", module="phase15a.trend_bundle",
            artifact_path=None,
        ))
    return found


def _discover_future_stubs() -> list[EngineDescriptor]:
    return [
        EngineDescriptor("lightgbm_range_v1", "future", "ml.models", None),
        EngineDescriptor("ensemble_v1", "future", "ml.orchestrator", None),
    ]


def _discover_deprecated() -> list[EngineDescriptor]:
    return [
        EngineDescriptor("phase9_6_lgbm", "deprecated", "research.regime_optimization", None, version="9.6"),
        EngineDescriptor("phase13_8_runtime_fit", "deprecated", "decision_engine.validation.load_production_engines", None),
    ]


def _scan_registry_modules() -> list[str]:
    modules: list[str] = []
    try:
        import tradingbot.ml.phase15a as pkg
        for mod in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
            modules.append(mod.name)
    except Exception:
        pass
    return modules


def discover_engines(*, base_dir: str | Path | None = None, persist_manifests: bool = True) -> dict[str, Any]:
    active = _discover_from_artifacts(base_dir)
    future = _discover_future_stubs()
    deprecated = _discover_deprecated()
    modules = _scan_registry_modules()

    payload = {
        "phase": "15A",
        "active": [e.to_dict() for e in active if e.status in ("active", "degraded")],
        "inactive": [e.to_dict() for e in active if e.status == "inactive"],
        "deprecated": [d.to_dict() for d in deprecated],
        "future": [f.to_dict() for f in future],
        "registry_modules": modules,
        "discovery_method": "artifact_scan+manifest",
    }

    if persist_manifests:
        out = load_engine_manifests_dir(base_dir)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "discovery.json", payload)
    return payload
