"""Phase 3 supervised dataset construction and event-based labeling."""

from tradingbot.ml.dataset.builder import DatasetBuilder
from tradingbot.ml.dataset.labels import LabelResult, label_from_future_candles, verify_rr_ratio
from tradingbot.ml.dataset.preflight import PreflightReport, run_preflight
from tradingbot.ml.dataset.schema import (
    DATASET_SCHEMA_VERSION,
    DatasetBuildConfig,
    Label,
    SAMPLE_EVENT_TYPES,
)
from tradingbot.ml.dataset.splitter import SplitResult, assign_split_column, time_based_split, verify_chronological_splits
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset, validate_dataset_schema

__all__ = [
    "DatasetBuilder",
    "DatasetBuildConfig",
    "DatasetStore",
    "Label",
    "LabelResult",
    "PreflightReport",
    "DATASET_SCHEMA_VERSION",
    "SAMPLE_EVENT_TYPES",
    "label_from_future_candles",
    "verify_rr_ratio",
    "time_based_split",
    "assign_split_column",
    "verify_chronological_splits",
    "SplitResult",
    "validate_dataset",
    "validate_dataset_schema",
    "run_preflight",
]
