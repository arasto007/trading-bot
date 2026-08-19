"""Load labeled datasets for offline model training."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import dataset_path
from tradingbot.ml.dataset.schema import META_COLUMNS
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry.registry import feature_names

VALID_SPLITS = frozenset({"train", "validation", "test"})
RESOLVED_LABELS = frozenset({0, 1})

_EXCLUDE_FROM_FEATURES = frozenset(META_COLUMNS) | {
    "feature_schema_version",
    "dataset_schema_version",
}


@dataclass
class DatasetSplits:
    symbol: str
    timeframe: str
    feature_columns: list[str]
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    dataset_hash: str | None = None
    feature_version: str | None = None

    @property
    def X_train(self) -> pd.DataFrame:
        return self.train[self.feature_columns]

    @property
    def y_train(self) -> pd.Series:
        return self.train["label"].astype(int)

    @property
    def X_val(self) -> pd.DataFrame:
        return self.validation[self.feature_columns]

    @property
    def y_val(self) -> pd.Series:
        return self.validation["label"].astype(int)

    @property
    def X_test(self) -> pd.DataFrame:
        return self.test[self.feature_columns]

    @property
    def y_test(self) -> pd.Series:
        return self.test["label"].astype(int)


def resolve_feature_columns(df: pd.DataFrame) -> list[str]:
    registered = [c for c in feature_names() if c in df.columns]
    if registered:
        return registered
    return [c for c in df.columns if c not in _EXCLUDE_FROM_FEATURES]


def load_dataset_splits(
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> DatasetSplits:
    """
    Load dataset parquet and split by `split` column.

    - Only label in {0, 1}
    - Ignores purge rows
    - Never shuffles
    """
    store = DatasetStore(base_dir)
    df = store.load(symbol, timeframe)
    if df is None or df.empty:
        raise FileNotFoundError(f"Dataset not found: {dataset_path(symbol, timeframe, base_dir)}")

    if "label" not in df.columns or "split" not in df.columns:
        raise ValueError("Dataset missing required columns: label, split")

    work = df[df["label"].isin(RESOLVED_LABELS)].copy()
    work = work[work["split"].isin(VALID_SPLITS)].copy()

    if "timestamp" in work.columns:
        work = work.sort_values("timestamp")

    feature_cols = resolve_feature_columns(work)
    if not feature_cols:
        raise ValueError("No feature columns found in dataset")

    train = work[work["split"] == "train"].copy()
    val = work[work["split"] == "validation"].copy()
    test = work[work["split"] == "test"].copy()

    manifest = store.load_build_manifest(symbol, timeframe)
    return DatasetSplits(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        feature_columns=feature_cols,
        train=train,
        validation=val,
        test=test,
        dataset_hash=manifest.get("dataset_hash"),
        feature_version=manifest.get("feature_version"),
    )


def class_weights_from_labels(y: pd.Series | Any) -> dict[int, float]:
    """Compute sklearn-style class weights for imbalance."""
    counts = y.value_counts()
    total = len(y)
    weights: dict[int, float] = {}
    for cls in (0, 1):
        n = counts.get(cls, 0)
        weights[cls] = total / (2 * n) if n > 0 else 1.0
    return weights
