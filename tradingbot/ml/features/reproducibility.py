"""Build reproducibility metadata for feature datasets."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import feature_build_manifest_path
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.features.registry.registry import registry_version


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_dataframe(df: pd.DataFrame) -> str:
    """Stable SHA256 hash of OHLCV content for reproducibility tracking."""
    if df is None or df.empty:
        return ""
    work = df.sort_index()
    payload = work[["open", "high", "low", "close"]].astype("float64").to_csv().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_commit_hash() -> str | None:
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


def build_manifest(
    symbol: str,
    timeframe: str,
    *,
    source_candles: dict[str, pd.DataFrame | None],
    feature_path: str | Path,
    row_count: int,
    feature_count: int,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    candle_hashes = {
        tf: hash_dataframe(df) for tf, df in source_candles.items() if df is not None and not df.empty
    }
    manifest = {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_registry_version": registry_version(),
        "build_timestamp_utc": _now_iso(),
        "git_commit": git_commit_hash(),
        "source_candle_hashes": candle_hashes,
        "feature_storage_path": str(feature_path),
        "row_count": row_count,
        "feature_count": feature_count,
    }
    path = feature_build_manifest_path(symbol, timeframe, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def load_manifest(symbol: str, timeframe: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = feature_build_manifest_path(symbol, timeframe, base_dir)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
