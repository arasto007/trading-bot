"""Phase 8.2 dataset release manager — freeze validated datasets."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import dataset_release_dir, releases_root
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint, label_config_dict
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.features.registry.registry import all_features, feature_names


@dataclass
class DatasetReleaseResult:
    symbol: str
    timeframe: str
    version: str
    release_dir: str
    dataset_hash: str
    created_at_utc: str
    row_count: int
    files: dict[str, str] = field(default_factory=dict)
    status: str = "created"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _feature_schema_payload() -> dict[str, Any]:
    return {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_count": len(feature_names()),
        "features": [f.to_dict() for f in all_features()],
    }


class DatasetReleaseManager:
    """Create immutable frozen dataset releases under data/ml/releases/."""

    def __init__(
        self,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
        *,
        base_dir: str | Path | None = None,
        config: DatasetBuildConfig | None = None,
    ) -> None:
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.base_dir = base_dir
        self.config = config or DatasetBuildConfig(symbol=self.symbol, timeframe=self.timeframe)

    def release_path(self, version: str | int) -> Path:
        return dataset_release_dir(self.symbol, self.timeframe, version, self.base_dir)

    def create_release(
        self,
        df: pd.DataFrame,
        *,
        version: str | int = "1",
        research_report: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> DatasetReleaseResult:
        """
        Freeze dataset into an immutable release folder.

        Structure:
            XAUUSD_M5_v1/
                dataset.parquet
                fingerprint.json
                feature_schema.json
                label_config.json
                research_report.json
        """
        release_dir = self.release_path(version)
        if release_dir.exists():
            if not overwrite:
                raise FileExistsError(f"Release already exists: {release_dir}")
            shutil.rmtree(release_dir)

        release_dir.mkdir(parents=True, exist_ok=True)
        releases_root(self.base_dir).mkdir(parents=True, exist_ok=True)

        dataset_file = release_dir / "dataset.parquet"
        df.to_parquet(dataset_file, index=False)
        file_hash = _sha256_file(dataset_file)

        fp = compute_dataset_fingerprint(df, self.config)
        fingerprint_payload = {
            **fp.to_dict(),
            "parquet_sha256": file_hash,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "released_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "version": str(version).lstrip("v"),
            "row_count": len(df),
        }

        label_config = {
            **label_config_dict(self.config),
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
        }

        files: dict[str, str] = {}
        files["dataset.parquet"] = str(dataset_file)
        files["fingerprint.json"] = str(self._write_json(release_dir / "fingerprint.json", fingerprint_payload))
        files["feature_schema.json"] = str(
            self._write_json(release_dir / "feature_schema.json", _feature_schema_payload())
        )
        files["label_config.json"] = str(self._write_json(release_dir / "label_config.json", label_config))
        files["research_report.json"] = str(
            self._write_json(release_dir / "research_report.json", research_report or {})
        )

        return DatasetReleaseResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            version=str(version).lstrip("v"),
            release_dir=str(release_dir),
            dataset_hash=file_hash,
            created_at_utc=fingerprint_payload["released_at_utc"],
            row_count=len(df),
            files=files,
            status="created",
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> Path:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
