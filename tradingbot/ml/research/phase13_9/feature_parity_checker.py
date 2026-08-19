"""Phase 13.9 — feature parity between Phase 13.3 and legacy router frames."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP, TREND_PROTECTED_COLUMNS
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features


def _align(legacy: pd.DataFrame, unified: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ts = pd.to_datetime(legacy["timestamp"], utc=True)
    u_ts = pd.to_datetime(unified["timestamp"], utc=True)
    common = ts.isin(set(u_ts))
    l = legacy.loc[common].reset_index(drop=True)
    u = unified.merge(l[["timestamp"]], on="timestamp", how="inner").reset_index(drop=True)
    return l, u


def check_feature_parity(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
) -> dict[str, Any]:
    canonical = build_ml_features(candles)
    legacy = prepare_merged_frame(candles, dataset)
    unified = build_unified_frame(candles, dataset)

    legacy_a, unified_a = _align(legacy, unified)

    missing_in_router: list[str] = []
    drift_columns: list[dict[str, Any]] = []

    for col in TREND_PROTECTED_COLUMNS:
        if col not in legacy_a.columns:
            missing_in_router.append(col)
        if col not in unified_a.columns:
            continue
        if col not in legacy_a.columns:
            continue
        lv = legacy_a[col].astype(float)
        uv = unified_a[col].astype(float)
        diff = (lv - uv).abs()
        max_drift = float(diff.max()) if len(diff) else 0.0
        mean_drift = float(diff.mean()) if len(diff) else 0.0
        if max_drift > 1e-6:
            drift_columns.append(
                {
                    "column": col,
                    "max_abs_drift": round(max_drift, 6),
                    "mean_abs_drift": round(mean_drift, 6),
                    "legacy_sample": round(float(lv.iloc[len(lv) // 2]), 6),
                    "unified_sample": round(float(uv.iloc[len(uv) // 2]), 6),
                }
            )

    # Dataset overwrite detection
    overwrite_hits = 0
    if "ema50_slope" in legacy_a.columns and "ema50_slope" in canonical.columns:
        c_ts = canonical.set_index(pd.to_datetime(canonical["timestamp"], utc=True))
        for _, row in legacy_a.iterrows():
            ts = pd.Timestamp(row["timestamp"])
            if ts in c_ts.index:
                if abs(float(row["ema50_slope"]) - float(c_ts.loc[ts, "ema50_slope"])) > 0.01:
                    overwrite_hits += 1

    drift_columns.sort(key=lambda x: x["max_abs_drift"], reverse=True)

    return {
        "phase": "13.9",
        "answers": {
            "1_missing_in_router": missing_in_router,
            "2_value_drift_columns": drift_columns,
            "3_primary_cause": (
                "Legacy router prepare_merged_frame overwrites trend ema50_slope with dataset "
                f"values (detected {overwrite_hits} row drifts vs canonical)."
                if overwrite_hits > 0
                else "Column collision or merge suffix drift."
            ),
        },
        "legacy_rows": len(legacy),
        "unified_rows": len(unified),
        "canonical_rows": len(canonical),
        "phase99_prefix_map": PHASE99_FEATURE_MAP,
        "protected_trend_columns": list(TREND_PROTECTED_COLUMNS),
        "overwrite_drift_rows": overwrite_hits,
    }
