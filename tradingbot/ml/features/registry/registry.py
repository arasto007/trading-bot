"""Feature registry — metadata for all engineered features."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from tradingbot.ml.features.base import FeatureDefinition, REGISTRY_VERSION
from tradingbot.ml.features.registry.enrichment import FEATURE_ENRICHMENT, enrich_definition

_REGISTRY: dict[str, FeatureDefinition] = {}


def _apply_enrichment(defn: FeatureDefinition) -> FeatureDefinition:
    extra = FEATURE_ENRICHMENT.get(defn.name, {})
    if not extra and defn.dtype == "float" and defn.nullable_policy == "zero_fill":
        return defn
    return FeatureDefinition(
        name=defn.name,
        source=defn.source,
        description=defn.description,
        version=defn.version,
        family=defn.family,
        dtype=extra.get("dtype", defn.dtype),
        nullable_policy=extra.get("nullable_policy", defn.nullable_policy),
    )


def register(defn: FeatureDefinition) -> FeatureDefinition:
    defn = _apply_enrichment(defn)
    if defn.name in _REGISTRY:
        existing = _REGISTRY[defn.name]
        if existing.version != defn.version or existing.family != defn.family:
            raise ValueError(f"Feature name collision: {defn.name}")
        return existing
    _REGISTRY[defn.name] = defn
    return defn


def register_many(definitions: Iterable[FeatureDefinition]) -> None:
    for defn in definitions:
        register(defn)


def get(name: str) -> FeatureDefinition | None:
    return _REGISTRY.get(name)


def all_features() -> list[FeatureDefinition]:
    return sorted(_REGISTRY.values(), key=lambda d: (d.family, d.name))


def feature_names() -> list[str]:
    return [d.name for d in all_features()]


def registry_version() -> str:
    return REGISTRY_VERSION


def validate_integrity() -> list[str]:
    """Return list of integrity errors (empty if valid)."""
    errors: list[str] = []
    seen: set[str] = set()
    for defn in all_features():
        if not defn.name:
            errors.append("empty feature name")
        if defn.name in seen:
            errors.append(f"duplicate feature name: {defn.name}")
        seen.add(defn.name)
        for field in ("source", "description", "version", "family", "dtype", "nullable_policy"):
            if not getattr(defn, field):
                errors.append(f"{defn.name}: missing {field}")
        if defn.name not in FEATURE_ENRICHMENT:
            errors.append(f"{defn.name}: missing enrichment spec")
    return errors


def validate_json_file(path: str | Path | None = None) -> list[str]:
    """Verify features.json has complete metadata and matches in-memory registry."""
    if path is None:
        path = Path(__file__).with_name("features.json")
    path = Path(path)
    errors: list[str] = []
    if not path.is_file():
        return ["features.json not found"]
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"features.json invalid JSON: {exc}"]

    if not isinstance(rows, list):
        return ["features.json must be a list"]

    json_names = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("features.json row is not an object")
            continue
        name = row.get("name", "")
        json_names.add(name)
        for field in ("name", "family", "source", "version", "description", "dtype", "nullable_policy"):
            if not row.get(field):
                errors.append(f"{name or '?'}: missing {field} in features.json")

    reg_names = set(feature_names())
    if json_names != reg_names:
        missing = reg_names - json_names
        extra = json_names - reg_names
        if missing:
            errors.append(f"features.json missing: {sorted(missing)}")
        if extra:
            errors.append(f"features.json extra: {sorted(extra)}")
    return errors


def export_json(path: str | Path | None = None) -> Path:
    payload = [enrich_definition(d.to_dict()) for d in all_features()]
    for row in payload:
        extra = FEATURE_ENRICHMENT.get(row["name"], {})
        if "min" in extra:
            row["min"] = extra["min"]
        if "max" in extra:
            row["max"] = extra["max"]
        if "allowed_values" in extra:
            row["allowed_values"] = extra["allowed_values"]
    if path is None:
        path = Path(__file__).with_name("features.json")
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_json(path: str | Path | None = None) -> list[FeatureDefinition]:
    if path is None:
        path = Path(__file__).with_name("features.json")
    path = Path(path)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[FeatureDefinition] = []
    for row in data:
        enriched = enrich_definition(row)
        out.append(
            FeatureDefinition(
                name=enriched["name"],
                source=enriched["source"],
                description=enriched["description"],
                version=enriched["version"],
                family=enriched["family"],
                dtype=enriched.get("dtype", "float"),
                nullable_policy=enriched.get("nullable_policy", "zero_fill"),
            )
        )
    return out
