"""Phase 9.3 — shared research utilities (read-only dataset access)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.training.data_loader import (
    TrainingSplits,
    assert_no_test_leakage,
    load_dataset_v2_splits,
)
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import DEFAULT_SEED

PHASE = "9.3"


@dataclass(frozen=True)
class ResearchContext:
    symbol: str
    timeframe: str
    base_dir: str | Path | None
    seed: int
    splits: TrainingSplits
    pipeline: FeaturePipeline
    model: Any
    model_metadata: dict[str, Any]
    dataset_snapshot_hash: str


def dataset_content_fingerprint(df: pd.DataFrame) -> str:
    """Stable fingerprint for verifying dataset was not mutated."""
    import hashlib

    cols = sorted(df.columns.tolist())
    payload = f"{len(df)}|{cols}|{df['label'].sum() if 'label' in df.columns else 0}"
    if "timestamp" in df.columns and len(df):
        payload += f"|{df['timestamp'].iloc[0]}|{df['timestamp'].iloc[-1]}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_research_context(
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> ResearchContext:
    """Load dataset splits, production model, and scaler without mutating data."""
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")

    fingerprint = dataset_content_fingerprint(raw)
    splits = load_dataset_v2_splits(symbol, timeframe, base_dir)
    assert_no_test_leakage(splits)

    from tradingbot.ml.training.phase9_production import load_production_bundle

    model, pipeline, metadata = load_production_bundle(base_dir)
    return ResearchContext(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        base_dir=base_dir,
        seed=seed,
        splits=splits,
        pipeline=pipeline,
        model=model,
        model_metadata=metadata,
        dataset_snapshot_hash=fingerprint,
    )


def scaled_split_arrays(
    ctx: ResearchContext,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Return scaled feature matrices and labels for train/validation/test."""
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for split in ("train", "validation", "test"):
        X, y = ctx.splits.feature_matrix(split)
        X_s = ctx.pipeline.transform(X)
        out[split] = (X_s, y.to_numpy(dtype=int))
    return out
