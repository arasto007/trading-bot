"""Storage integrity and tick ordering validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase30f.storage.manifest import ManifestStore


def detect_duplicate_timestamps(df: pd.DataFrame) -> int:
    if df.empty or "timestamp_ms" not in df.columns:
        return 0
    return int(df.duplicated(subset=["symbol", "timestamp_ms"]).sum())


def detect_tick_gaps(df: pd.DataFrame, threshold_ms: int) -> list[dict[str, Any]]:
    if df.empty or "timestamp_ms" not in df.columns:
        return []
    df = df.sort_values("timestamp_ms")
    gaps = []
    ts = df["timestamp_ms"].astype(int).tolist()
    sym = df["symbol"].iloc[0] if "symbol" in df.columns else ""
    for i in range(1, len(ts)):
        delta = ts[i] - ts[i - 1]
        if delta > threshold_ms:
            gaps.append(
                {
                    "symbol": sym,
                    "gap_start_ms": ts[i - 1],
                    "gap_end_ms": ts[i],
                    "gap_ms": delta,
                }
            )
    return gaps


def validate_tick_ordering(df: pd.DataFrame) -> bool:
    if df.empty:
        return True
    ts = df["timestamp_ms"].astype(int).tolist()
    return ts == sorted(ts)


def validate_clock_consistency(df: pd.DataFrame, *, max_future_ms: int = 60_000) -> list[str]:
    if df.empty:
        return []
    import time

    now_ms = int(time.time() * 1000)
    issues = []
    future = df[df["timestamp_ms"] > now_ms + max_future_ms]
    if len(future) > 0:
        issues.append(f"{len(future)} ticks in the future")
    return issues


def run_storage_validation(manifest: ManifestStore) -> dict[str, Any]:
    checks = manifest.verify_all()
    valid = all(c["valid"] for c in checks) if checks else True
    return {
        "manifest_files": len(checks),
        "all_checksums_valid": valid,
        "checks": checks,
    }
