"""Phase 8.5 production dataset V2 builder — sanity-gated, deterministic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.builder import DatasetBuilder
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.production_builder import ProductionDatasetBuilder, ProductionBuildResult
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate, SanityReport
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig
from tradingbot.ml.dataset.splitter import assign_purged_split_column, verify_chronological_splits
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.train_readiness_report import TrainReadinessAnalyzer
from tradingbot.ml.dataset.validation import validate_dataset

logger = logging.getLogger(__name__)


@dataclass
class ProductionV2BuildResult:
    symbol: str
    timeframe: str
    status: str
    dataset_path: str | None = None
    source_build: dict[str, Any] | None = None
    sanity_before: dict[str, Any] | None = None
    sanity_after: dict[str, Any] | None = None
    train_readiness: dict[str, Any] | None = None
    fingerprint: dict[str, Any] | None = None
    row_count: int = 0
    rows_filtered: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "passed": self.passed,
            "dataset_path": self.dataset_path,
            "source_build": self.source_build,
            "sanity_before": self.sanity_before,
            "sanity_after": self.sanity_after,
            "train_readiness": self.train_readiness,
            "fingerprint": self.fingerprint,
            "row_count": self.row_count,
            "rows_filtered": self.rows_filtered,
            "errors": self.errors,
        }


def _deterministic_sort(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    sort_cols = [c for c in ("timestamp", "event_id", "event_type") if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols).reset_index(drop=True)
    return out


class ProductionDatasetV2Builder:
    """
    Build training-ready dataset V2 using Phase 8.1 pipeline + sanity gate.

    Flow: Phase 8.1 build (or load existing) → sanity → filter → deterministic split →
          sanity → train readiness → store v2 parquet.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        *,
        timeframe: str = "M5",
        base_dir: str | Path | None = None,
        config: DatasetBuildConfig | None = None,
        min_samples: int = 500,
        rebuild_source: bool = False,
    ) -> None:
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.base_dir = base_dir
        self.config = config or DatasetBuildConfig(symbol=self.symbol, timeframe=self.timeframe)
        self._gate = DatasetSanityGate(min_samples=min_samples)
        self._readiness = TrainReadinessAnalyzer(min_samples=min_samples)
        self._store = DatasetStore(base_dir)
        self._v1 = ProductionDatasetBuilder(
            symbol,
            timeframe=timeframe,
            base_dir=base_dir,
            config=self.config,
        )
        self.rebuild_source = rebuild_source

    def run_sanity(self, df: pd.DataFrame | None = None) -> SanityReport:
        if df is None:
            df = self._store.load(self.symbol, self.timeframe)
        if df is None or df.empty:
            df = self._store.load_v2(self.symbol, self.timeframe)
        if df is None or df.empty:
            return self._gate.evaluate(pd.DataFrame(), self.symbol, self.timeframe)
        return self._gate.evaluate(df, self.symbol, self.timeframe)

    def build_v2(self) -> ProductionV2BuildResult:
        result = ProductionV2BuildResult(symbol=self.symbol, timeframe=self.timeframe, status="fail")

        df: pd.DataFrame | None = None
        if self.rebuild_source:
            v1_result: ProductionBuildResult = self._v1.build()
            result.source_build = v1_result.to_dict()
            if not v1_result.passed and v1_result.status == "fail":
                result.errors.append("v1_build_failed")
                result.errors.extend(v1_result.errors)
                return result
            df = self._store.load(self.symbol, self.timeframe)
        else:
            df = self._store.load(self.symbol, self.timeframe)
            if df is None or df.empty:
                builder = DatasetBuilder(self.config, base_dir=self.base_dir)
                df = builder.build(self.symbol)

        if df is None or df.empty:
            result.errors.append("no_source_dataset")
            return result

        sanity_before = self._gate.evaluate(df, self.symbol, self.timeframe)
        result.sanity_before = sanity_before.to_dict()

        filtered, removed = self._gate.filter_dataset(df, symbol=self.symbol, timeframe=self.timeframe)
        result.rows_filtered = removed

        if filtered.empty:
            result.errors.append("all_rows_filtered")
            return result

        filtered = assign_purged_split_column(
            filtered,
            purge_bars=self.config.purge_bars,
            timeframe=self.timeframe,
        )
        filtered = filtered[filtered["split"] != "purge"].copy()
        filtered = _deterministic_sort(filtered)
        filtered["dataset_schema_version"] = DATASET_SCHEMA_VERSION

        sanity_after = self._gate.evaluate(filtered, self.symbol, self.timeframe)
        result.sanity_after = sanity_after.to_dict()
        if sanity_after.blocked:
            result.errors.append("sanity_gate_blocked")
            for issue in sanity_after.issues:
                if issue.severity == "error":
                    result.errors.append(f"{issue.code}: {issue.message}")
            return result

        val = validate_dataset(filtered)
        if val.status == "fail":
            result.errors.append("validation_failed")
            return result

        if not verify_chronological_splits(filtered):
            result.errors.append("split_not_chronological")
            return result

        readiness, readiness_path = self._readiness.analyze_and_save(
            filtered, self.symbol, self.timeframe, self.base_dir
        )
        result.train_readiness = readiness.to_dict()

        path = self._store.store_v2(self.symbol, self.timeframe, filtered)
        result.dataset_path = str(path)
        result.row_count = len(filtered)
        result.fingerprint = compute_dataset_fingerprint(filtered, self.config).to_dict()

        manifest = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "build_phase": "8.5",
            "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rows_filtered": removed,
            "row_count": len(filtered),
            "dataset_path": str(path),
            "train_readiness_path": str(readiness_path),
            "fingerprint": result.fingerprint,
            "sanity_after": sanity_after.to_dict(),
        }
        self._store.save_build_manifest(self.symbol, f"{self.timeframe}_V2", manifest)

        result.status = "pass" if readiness.recommended_for_training else "warn"
        if not readiness.dataset_valid:
            result.status = "warn"
        return result
