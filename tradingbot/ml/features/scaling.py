"""Scaler metadata — fit statistics only; raw features are never scaled on disk."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import scaler_metadata_path, scalers_dir
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.features.registry.registry import feature_names

logger = logging.getLogger(__name__)

ScalingMethod = Literal["standard", "minmax", "robust"]


@dataclass
class ColumnScalerMeta:
    name: str
    method: str
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    median: float | None = None
    iqr: float | None = None
    q25: float | None = None
    q75: float | None = None


@dataclass
class ScalerMetadata:
    symbol: str
    timeframe: str
    feature_schema_version: str
    methods: list[str]
    columns: list[ColumnScalerMeta] = field(default_factory=list)
    row_count: int = 0
    generated_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["columns"] = [asdict(c) for c in self.columns]
        return payload


def _stats(series: pd.Series) -> dict[str, float]:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {
            "mean": 0.0,
            "std": 1.0,
            "min": 0.0,
            "max": 0.0,
            "median": 0.0,
            "q25": 0.0,
            "q75": 0.0,
            "iqr": 1.0,
        }
    q25 = float(clean.quantile(0.25))
    q75 = float(clean.quantile(0.75))
    std = float(clean.std())
    return {
        "mean": float(clean.mean()),
        "std": std if std > 0 else 1.0,
        "min": float(clean.min()),
        "max": float(clean.max()),
        "median": float(clean.median()),
        "q25": q25,
        "q75": q75,
        "iqr": max(q75 - q25, 1e-9),
    }


def fit_scaler_metadata(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    methods: tuple[ScalingMethod, ...] = ("standard", "minmax", "robust"),
    feature_columns: list[str] | None = None,
) -> ScalerMetadata:
    """
    Compute scaler statistics for training-time use.

    Does NOT modify or return scaled data.
    """
    cols = feature_columns or [c for c in feature_names() if c in df.columns]
    meta_cols: list[ColumnScalerMeta] = []
    primary_method = methods[0] if methods else "standard"

    for col in cols:
        st = _stats(df[col])
        meta_cols.append(
            ColumnScalerMeta(
                name=col,
                method=primary_method,
                mean=st["mean"],
                std=st["std"],
                min=st["min"],
                max=st["max"],
                median=st["median"],
                iqr=st["iqr"],
                q25=st["q25"],
                q75=st["q75"],
            )
        )

    return ScalerMetadata(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        methods=list(methods),
        columns=meta_cols,
        row_count=len(df),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
    )


def transform_with_metadata(
    df: pd.DataFrame,
    meta: ScalerMetadata,
    method: ScalingMethod = "standard",
) -> pd.DataFrame:
    """In-memory transform helper for model training — not used for parquet storage."""
    out = df.copy()
    col_map = {c.name: c for c in meta.columns}
    for col in out.columns:
        if col not in col_map:
            continue
        cm = col_map[col]
        if method == "standard":
            out[col] = (out[col] - (cm.mean or 0.0)) / max(cm.std or 1.0, 1e-9)
        elif method == "minmax":
            denom = max((cm.max or 0.0) - (cm.min or 0.0), 1e-9)
            out[col] = (out[col] - (cm.min or 0.0)) / denom
        elif method == "robust":
            out[col] = (out[col] - (cm.median or 0.0)) / max(cm.iqr or 1.0, 1e-9)
    return out


def save_scaler_metadata(meta: ScalerMetadata, base_dir: str | Path | None = None) -> Path:
    scalers_dir(base_dir).mkdir(parents=True, exist_ok=True)
    path = scaler_metadata_path(meta.symbol, meta.timeframe, base_dir)
    path.write_text(json.dumps(meta.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved scaler metadata -> %s", path)
    return path


def load_scaler_metadata(symbol: str, timeframe: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = scaler_metadata_path(symbol, timeframe, base_dir)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
