"""Shadow optimization report persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir


def shadow_optimization_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "shadow_optimization.json"


def write_shadow_optimization_report(
    payload: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    path = shadow_optimization_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_shadow_optimization_report(base_dir: str | Path | None = None) -> dict[str, Any]:
    path = shadow_optimization_path(base_dir)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
