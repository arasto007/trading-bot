"""Feature store — processed tier parquet persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from tradingbot.ml.data.paths import feature_path, features_dir
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION

logger = logging.getLogger(__name__)

_SCHEMA_COLUMN = "feature_schema_version"


class FeatureStore:
    """Persist engineered features under data/ml/processed/features/."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = base_dir
        features_dir(base_dir).mkdir(parents=True, exist_ok=True)

    def resolve_path(self, symbol: str, timeframe: str) -> Path:
        return feature_path(symbol, timeframe, self._base)

    @staticmethod
    def attach_schema_version(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out[_SCHEMA_COLUMN] = FEATURE_SCHEMA_VERSION
        return out

    @staticmethod
    def read_schema_version(df: pd.DataFrame) -> str | None:
        if _SCHEMA_COLUMN not in df.columns:
            return None
        vals = df[_SCHEMA_COLUMN].dropna().unique()
        if len(vals) == 0:
            return None
        return str(vals[0])

    def store(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        path = self.resolve_path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = self.attach_schema_version(df)
        if not isinstance(out.index, pd.DatetimeIndex):
            if "time" in out.columns:
                out = out.set_index("time")
        out.index = pd.to_datetime(out.index, utc=True)
        out = out.sort_index()

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pandas(out, preserve_index=True)
            custom_meta = {
                b"feature_schema_version": FEATURE_SCHEMA_VERSION.encode("utf-8"),
            }
            existing = table.schema.metadata or {}
            merged = {**existing, **custom_meta}
            table = table.replace_schema_metadata(merged)
            pq.write_table(table, path)
        except Exception:
            out.to_parquet(path, index=True)

        logger.info("Stored features %s %s -> %s (%d rows)", symbol, timeframe, path, len(out))
        return path

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        path = self.resolve_path(symbol, timeframe)
        if not path.is_file():
            return None
        try:
            df = pd.read_parquet(path)
            if not isinstance(df.index, pd.DatetimeIndex):
                if "time" in df.columns:
                    df = df.set_index("time")
            df.index = pd.to_datetime(df.index, utc=True)
            return df.sort_index()
        except Exception as exc:
            logger.warning("Feature load failed %s: %s", path, exc)
            return None

    def read_parquet_metadata(self, symbol: str, timeframe: str) -> dict[str, str]:
        path = self.resolve_path(symbol, timeframe)
        if not path.is_file():
            return {}
        try:
            import pyarrow.parquet as pq

            meta = pq.read_metadata(path).metadata or {}
            return {k.decode("utf-8"): meta[k].decode("utf-8") for k in meta}
        except Exception:
            return {}

    def merge_store(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        existing = self.load(symbol, timeframe)
        if existing is None or existing.empty:
            return self.store(symbol, timeframe, df)
        merged = pd.concat([existing, df])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        feature_cols = [c for c in merged.columns if c != _SCHEMA_COLUMN]
        merged = merged[feature_cols]
        return self.store(symbol, timeframe, merged)
