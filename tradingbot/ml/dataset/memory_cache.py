"""Phase 24E — in-process memory cache for dataset_v2 parquet loads."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)

ENV_ENABLE_DATASET_MEMORY_CACHE = "ENABLE_DATASET_MEMORY_CACHE"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def dataset_memory_cache_enabled() -> bool:
    return _env_bool(ENV_ENABLE_DATASET_MEMORY_CACHE, True)


def file_fingerprint(path: Path) -> str:
    """Cheap on-disk identity — changes when parquet is rewritten."""
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def dataset_content_fingerprint(df: pd.DataFrame) -> str:
    """Stable content fingerprint for cache invalidation parity checks."""
    import hashlib

    cols = sorted(df.columns.tolist())
    payload = f"{len(df)}|{cols}"
    if "timestamp" in df.columns and len(df):
        payload += f"|{df['timestamp'].iloc[0]}|{df['timestamp'].iloc[-1]}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class _CacheEntry:
    df: pd.DataFrame
    file_fingerprint: str
    content_fingerprint: str


class DatasetMemoryCache:
    """
    Process-wide cache for dataset_v2 loads.

    Invalidates when the on-disk file fingerprint changes, on reset(), or process restart.
    """

    _lock = threading.Lock()
    _entries: dict[str, _CacheEntry] = {}
    _loads_from_disk: int = 0
    _loads_from_memory: int = 0

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._entries.clear()
            cls._loads_from_disk = 0
            cls._loads_from_memory = 0

    @classmethod
    def invalidate(cls, cache_key: str) -> None:
        with cls._lock:
            cls._entries.pop(cache_key, None)

    @classmethod
    def stats(cls) -> dict[str, int]:
        with cls._lock:
            return {
                "entries": len(cls._entries),
                "loads_from_disk": cls._loads_from_disk,
                "loads_from_memory": cls._loads_from_memory,
            }

    @classmethod
    def load_v2(
        cls,
        cache_key: str,
        path: Path,
        loader: Callable[[Path], pd.DataFrame | None],
    ) -> pd.DataFrame | None:
        if not path.is_file():
            cls.invalidate(cache_key)
            return None

        fp = file_fingerprint(path)
        with cls._lock:
            entry = cls._entries.get(cache_key)
            if entry is not None and entry.file_fingerprint == fp:
                cls._loads_from_memory += 1
                return entry.df.copy()

        df = loader(path)
        if df is None:
            cls.invalidate(cache_key)
            return None

        content_fp = dataset_content_fingerprint(df)
        with cls._lock:
            cls._entries[cache_key] = _CacheEntry(
                df=df.copy(),
                file_fingerprint=fp,
                content_fingerprint=content_fp,
            )
            cls._loads_from_disk += 1
        return df.copy()

    @classmethod
    def load_v2_bypass_cache(cls, path: Path, loader: Callable[[Path], pd.DataFrame | None]) -> pd.DataFrame | None:
        """Direct disk read — rollback path matching pre-24E behavior."""
        if not path.is_file():
            return None
        df = loader(path)
        return df.copy() if df is not None else None
