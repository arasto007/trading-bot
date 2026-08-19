"""Model registry — track trained baseline models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.models.artifacts import models_registry_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    path = models_registry_path(base_dir)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def save_registry(entries: list[dict[str, Any]], base_dir: str | Path | None = None) -> Path:
    path = models_registry_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def register_model(
    entry: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    """Append or update model entry in registry.json."""
    entries = load_registry(base_dir)
    name = entry.get("name", "")
    version = entry.get("version", "1.0")
    entry["registered_at_utc"] = _now()

    updated = False
    for i, existing in enumerate(entries):
        if existing.get("name") == name and existing.get("version") == version:
            entries[i] = {**existing, **entry}
            updated = True
            break
    if not updated:
        entries.append(entry)

    return save_registry(entries, base_dir)


def get_model_entry(
    name: str,
    version: str = "1.0",
    base_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    for entry in load_registry(base_dir):
        if entry.get("name") == name and entry.get("version", "1.0") == version:
            return entry
    return None
