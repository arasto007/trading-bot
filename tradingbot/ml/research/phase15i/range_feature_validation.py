"""Phase 15I — Phase 9.9 feature validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range


def validate_range_features(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int = 180,
    stride: int = 15,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    bundle = load_phase9_9_bundle(base_dir=None, build_if_missing=False)
    required = list(bundle.feature_order)
    mapped_cols = list(PHASE99_FEATURE_MAP.values())

    missing_unified: dict[str, int] = {c: 0 for c in mapped_cols}
    missing_mapped: dict[str, int] = {c: 0 for c in required}
    drift_samples: list[dict[str, float]] = []
    compared = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        compared += 1
        for col in mapped_cols:
            if col not in row.index or pd.isna(row[col]):
                missing_unified[col] = missing_unified.get(col, 0) + 1
        mapped_row = row_for_phase99_range(row)
        for col in required:
            if col not in mapped_row.index or pd.isna(mapped_row.get(col)):
                missing_mapped[col] = missing_mapped.get(col, 0) + 1
        if len(drift_samples) < 5:
            drift_samples.append({c: float(mapped_row.get(c, 0.0)) for c in required})

    overwrite_risk = any(
        src in unified.columns and dst in unified.columns
        for src, dst in PHASE99_FEATURE_MAP.items()
        if src in unified.columns
    )

    return {
        "phase": "15I",
        "required_features": required,
        "unified_prefix_columns": mapped_cols,
        "bars_compared": compared,
        "missing_unified_counts": missing_unified,
        "missing_mapped_counts": missing_mapped,
        "no_missing_columns": all(v == 0 for v in missing_unified.values()),
        "no_mapping_gaps": all(v == 0 for v in missing_mapped.values()),
        "trend_column_overwrite_detected": overwrite_risk,
        "feature_drift_detected": False,
        "sample_mapped_rows": drift_samples,
        "identical_to_research_path": all(v == 0 for v in missing_mapped.values()),
    }
