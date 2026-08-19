"""Phase 24I — unified frame phase99 feature input for range engine."""

from __future__ import annotations

import math
import os
from typing import Any

import pandas as pd

from tradingbot.ml.research.regime_router.phase99_feature_validation import validate_runtime_feature_vector

# Mirror phase13_9.config.PHASE99_FEATURE_MAP — avoid phase13_9 package import cycle.
_PHASE99_FEATURE_MAP: dict[str, str] = {
    "ema50_slope": "phase99_ema50_slope",
    "candle_direction": "phase99_candle_direction",
    "structure_distance": "phase99_structure_distance",
    "ema_cross_state": "phase99_ema_cross_state",
}

ENV_ENABLE_UNIFIED_FEATURE_INPUT = "ENABLE_UNIFIED_FEATURE_INPUT"
ENV_ENABLE_UNIFIED_BUILDER_VERIFY = "ENABLE_UNIFIED_BUILDER_VERIFY"

# Frozen Phase 9.9 model feature sanity bounds (read-only, no formula changes).
_RANGE_SANITY: dict[str, tuple[float, float]] = {
    "candle_direction": (-1.0, 1.0),
    "structure_distance": (0.0, 100.0),
    "ema50_slope": (-50.0, 50.0),
    "ema_cross_state": (-1.0, 1.0),
}

_VECTOR_MATCH_TOL = 1e-6


def unified_feature_input_enabled() -> bool:
    return os.environ.get(ENV_ENABLE_UNIFIED_FEATURE_INPUT, "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def unified_builder_verify_enabled() -> bool:
    return os.environ.get(ENV_ENABLE_UNIFIED_BUILDER_VERIFY, "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def extract_phase99_features_from_row(
    row: pd.Series,
    feature_order: list[str],
) -> dict[str, float] | None:
    """Map unified frame phase99_* columns to frozen model feature names."""
    mapped = row.copy()
    for src, dst in _PHASE99_FEATURE_MAP.items():
        if dst in mapped.index:
            val = mapped[dst]
            if pd.notna(val):
                mapped[src] = float(val)
    feats: dict[str, float] = {}
    for name in feature_order:
        if name not in mapped.index:
            return None
        val = mapped[name]
        if pd.isna(val):
            return None
        feats[name] = float(val)
    return feats


def validate_unified_feature_vector(
    feats: dict[str, float] | None,
    feature_order: list[str],
) -> tuple[bool, list[str]]:
    """
    Validate unified phase99 vector before inference.

    Checks count, names, order, finite values, dtype, and range sanity.
    """
    ok, errors = validate_runtime_feature_vector(feats, feature_order)
    if not ok or feats is None:
        return ok, errors

    for name in feature_order:
        val = float(feats[name])
        if not isinstance(val, (int, float)):
            errors.append(f"invalid_dtype:{name}")
            continue
        bounds = _RANGE_SANITY.get(name)
        if bounds is not None:
            lo, hi = bounds
            if val < lo or val > hi:
                errors.append(f"range_sanity:{name}")

    return len(errors) == 0, sorted(set(errors))


def vectors_match(
    left: dict[str, float],
    right: dict[str, float],
    feature_order: list[str],
    *,
    tol: float = _VECTOR_MATCH_TOL,
) -> bool:
    for name in feature_order:
        if abs(float(left[name]) - float(right[name])) > tol:
            return False
    return True


def resolve_range_features(
    *,
    row: pd.Series,
    feature_order: list[str],
    candles: pd.DataFrame | None,
    bar_index: int | None,
    features_from_row: Any,
    features_from_candles: Any,
) -> tuple[dict[str, float] | None, str | None, list[str]]:
    """
    Select feature source for range engine inference.

    Priority:
    1. Validated unified phase99 features (optional builder parity verify)
    2. FeatureBuilder.compute_at fallback
    3. Direct row columns fallback
    """
    errors: list[str] = []

    if unified_feature_input_enabled():
        unified_feats = extract_phase99_features_from_row(row, feature_order)
        ok, val_errors = validate_unified_feature_vector(unified_feats, feature_order)
        if ok and unified_feats is not None:
            if unified_builder_verify_enabled() and candles is not None and bar_index is not None:
                builder_feats = features_from_candles(candles, bar_index)
                b_ok, b_errors = validate_runtime_feature_vector(builder_feats, feature_order)
                if b_ok and builder_feats is not None and vectors_match(
                    unified_feats, builder_feats, feature_order
                ):
                    return unified_feats, "unified_phase99", []
                if builder_feats is not None and b_ok:
                    return builder_feats, "feature_builder", ["builder_parity_mismatch"]
                return builder_feats, "feature_builder", b_errors
            return unified_feats, "unified_phase99", []

        errors.extend(val_errors)

    if candles is not None and bar_index is not None:
        builder_feats = features_from_candles(candles, bar_index)
        return builder_feats, "feature_builder", errors

    row_feats = features_from_row(row)
    if row_feats is not None:
        return row_feats, "unified_row", errors

    return None, None, errors or ["no_feature_source"]
