"""Phase 22T — resolve phase99 range features from merge row or live FeatureBuilder."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
from tradingbot.ml.research.phase22t.config import PHASE99_FEATURES


def features_from_merge_row(row: pd.Series, feature_order: tuple[str, ...] | list[str]) -> dict[str, float]:
    mapped = row_for_phase99_range(row)
    return {f: float(mapped.get(f, 0.0)) for f in feature_order}


def features_from_live_candles(
    candles: pd.DataFrame,
    bar_index: int,
    *,
    symbol: str,
    base_dir: str | None,
    feature_order: tuple[str, ...] | list[str],
) -> dict[str, float]:
    fb = FeatureBuilder(symbol=symbol, base_dir=base_dir)
    live = fb.compute_at(candles, bar_index)
    return {f: float(live.get(f, 0.0)) for f in feature_order}


def build_range_eval_row(
    row: pd.Series,
    *,
    candles: pd.DataFrame | None,
    bar_index: int | None,
    use_live: bool,
    symbol: str,
    base_dir: str | None,
    feature_order: tuple[str, ...] | list[str],
) -> pd.Series:
    if use_live and candles is not None and bar_index is not None:
        live_feats = features_from_live_candles(
            candles, bar_index, symbol=symbol, base_dir=base_dir, feature_order=feature_order,
        )
        out = row.copy()
        for f, v in live_feats.items():
            out[f] = v
        return out
    return row_for_phase99_range(row)


def compare_feature_sources(
    *,
    candles: pd.DataFrame,
    unified_row: pd.Series,
    bar_index: int,
    symbol: str,
    base_dir: str | None,
) -> dict[str, Any]:
    merge = {f: features_from_merge_row(unified_row, (f,))[f] for f in PHASE99_FEATURES}
    live = features_from_live_candles(
        candles, bar_index, symbol=symbol, base_dir=base_dir, feature_order=PHASE99_FEATURES,
    )
    diffs = {f: abs(merge[f] - live[f]) for f in PHASE99_FEATURES}
    return {
        "merge": merge,
        "live": live,
        "abs_diff": diffs,
        "any_diff": any(d > 1e-6 for d in diffs.values()),
    }
