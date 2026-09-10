"""Phase 22L — Step 2: rebuild dataset_v2 to research artifact (no production overwrite)."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

from tradingbot.ml.data.paths import dataset_v2_path, normalize_ml_base_dir
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig
from tradingbot.ml.dataset.sparse_event_builder import SparseEventDatasetBuilder
from tradingbot.ml.dataset.splitter import assign_purged_split_column
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset

PHASE22L_DIR = Path(__file__).resolve().parent
ARTIFACTS = PHASE22L_DIR / "artifacts"
OLD_SNAPSHOT = ARTIFACTS / "XAUUSD_M5_dataset_v2_old.parquet"
REFRESHED = ARTIFACTS / "XAUUSD_M5_dataset_v2_refreshed.parquet"


def _feature_stats(df: pd.DataFrame, cols: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in cols:
        if c not in df.columns:
            out[c] = {"present": False}
            continue
        s = df[c].astype(float)
        out[c] = {
            "present": True,
            "zero_pct": round(float((s.fillna(0).abs() < 1e-9).mean()) * 100, 2),
            "mean": round(float(s.mean()), 6),
            "std": round(float(s.std()), 6),
            "min": round(float(s.min()), 6),
            "max": round(float(s.max()), 6),
            "unique": int(s.nunique()),
        }
    return out


def snapshot_old_dataset(*, base_dir: str | None = None) -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    src = dataset_v2_path("XAUUSD", "M5", base_dir)
    if not src.is_file():
        raise FileNotFoundError(f"production dataset_v2 missing: {src}")
    shutil.copy2(src, OLD_SNAPSHOT)
    return OLD_SNAPSHOT


def rebuild_dataset_v2_research(*, base_dir: str | None = None) -> dict[str, Any]:
    """
    Full sparse-event rebuild using production pipeline classes.
    Writes ONLY to phase22l/artifacts/ — never production datasets_root.
    """
    from tradingbot.adapters.legacy_loader import load_legacy_config

    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(base_dir or legacy.get("BASE_DIR"))
    symbol, tf = "XAUUSD", "M5"
    cfg = DatasetBuildConfig(symbol=symbol, timeframe=tf)

    snapshot_old_dataset(base_dir=base_dir)
    old_df = pd.read_parquet(OLD_SNAPSHOT)
    old_df["timestamp"] = pd.to_datetime(old_df["timestamp"], utc=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Phase 22L sparse rebuild starting for %s %s", symbol, tf)
    sparse = SparseEventDatasetBuilder(config=cfg, base_dir=base_dir)
    v1_df, sparse_result = sparse.build(symbol)
    logger.info("Phase 22L sparse rebuild done rows=%s status=%s", sparse_result.row_count, sparse_result.status)

    if v1_df.empty or not sparse_result.passed:
        return {
            "phase": "22L",
            "step": 2,
            "status": "fail",
            "error": "sparse_build_failed",
            "sparse_result": sparse_result.to_dict(),
        }

    gate = DatasetSanityGate(min_samples=500)
    filtered, removed = gate.filter_dataset(v1_df, symbol=symbol, timeframe=tf)
    filtered = assign_purged_split_column(filtered, purge_bars=cfg.purge_bars, timeframe=tf)
    filtered = filtered[filtered["split"] != "purge"].copy()
    filtered["dataset_schema_version"] = DATASET_SCHEMA_VERSION
    filtered = filtered.sort_values(
        [c for c in ("timestamp", "event_id", "event_type") if c in filtered.columns]
    ).reset_index(drop=True)

    sanity_after = gate.evaluate(filtered, symbol, tf)
    val = validate_dataset(filtered)
    if sanity_after.blocked or val.status == "fail":
        return {
            "phase": "22L",
            "step": 2,
            "status": "fail",
            "error": "v2_sanity_or_validation_failed",
            "sanity_after": sanity_after.to_dict(),
            "validation": val.to_dict() if hasattr(val, "to_dict") else str(val),
        }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    filtered.to_parquet(REFRESHED, index=False)
    new_df = filtered.copy()
    new_df["timestamp"] = pd.to_datetime(new_df["timestamp"], utc=True)

    phase99 = ["ema50_slope", "candle_direction", "structure_distance"]
    old_ts = set(old_df["timestamp"])
    new_ts = set(new_df["timestamp"])
    added_ts = sorted(new_ts - old_ts)
    removed_ts = sorted(old_ts - new_ts)

    return {
        "phase": "22L",
        "step": 2,
        "status": "pass",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "production_unmodified": True,
        "output_path": str(REFRESHED),
        "old_snapshot_path": str(OLD_SNAPSHOT),
        "sparse_build": sparse_result.to_dict(),
        "rows_filtered_v2_gate": removed,
        "old_dataset": {
            "rows": len(old_df),
            "max_timestamp": str(old_df["timestamp"].max()),
            "min_timestamp": str(old_df["timestamp"].min()),
            "fingerprint": compute_dataset_fingerprint(old_df, cfg).to_dict(),
            "phase99_stats": _feature_stats(old_df, phase99),
        },
        "new_dataset": {
            "rows": len(new_df),
            "max_timestamp": str(new_df["timestamp"].max()),
            "min_timestamp": str(new_df["timestamp"].min()),
            "fingerprint": compute_dataset_fingerprint(new_df, cfg).to_dict(),
            "phase99_stats": _feature_stats(new_df, phase99),
        },
        "delta": {
            "row_delta": len(new_df) - len(old_df),
            "timestamps_added": len(added_ts),
            "timestamps_removed": len(removed_ts),
            "sample_added_timestamps": [str(t) for t in added_ts[:10]],
            "max_timestamp_extended": str(new_df["timestamp"].max()) != str(old_df["timestamp"].max()),
        },
        "sanity_after": sanity_after.to_dict(),
    }


def load_refreshed_dataset() -> pd.DataFrame:
    if not REFRESHED.is_file():
        raise FileNotFoundError("refreshed dataset not built — run rebuild first")
    df = pd.read_parquet(REFRESHED)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_old_snapshot() -> pd.DataFrame:
    df = pd.read_parquet(OLD_SNAPSHOT)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df
