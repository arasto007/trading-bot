"""Phase 15J — frozen trend bundle validation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum


def validate_bundle(
    *,
    base_dir: str | None = None,
) -> dict[str, Any]:
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    checksum_result = validate_trend_checksum(base_dir=base_dir)
    return {
        "phase": "15J",
        "engine_id": bundle.metadata.get("engine_id"),
        "version": bundle.version,
        "checksum": bundle.checksum,
        "checksum_valid": bool(checksum_result.get("valid", False)),
        "checksum_detail": checksum_result,
        "training_rows": bundle.metadata.get("train_rows"),
        "seed": bundle.metadata.get("seed"),
        "dataset_fingerprint": bundle.metadata.get("dataset_fingerprint"),
        "training_fingerprint": bundle.metadata.get("training_fingerprint"),
        "feature_count": len(bundle.feature_order),
        "feature_names": list(bundle.feature_order),
        "threshold": bundle.config.get("threshold"),
        "model": bundle.config.get("model"),
    }
