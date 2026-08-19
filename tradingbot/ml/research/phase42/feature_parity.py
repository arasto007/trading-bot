"""Phase 42 — production feature parity audit (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.sparse_event_builder import patch_spread_features
from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.features.registry.registry import feature_names
from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles


def _prepare_htf_frames() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    cs = CandleStore(None)
    m15_raw = cs.load("XAUUSD", "M15")
    h4_raw = cs.load("XAUUSD", "H4")

    def _norm(frame: pd.DataFrame | None) -> pd.DataFrame | None:
        if frame is None or frame.empty:
            return None
        out = frame
        if not isinstance(out.index, pd.DatetimeIndex):
            if "timestamp" in out.columns:
                out = out.set_index("timestamp")
            elif "time" in out.columns:
                out = out.set_index("time")
        out = out.copy()
        out.index = pd.to_datetime(out.index, utc=True)
        return out.sort_index()

    return _norm(m15_raw), _norm(h4_raw)


def audit_feature_parity(
    df: pd.DataFrame,
    *,
    sample_size: int = 120,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare stored dataset features vs FeatureBuilder with full HTF context."""
    if df.empty:
        return {"verdict": "INSUFFICIENT_DATA", "samples": 0}

    work = df.copy()
    if "bar_index" not in work.columns:
        return {"verdict": "MISSING_BAR_INDEX", "samples": 0}

    n = min(sample_size, len(work))
    sample = work.sample(n, random_state=seed) if n < len(work) else work
    candles = resolve_fullest_candles()
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "samples": 0}

    m15, h4 = _prepare_htf_frames()
    builder = FeatureBuilder("XAUUSD", base_dir=None)
    feats = feature_columns(df)

    per_feature: dict[str, list[float]] = {f: [] for f in feats}
    for _, row in sample.iterrows():
        idx = int(row["bar_index"])
        built = builder.compute_at(candles, idx, h4_df=h4, m15_df=m15)
        for f in feats:
            per_feature[f].append(abs(float(row[f]) - float(built.get(f, 0.0))))

    metrics: list[dict[str, Any]] = []
    for f in feats:
        arr = np.array(per_feature[f], dtype=float)
        metrics.append({
            "feature": f,
            "mae": round(float(arr.mean()), 6),
            "max_abs_error": round(float(arr.max()), 6),
            "bit_equal_ratio": round(float((arr == 0.0).mean()), 4),
        })
    metrics.sort(key=lambda x: -x["mae"])

    spread_mismatch = [m for m in metrics if m["feature"].startswith("spread_") and m["mae"] > 0.001]
    non_spread_bad = [m for m in metrics if not m["feature"].startswith("spread_") and m["mae"] > 0.001]
    perfect = sum(1 for m in metrics if m["mae"] == 0.0)

    if non_spread_bad:
        verdict = "FEATURE_PARITY_BROKEN"
    elif spread_mismatch:
        verdict = "SPREAD_PROXY_FIXABLE"
    else:
        verdict = "FEATURE_PARITY_CONFIRMED"

    return {
        "verdict": verdict,
        "samples": n,
        "feature_count": len(feats),
        "perfect_features": perfect,
        "spread_mismatch_features": [m["feature"] for m in spread_mismatch],
        "non_spread_mismatch_features": [m["feature"] for m in non_spread_bad],
        "top_mismatches": metrics[:8],
        "all_metrics": metrics,
    }


def rebuild_spread_features(df: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """Patch spread_* columns using production bar-range proxy (vectorized)."""
    return patch_spread_features(df, candles, symbol="XAUUSD")


def build_dataset_v4(df: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """Create v4 dataset: v3 labels + spread features patched from production proxy."""
    out = rebuild_spread_features(df, candles)
    out["dataset_version"] = "v4_spread_patched"
    return out
