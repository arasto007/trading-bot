"""Phase 23B — runtime feature vector validation for Phase 9.9 inference."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def normalize_candles_for_builder(candles: pd.DataFrame) -> pd.DataFrame:
    """Ensure FeatureBuilder receives OHLCV with UTC DatetimeIndex."""
    out = candles.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        if out.index.tz is None:
            out.index = out.index.tz_localize("UTC")
        else:
            out.index = out.index.tz_convert("UTC")
        return out
    if "timestamp" in out.columns:
        out = out.set_index(pd.to_datetime(out["timestamp"], utc=True))
        return out
    if "time" in out.columns:
        out = out.set_index(pd.to_datetime(out["time"], utc=True))
        return out
    raise ValueError("candles_missing_datetime_index")


def validate_runtime_feature_vector(
    feats: dict[str, float] | None,
    feature_order: list[str],
) -> tuple[bool, list[str]]:
    """Validate feature vector before predict_proba — fail closed on missing/non-finite values."""
    errors: list[str] = []
    if not feats:
        return False, ["missing_feature_vector"]
    for name in feature_order:
        if name not in feats:
            errors.append(f"missing:{name}")
            continue
        value = float(feats[name])
        if not math.isfinite(value):
            errors.append(f"non_finite:{name}")
    if list(feats.keys())[: len(feature_order)] != feature_order and any(
        name not in feats for name in feature_order
    ):
        pass
    ordered = [name for name in feature_order if name in feats]
    if ordered != list(feature_order):
        errors.append("feature_order_mismatch")
    return len(errors) == 0, sorted(set(errors))


def ordered_feature_vector(feats: dict[str, float], feature_order: list[str]) -> dict[str, float]:
    return {name: float(feats[name]) for name in feature_order}


def hold_result_with_diagnostics(
    *,
    errors: list[str],
    feature_source: str | None,
    model_version: str,
) -> dict[str, Any]:
    return {
        "signal": "HOLD",
        "probability": 0.5,
        "confidence": 0.0,
        "sl": None,
        "tp": None,
        "model_version": model_version,
        "regime": "RANGE",
        "engine": "phase9_9",
        "predict_proba_called": False,
        "feature_validation_failed": True,
        "feature_validation_errors": errors,
        "feature_source": feature_source,
    }
