"""Dataset fingerprinting — SHA256 hashes for reproducibility."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.schema import DatasetBuildConfig
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.features.registry.registry import feature_names


@dataclass
class DatasetFingerprint:
    dataset_hash: str
    feature_hash: str
    label_config_hash: str
    feature_version: str
    label_config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hash_dataframe_content(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    if df is None or df.empty:
        return ""
    cols = columns or list(df.columns)
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return ""
    work = df[cols].sort_index()
    payload = work.to_csv(index=False).encode("utf-8")
    return _sha256(payload)


def compute_label_config_hash(config: DatasetBuildConfig) -> str:
    payload = {
        "risk": "ATR",
        "tp": f"{config.tp_r_multiple}R",
        "sl": f"{config.sl_r_multiple}R",
        "window": config.future_window_bars,
        "atr_period": config.atr_period,
        "purge_bars": config.purge_bars,
    }
    return _sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))


def label_config_dict(config: DatasetBuildConfig) -> dict[str, Any]:
    return {
        "risk": "ATR",
        "tp": f"{config.tp_r_multiple}R",
        "sl": f"{config.sl_r_multiple}R",
        "window": config.future_window_bars,
        "atr_period": config.atr_period,
        "purge_bars": config.purge_bars,
    }


def compute_dataset_fingerprint(
    df: pd.DataFrame,
    config: DatasetBuildConfig,
) -> DatasetFingerprint:
    feature_cols = [c for c in feature_names() if c in df.columns]
    meta_cols = [
        "timestamp",
        "event_type",
        "entry_price",
        "direction",
        "stop_loss",
        "take_profit",
        "label",
        "future_window_bars",
        "tp_hit",
        "sl_hit",
        "mfe",
        "mae",
        "future_return",
        "split",
    ]
    label_cols = [c for c in meta_cols if c in df.columns]
    all_cols = label_cols + feature_cols

    label_cfg = label_config_dict(config)
    return DatasetFingerprint(
        dataset_hash=_hash_dataframe_content(df, all_cols),
        feature_hash=_hash_dataframe_content(df, feature_cols),
        label_config_hash=compute_label_config_hash(config),
        feature_version=FEATURE_SCHEMA_VERSION,
        label_config=label_cfg,
    )
