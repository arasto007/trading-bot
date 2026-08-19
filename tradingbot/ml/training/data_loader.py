"""Dataset v2 loader and train/val/test batching for Phase 8.6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.dataset.splitter import verify_chronological_splits
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names

RESOLVED_LABELS = {int(Label.SL_FIRST), int(Label.TP_FIRST)}
TRAIN_SPLIT = "train"
VAL_SPLIT = "validation"
TEST_SPLIT = "test"
PURGE_SPLIT = "purge"


@dataclass(frozen=True)
class TrainingSplits:
    """Resolved-label rows partitioned by the dataset split column."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    feature_columns: tuple[str, ...]
    symbol: str
    timeframe: str

    def feature_matrix(self, split: str) -> tuple[pd.DataFrame, pd.Series]:
        frame = self._frame_for_split(split)
        X = frame.loc[:, list(self.feature_columns)].astype(np.float64)
        y = frame["label"].astype(int)
        return X, y

    def _frame_for_split(self, split: str) -> pd.DataFrame:
        if split == TRAIN_SPLIT:
            return self.train
        if split == VAL_SPLIT:
            return self.validation
        if split == TEST_SPLIT:
            return self.test
        raise ValueError(f"Unknown split: {split}")

    def train_xy(self) -> tuple[pd.DataFrame, pd.Series]:
        return self.feature_matrix(TRAIN_SPLIT)

    def validation_xy(self) -> tuple[pd.DataFrame, pd.Series]:
        return self.feature_matrix(VAL_SPLIT)

    def test_xy(self) -> tuple[pd.DataFrame, pd.Series]:
        return self.feature_matrix(TEST_SPLIT)


def resolve_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return registry feature columns present in the dataset, in stable order."""
    names = feature_names()
    missing = [c for c in names if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing required feature columns: {missing[:5]}")
    return list(names)


def filter_resolved_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only TP/SL resolved labels and non-purge splits."""
    if "label" not in df.columns:
        raise ValueError("Dataset missing label column")
    if "split" not in df.columns:
        raise ValueError("Dataset missing split column")
    mask = df["label"].isin(RESOLVED_LABELS) & (df["split"] != PURGE_SPLIT)
    out = df.loc[mask].copy()
    if out.empty:
        raise ValueError("No resolved labels remain after filtering")
    return out


def validate_training_splits(df: pd.DataFrame) -> None:
    """Ensure chronological ordering and required partitions exist."""
    if not verify_chronological_splits(df):
        raise ValueError("Dataset splits are not chronologically ordered")
    for name in (TRAIN_SPLIT, VAL_SPLIT, TEST_SPLIT):
        count = int((df["split"] == name).sum())
        if count == 0:
            raise ValueError(f"Training dataset has no rows in split={name!r}")


def load_dataset_v2_splits(
    symbol: str,
    timeframe: str,
    base_dir: str | None = None,
) -> TrainingSplits:
    """Load dataset v2 and return train/validation/test partitions."""
    store = DatasetStore(base_dir)
    df = store.load_v2(symbol, timeframe)
    if df is None or df.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")
    filtered = filter_resolved_labels(df)
    if filtered.empty:
        raise ValueError("Dataset v2 has no resolved labels after filtering")
    validate_training_splits(filtered)
    cols = resolve_feature_columns(filtered)
    train_df = filtered.loc[filtered["split"] == TRAIN_SPLIT].reset_index(drop=True)
    val_df = filtered.loc[filtered["split"] == VAL_SPLIT].reset_index(drop=True)
    test_df = filtered.loc[filtered["split"] == TEST_SPLIT].reset_index(drop=True)
    return TrainingSplits(
        train=train_df,
        validation=val_df,
        test=test_df,
        feature_columns=tuple(cols),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
    )


def batch_iterator(
    X: np.ndarray,
    y: np.ndarray,
    *,
    batch_size: int = 256,
    shuffle: bool = False,
    seed: int = 42,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield mini-batches for optional iterative trainers (CPU-only)."""
    n = len(X)
    if n == 0:
        return
    indices = np.arange(n)
    if shuffle:
        rng = np.random.default_rng(seed)
        rng.shuffle(indices)
    for start in range(0, n, batch_size):
        idx = indices[start : start + batch_size]
        yield X[idx], y[idx]


def assert_no_test_leakage(splits: TrainingSplits) -> None:
    """Verify test timestamps do not overlap train/validation windows."""
    train_max = splits.train["timestamp"].max()
    val_max = splits.validation["timestamp"].max()
    test_min = splits.test["timestamp"].min()
    if test_min <= train_max or test_min <= val_max:
        raise ValueError("Test split timestamps overlap train/validation (leakage risk)")
