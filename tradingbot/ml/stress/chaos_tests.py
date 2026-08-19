"""Controlled chaos functions — sandbox only, never production data."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    dataset_path,
    feature_path,
    metadata_root,
    ml_root,
    reports_dir,
)
from tradingbot.ml.models.artifacts import model_metadata_path, model_pkl_path
from tradingbot.ml.stress.scenarios import FailureScenario


@dataclass
class SandboxSnapshot:
    path: Path
    content: bytes | None = None
    existed: bool = True


@dataclass
class StressSandbox:
    """
    Isolated temporary ML layout for failure simulation.

    Never modifies production data outside sandbox root.
    """

    root: Path
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    _snapshots: dict[str, SandboxSnapshot] = field(default_factory=dict)

    @classmethod
    def create(cls, root: Path, symbol: str = "XAUUSD", timeframe: str = "M5") -> "StressSandbox":
        sandbox = cls(root=root, symbol=symbol.upper(), timeframe=timeframe.upper())
        sandbox.seed_baseline()
        return sandbox

    @property
    def base_dir(self) -> Path:
        return self.root

    def seed_baseline(self) -> None:
        """Create minimal healthy sandbox structure."""
        paths = [
            feature_path(self.symbol, self.timeframe, self.root),
            dataset_path(self.symbol, self.timeframe, self.root),
            model_pkl_path("xgboost", self.root),
            model_metadata_path("xgboost", self.root),
            reports_dir(self.root) / "monitoring_summary.json",
            reports_dir(self.root) / "paper_trading_report.json",
            reports_dir(self.root) / "ab_test_report.json",
            reports_dir(self.root) / "feature_drift_report.json",
            metadata_root(self.root) / "runtime_config.json",
            metadata_root(self.root) / "model_versions.json",
            ml_root(self.root) / "deployment" / "readiness_report.json",
            ml_root(self.root) / "live_gate" / "live_gate_report.json",
        ]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                self._write_json(path, self._default_json(path.name))
            elif path.suffix == ".pkl":
                path.write_bytes(b"healthy-model-bytes")
            elif path.suffix == ".parquet":
                path.write_bytes(b"PAR1" + b"\x00" * 32)

    @staticmethod
    def _default_json(name: str) -> dict[str, Any]:
        defaults: dict[str, dict[str, Any]] = {
            "monitoring_summary.json": {
                "model_health": "HEALTHY",
                "expected_R": 0.35,
                "feature_drift_score": 0.05,
                "degradation": {"status": "HEALTHY", "drop_percentage": 0.0},
            },
            "paper_trading_report.json": {
                "metrics": {
                    "win_rate": 0.62,
                    "expectancy_r": 0.4,
                    "max_drawdown_r": 10.0,
                    "trade_frequency": 120,
                }
            },
            "ab_test_report.json": {
                "sample_size": 150,
                "winner": "HYBRID_BETTER",
                "confidence": "HIGH",
                "status": "COMPLETE",
            },
            "feature_drift_report.json": {
                "aggregate_score": 0.05,
                "severity": "LOW",
                "calibration_error": 0.05,
            },
            "runtime_config.json": {
                "active_model_name": "xgboost",
                "threshold": 0.60,
                "confidence_requirement": "MEDIUM",
                "shadow_mode": True,
                "live_enabled": False,
            },
            "model_versions.json": {"models": [{"model_name": "xgboost", "dataset_hash": "abc123"}]},
            "readiness_report.json": {"status": "CONDITIONAL_READY", "score": 0.72},
            "live_gate_report.json": {
                "permission": {"state": "CONDITIONAL_SHADOW", "allowed_mode": "shadow_only"}
            },
            "metadata.json": {
                "symbol": "XAUUSD",
                "version": "1.0",
                "feature_version": "2.0",
                "validation_score": 0.65,
                "dataset_hash": "abc123",
            },
        }
        return defaults.get(name, {"status": "OK"})

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _backup(self, path: Path) -> None:
        key = str(path)
        if key in self._snapshots:
            return
        existed = path.is_file()
        content = path.read_bytes() if existed else None
        self._snapshots[key] = SandboxSnapshot(path=path, content=content, existed=existed)

    def restore_all(self) -> None:
        for snap in self._snapshots.values():
            if snap.existed and snap.content is not None:
                snap.path.parent.mkdir(parents=True, exist_ok=True)
                snap.path.write_bytes(snap.content)
            elif snap.existed:
                if snap.path.is_file():
                    snap.path.unlink()
            elif snap.path.is_file():
                snap.path.unlink()
        self._snapshots.clear()

    def apply_scenario(self, scenario: FailureScenario) -> list[Path]:
        """Apply isolated failure; returns affected paths."""
        affected: list[Path] = []
        if scenario == FailureScenario.MISSING_FEATURE_DATA:
            affected.append(self._remove_file(feature_path(self.symbol, self.timeframe, self.root)))
        elif scenario == FailureScenario.STALE_FEATURE_DATA:
            affected.append(self._stale_file(feature_path(self.symbol, self.timeframe, self.root)))
        elif scenario == FailureScenario.CORRUPTED_MODEL_FILE:
            affected.append(self._corrupt_file(model_pkl_path("xgboost", self.root)))
        elif scenario == FailureScenario.INVALID_MODEL_METADATA:
            affected.append(self._corrupt_file(model_metadata_path("xgboost", self.root)))
        elif scenario == FailureScenario.DATASET_HASH_MISMATCH:
            path = metadata_root(self.root) / "model_versions.json"
            self._backup(path)
            self._write_json(path, {"models": [{"model_name": "xgboost", "dataset_hash": "mismatch"}]})
            affected.append(path)
        elif scenario == FailureScenario.FEATURE_DRIFT_SPIKE:
            path = reports_dir(self.root) / "feature_drift_report.json"
            self._backup(path)
            self._write_json(path, {"aggregate_score": 0.45, "severity": "HIGH", "calibration_error": 0.20})
            affected.append(path)
        elif scenario == FailureScenario.PERFORMANCE_DEGRADATION:
            path = reports_dir(self.root) / "monitoring_summary.json"
            self._backup(path)
            self._write_json(
                path,
                {
                    "model_health": "DEGRADED",
                    "expected_R": -0.1,
                    "degradation": {"status": "DEGRADED", "drop_percentage": 55.0},
                },
            )
            affected.append(path)
        elif scenario == FailureScenario.LOW_SAMPLE_SIZE:
            path = reports_dir(self.root) / "ab_test_report.json"
            self._backup(path)
            self._write_json(path, {"sample_size": 10, "confidence": "LOW", "status": "INSUFFICIENT_DATA"})
            affected.append(path)
        elif scenario == FailureScenario.SPREAD_SPIKE:
            path = reports_dir(self.root) / "monitoring_summary.json"
            self._backup(path)
            payload = self._default_json("monitoring_summary.json")
            payload["spread_regime"] = 0.95
            payload["alerts"] = [{"type": "SPREAD_SPIKE", "severity": "WARNING"}]
            self._write_json(path, payload)
            affected.append(path)
        elif scenario == FailureScenario.NEWS_VOLATILITY_SPIKE:
            path = reports_dir(self.root) / "monitoring_summary.json"
            self._backup(path)
            payload = self._default_json("monitoring_summary.json")
            payload["news_volatility"] = 0.92
            payload["model_health"] = "WARNING"
            self._write_json(path, payload)
            affected.append(path)
        elif scenario == FailureScenario.REPORT_CORRUPTION:
            path = reports_dir(self.root) / "monitoring_summary.json"
            affected.append(self._corrupt_file(path))
        elif scenario == FailureScenario.CONFIG_CORRUPTION:
            path = metadata_root(self.root) / "runtime_config.json"
            affected.append(self._corrupt_file(path))
        return affected

    def _remove_file(self, path: Path) -> Path:
        self._backup(path)
        if path.is_file():
            path.unlink()
        return path

    def _corrupt_file(self, path: Path) -> Path:
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{corrupted", encoding="utf-8")
        return path

    def _stale_file(self, path: Path) -> Path:
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_bytes(b"PAR1" + b"\x00" * 32)
        old = time.time() - (200 * 3600)
        os.utime(path, (old, old))
        return path


def simulate_missing_features(sandbox: StressSandbox) -> list[Path]:
    return sandbox.apply_scenario(FailureScenario.MISSING_FEATURE_DATA)


def simulate_model_failure(sandbox: StressSandbox) -> list[Path]:
    return sandbox.apply_scenario(FailureScenario.CORRUPTED_MODEL_FILE)


def simulate_report_corruption(sandbox: StressSandbox) -> list[Path]:
    return sandbox.apply_scenario(FailureScenario.REPORT_CORRUPTION)


def simulate_extreme_drift(sandbox: StressSandbox) -> list[Path]:
    return sandbox.apply_scenario(FailureScenario.FEATURE_DRIFT_SPIKE)
