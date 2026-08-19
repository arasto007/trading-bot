"""Dataset parquet persistence under data/ml/datasets/."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import (
    dataset_build_manifest_path,
    dataset_path,
    dataset_v2_path,
    datasets_root,
)
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION

logger = logging.getLogger(__name__)


class DatasetStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = base_dir
        datasets_root(base_dir).mkdir(parents=True, exist_ok=True)

    def resolve_path(self, symbol: str, timeframe: str) -> Path:
        return dataset_path(symbol, timeframe, self._base)

    def resolve_v2_path(self, symbol: str, timeframe: str) -> Path:
        return dataset_v2_path(symbol, timeframe, self._base)

    def store(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        path = self.resolve_path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        if "dataset_schema_version" not in out.columns:
            out["dataset_schema_version"] = DATASET_SCHEMA_VERSION
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
            out = out.sort_values("timestamp")
        out.to_parquet(path, index=False)
        logger.info("Stored dataset %s %s -> %s (%d rows)", symbol, timeframe, path, len(out))
        return path

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        path = self.resolve_path(symbol, timeframe)
        if not path.is_file():
            return None
        try:
            df = pd.read_parquet(path)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            return df
        except Exception as exc:
            logger.warning("Dataset load failed %s: %s", path, exc)
            return None

    def store_v2(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        path = self.resolve_v2_path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        if "dataset_schema_version" not in out.columns:
            out["dataset_schema_version"] = DATASET_SCHEMA_VERSION
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
            sort_cols = [c for c in ("timestamp", "event_id") if c in out.columns]
            out = out.sort_values(sort_cols or ["timestamp"])
        out.to_parquet(path, index=False)
        logger.info("Stored dataset v2 %s %s -> %s (%d rows)", symbol, timeframe, path, len(out))
        from tradingbot.ml.dataset.memory_cache import DatasetMemoryCache

        DatasetMemoryCache.invalidate(str(path.resolve()))
        return path

    def _read_v2_parquet(self, path: Path) -> pd.DataFrame | None:
        try:
            df = pd.read_parquet(path)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            return df
        except Exception as exc:
            logger.warning("Dataset v2 load failed %s: %s", path, exc)
            return None

    def load_v2(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        path = self.resolve_v2_path(symbol, timeframe)
        if not path.is_file():
            return None
        from tradingbot.ml.dataset.memory_cache import (
            DatasetMemoryCache,
            dataset_memory_cache_enabled,
        )

        if not dataset_memory_cache_enabled():
            return self._read_v2_parquet(path)
        cache_key = str(path.resolve())
        return DatasetMemoryCache.load_v2(cache_key, path, self._read_v2_parquet)

    def save_build_manifest(
        self,
        symbol: str,
        timeframe: str,
        manifest: dict[str, Any],
    ) -> Path:
        path = dataset_build_manifest_path(symbol, timeframe, self._base)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_build_manifest(self, symbol: str, timeframe: str) -> dict[str, Any]:
        path = dataset_build_manifest_path(symbol, timeframe, self._base)
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
