"""Parquet storage with zstd compression."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase30f.storage.checksums import sha256_file


class ParquetStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _partition_path(self, symbol: str, timestamp_ms: int) -> Path:
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        return (
            self.root
            / symbol
            / f"{dt.year:04d}"
            / f"{dt.month:02d}"
            / f"{dt.day:02d}"
        )

    def write_ticks(self, rows: list[dict[str, Any]], *, dedupe_key: str | None = None) -> tuple[int, Path | None]:
        if not rows:
            return 0, None
        df = pd.DataFrame(rows)
        if dedupe_key and dedupe_key in df.columns:
            df = df.drop_duplicates(subset=[dedupe_key], keep="last")
        ts = int(df["timestamp_ms"].iloc[0])
        part_dir = self._partition_path(str(df["symbol"].iloc[0]), ts)
        part_dir.mkdir(parents=True, exist_ok=True)
        out = part_dir / f"part-{ts}-{len(df)}.parquet"
        df.to_parquet(out, compression="zstd", index=False)
        return len(df), out

    def append_ticks_merge(
        self,
        symbol: str,
        rows: list[dict[str, Any]],
        *,
        existing_filter: set[int] | None = None,
    ) -> tuple[int, Path | None]:
        """Write ticks skipping timestamps in existing_filter."""
        filtered = []
        for r in rows:
            ts = int(r["timestamp_ms"])
            if existing_filter and ts in existing_filter:
                continue
            filtered.append(r)
        return self.write_ticks(filtered)

    def read_ticks(self, symbol: str) -> pd.DataFrame:
        base = self.root / symbol
        if not base.exists():
            return pd.DataFrame()
        files = sorted(base.rglob("*.parquet"))
        if not files:
            return pd.DataFrame()
        frames = [pd.read_parquet(f) for f in files]
        df = pd.concat(frames, ignore_index=True)
        if "timestamp_ms" in df.columns:
            df = df.sort_values("timestamp_ms")
        return df

    def write_table(self, rel_path: str, rows: list[dict[str, Any]]) -> Path:
        out = self.root / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(rows)
        df.to_parquet(out, compression="zstd", index=False)
        return out

    def verify_file(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"path": str(path), "exists": False, "valid": False}
        try:
            pd.read_parquet(path)
            return {
                "path": str(path),
                "exists": True,
                "valid": True,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        except Exception as exc:
            return {"path": str(path), "exists": True, "valid": False, "error": str(exc)}
