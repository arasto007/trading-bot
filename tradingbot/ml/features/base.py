"""Base types and causal helpers for the feature engineering layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

FEATURE_SCHEMA_VERSION = "2.0"
REGISTRY_VERSION = "2.0"


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    source: str
    description: str
    version: str
    family: str
    dtype: str = "float"
    nullable_policy: str = "zero_fill"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "version": self.version,
            "family": self.family,
            "dtype": self.dtype,
            "nullable_policy": self.nullable_policy,
        }


@dataclass
class FeatureRangeSpec:
    """Validation constraints for a single feature column."""

    name: str
    dtype: str = "float"
    nullable_policy: str = "zero_fill"
    min: float | None = None
    max: float | None = None
    allowed_values: list[float] | None = None


class FeatureFamily(Protocol):
    family_name: str

    def feature_definitions(self) -> list[FeatureDefinition]: ...

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]: ...


def truncated_df(df: pd.DataFrame, index: int) -> pd.DataFrame:
    """Return only data available at bar `index` (inclusive). No future access."""
    if df is None or df.empty:
        return df
    idx = max(0, min(int(index), len(df) - 1))
    return df.iloc[: idx + 1]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_atr_distance(price: float, level: float, atr: float) -> float:
    if atr <= 0:
        return 0.0
    return round((price - level) / atr, 6)
