"""Phase 16A — main feature distribution aligner API."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.feature_alignment.config import SHIFTED_FEATURES
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS
from tradingbot.ml.feature_alignment.feature_statistics import (
    FeatureStats,
    load_live_reference_statistics,
    load_training_statistics,
)
from tradingbot.ml.feature_alignment.quantile_mapper import QuantileMapper
from tradingbot.ml.feature_alignment.alignment_trace import AlignmentTrace


class DistributionAligner:
    """Inference-only aligner: maps shifted live features into training support."""

    def __init__(
        self,
        *,
        mappers: dict[str, QuantileMapper],
        shifted_features: tuple[str, ...] = SHIFTED_FEATURES,
    ) -> None:
        self._mappers = mappers
        self._shifted = shifted_features

    @classmethod
    def build(
        cls,
        *,
        base_dir: str | None = None,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
    ) -> "DistributionAligner":
        train = load_training_statistics(base_dir=base_dir, symbol=symbol, timeframe=timeframe)
        live = load_live_reference_statistics(base_dir=base_dir, symbol=symbol, timeframe=timeframe)
        mappers: dict[str, QuantileMapper] = {}
        for feat in SHIFTED_FEATURES:
            if feat in train and feat in live:
                mappers[feat] = QuantileMapper(live=live[feat], train=train[feat])
        return cls(mappers=mappers)

    @property
    def shifted_features(self) -> tuple[str, ...]:
        return self._shifted

    def align(
        self,
        features: dict[str, float] | pd.Series,
        *,
        trace: bool = False,
    ) -> dict[str, float] | tuple[dict[str, float], AlignmentTrace]:
        src = dict(features) if isinstance(features, pd.Series) else dict(features)
        out = {k: float(v) for k, v in src.items()}
        changes: list[dict[str, Any]] = []
        for feat in self._shifted:
            if feat not in out or feat not in self._mappers:
                continue
            before = float(out[feat])
            after = self._mappers[feat].map_value(before)
            out[feat] = after
            if trace:
                changes.append({
                    "feature": feat,
                    "before": round(before, 8),
                    "after": round(after, 8),
                    "delta": round(after - before, 8),
                })
        if trace:
            return out, AlignmentTrace(shifted=changes, passthrough=[f for f in out if f not in self._shifted])
        return out

    def align_row(self, row: pd.Series, *, trace: bool = False) -> pd.Series:
        feat_keys = [c for c in TREND_ML_FEATURE_COLUMNS if c in row.index]
        feats = {k: float(row.get(k, 0.0)) for k in feat_keys}
        if trace:
            aligned, _ = self.align(feats, trace=True)
        else:
            aligned = self.align(feats)  # type: ignore[assignment]
        merged = row.to_dict()
        merged.update(aligned)
        return pd.Series(merged)
