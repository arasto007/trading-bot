"""Reproducibility metadata for research experiments."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import dataset_path
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION


def dataset_fingerprint(symbol: str, timeframe: str, base_dir: str | Path | None = None) -> str:
    path = dataset_path(symbol, timeframe, base_dir)
    if not path.is_file():
        return "missing"
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def git_commit_hash(cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def build_reproducibility_bundle(
    symbol: str,
    timeframe: str,
    *,
    model_name: str,
    model_version: str,
    parameters: dict[str, Any],
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "dataset_fingerprint": dataset_fingerprint(symbol, timeframe, base_dir),
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "model_name": model_name,
        "model_version": model_version,
        "parameters": parameters,
        "git_commit": git_commit_hash(),
    }


def verify_reproducibility(record: dict[str, Any], symbol: str, timeframe: str, base_dir: str | Path | None = None) -> bool:
    bundle = record.get("reproducibility", {})
    current = dataset_fingerprint(symbol, timeframe, base_dir)
    stored = bundle.get("dataset_fingerprint", record.get("dataset_hash", ""))
    return stored == current or stored == "missing" or current == "missing"
