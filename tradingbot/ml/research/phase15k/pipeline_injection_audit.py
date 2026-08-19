"""Phase 15K — pipeline injection audit (train vs inference path)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase15k.data_access import (
    bundle_probability,
    filter_probability,
    iter_trend_bars,
    load_frozen_bundle,
)


def audit_pipeline_injection(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    days: int = 365,
    stride: int = 15,
    max_checks: int = 200,
    **_: Any,
) -> dict[str, Any]:
    bundle = load_frozen_bundle(base_dir=base_dir)
    feature_order = list(bundle.feature_order)

    missing_counts: dict[str, int] = {f: 0 for f in feature_order}
    nan_counts: dict[str, int] = {f: 0 for f in feature_order}
    dtype_mismatches = 0
    reorder_mismatches = 0
    prob_deltas: list[float] = []
    checked = 0

    for _i, row, _ts in iter_trend_bars(candles, dataset, days=days, stride=stride):
        if checked >= max_checks:
            break
        checked += 1
        for f in feature_order:
            if f not in row.index:
                missing_counts[f] += 1
            val = row.get(f, np.nan)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                nan_counts[f] += 1
        p_bundle = bundle_probability(bundle, row)
        p_filter = filter_probability(row, bundle)
        prob_deltas.append(abs(p_bundle - p_filter))

        scaled_bundle = bundle.transform(row)
        cols_filter = [c for c in feature_order if c in row.index]
        if cols_filter != feature_order:
            reorder_mismatches += 1
        first_col = feature_order[0]
        if first_col in row.index:
            if str(row[first_col].dtype) not in ("float64", "float32", "int64", "int32"):
                dtype_mismatches += 1

    stored_order = feature_order
    training_order = list(bundle.metadata.get("feature_columns", feature_order))
    order_identical = stored_order == training_order

    max_delta = max(prob_deltas) if prob_deltas else 0.0
    normalization_mismatch = max_delta > 1e-6

    flags: list[str] = []
    if any(v > 0 for v in missing_counts.values()):
        flags.append("MISSING_FEATURES")
    if any(v > 0 for v in nan_counts.values()):
        flags.append("NAN_INJECTION")
    if normalization_mismatch:
        flags.append("NORMALIZATION_MISMATCH")
    if not order_identical:
        flags.append("FEATURE_REORDER")

    return {
        "phase": "15K",
        "bars_checked": checked,
        "missing_feature_counts": missing_counts,
        "nan_injection_counts": nan_counts,
        "dtype_cast_issues": dtype_mismatches,
        "feature_reorder_detected": reorder_mismatches > 0,
        "training_feature_order": training_order,
        "live_feature_order": stored_order,
        "feature_order_identical": order_identical,
        "bundle_vs_filter_max_delta": round(max_delta, 8),
        "bundle_vs_filter_mean_delta": round(float(np.mean(prob_deltas)) if prob_deltas else 0.0, 8),
        "normalization_mismatch": normalization_mismatch,
        "flags": flags,
        "pipeline_intact": len(flags) == 0,
    }
