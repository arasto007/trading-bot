"""Phase 8.1 production dataset build orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.roles import CONTEXT_TIMEFRAME, ENTRY_TIMEFRAME
from tradingbot.ml.dataset.builder import DatasetBuilder
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.hardening import run_dataset_hardening
from tradingbot.ml.dataset.preflight import run_preflight
from tradingbot.ml.dataset.report import save_dataset_quality_report
from tradingbot.ml.dataset.schema import DatasetBuildConfig
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset

logger = logging.getLogger(__name__)

EVENT_EXTRACTION_TIMEFRAMES: tuple[str, ...] = (ENTRY_TIMEFRAME, CONTEXT_TIMEFRAME)


@dataclass
class ProductionBuildResult:
    symbol: str
    timeframe: str
    status: str
    preflight: dict[str, Any] | None = None
    events: dict[str, str | None] = field(default_factory=dict)
    features_path: str | None = None
    dataset_path: str | None = None
    validation: dict[str, Any] | None = None
    fingerprint: dict[str, Any] | None = None
    hardening: dict[str, Any] | None = None
    manifest_path: str | None = None
    quality_report_path: str | None = None
    row_count: int = 0
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
            "preflight": self.preflight,
            "events": self.events,
            "features_path": self.features_path,
            "dataset_path": self.dataset_path,
            "validation": self.validation,
            "fingerprint": self.fingerprint,
            "hardening": self.hardening,
            "manifest_path": self.manifest_path,
            "quality_report_path": self.quality_report_path,
            "row_count": self.row_count,
            "errors": self.errors,
        }


class ProductionDatasetBuilder:
    """
    Orchestrate production dataset construction using existing Phase 2–3 modules.

    Flow: preflight → events → features → dataset → hardening → validation →
          fingerprint → manifest.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        *,
        timeframe: str = ENTRY_TIMEFRAME,
        base_dir: str | Path | None = None,
        config: DatasetBuildConfig | None = None,
        pipeline: MLDataPipeline | None = None,
        minimum_overrides: dict[str, int] | None = None,
        min_overlap_days: float = 30,
    ) -> None:
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.base_dir = base_dir
        self.config = config or DatasetBuildConfig(symbol=self.symbol, timeframe=self.timeframe)
        self._pipeline = pipeline or MLDataPipeline(base_dir=base_dir)
        self._minimum_overrides = minimum_overrides
        self._min_overlap_days = min_overlap_days

    def run_preflight(self) -> dict[str, Any]:
        report = run_preflight(
            self.symbol,
            base_dir=self.base_dir,
            minimum_overrides=self._minimum_overrides,
            min_overlap_days=self._min_overlap_days,
        )
        return report.to_dict()

    def validate_existing(self) -> dict[str, Any]:
        """Validate-only: inspect stored labeled dataset."""
        store = DatasetStore(self.base_dir)
        df = store.load(self.symbol, self.timeframe)
        if df is None or df.empty:
            return {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "status": "fail",
                "errors": ["no_dataset"],
            }

        val = validate_dataset(df)
        fingerprint = compute_dataset_fingerprint(df, self.config).to_dict()
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": val.status,
            "row_count": len(df),
            "validation": val.to_dict(),
            "fingerprint": fingerprint,
            "storage_path": str(store.resolve_path(self.symbol, self.timeframe)),
        }

    def build(self) -> ProductionBuildResult:
        result = ProductionBuildResult(symbol=self.symbol, timeframe=self.timeframe, status="fail")

        preflight = run_preflight(
            self.symbol,
            base_dir=self.base_dir,
            minimum_overrides=self._minimum_overrides,
            min_overlap_days=self._min_overlap_days,
        )
        result.preflight = preflight.to_dict()
        if not preflight.passed:
            result.errors.extend(preflight.issues)
            result.status = "fail"
            return result

        for tf in EVENT_EXTRACTION_TIMEFRAMES:
            try:
                path = self._pipeline.extract_and_store_events(self.symbol, tf)
                result.events[tf] = str(path) if path else None
                if path is None:
                    result.errors.append(f"events {tf}: no events extracted")
            except Exception as exc:
                result.errors.append(f"events {tf}: {exc}")
                result.events[tf] = None

        try:
            feature_path = self._pipeline.build_features(self.symbol, anchor_tf=self.timeframe)
        except Exception as exc:
            result.errors.append(f"features: {exc}")
            feature_path = None

        if feature_path is None:
            result.errors.append("feature build failed")
            result.status = "fail"
            return result
        result.features_path = str(feature_path)

        builder = DatasetBuilder(self.config, base_dir=self.base_dir)
        try:
            df = builder.build(self.symbol)
        except Exception as exc:
            result.errors.append(f"dataset build: {exc}")
            df = pd.DataFrame()

        if df is None or df.empty:
            result.errors.append("dataset build produced no rows")
            result.status = "fail"
            return result

        try:
            result.hardening = run_dataset_hardening(
                df,
                self.symbol,
                self.timeframe,
                self.config,
                base_dir=self.base_dir,
            )
        except Exception as exc:
            logger.warning("Hardening failed: %s", exc)
            result.errors.append(f"hardening: {exc}")

        val = validate_dataset(df)
        result.validation = val.to_dict()
        fp = compute_dataset_fingerprint(df, self.config)
        result.fingerprint = fp.to_dict()

        if val.status == "fail":
            result.errors.append("dataset validation failed")
            for issue in val.issues:
                if issue.severity == "error":
                    result.errors.append(f"{issue.code}: {issue.message}")
            result.status = "fail"
            return result

        store = DatasetStore(self.base_dir)
        dataset_path = store.store(self.symbol, self.timeframe, df)
        result.dataset_path = str(dataset_path)
        result.row_count = len(df)

        manifest = builder.build_manifest(
            self.symbol,
            self.timeframe,
            df,
            dataset_path=dataset_path,
            hardening=result.hardening or None,
        )
        manifest["build_phase"] = "8.1"
        manifest["build_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        manifest_path = store.save_build_manifest(self.symbol, self.timeframe, manifest)
        result.manifest_path = str(manifest_path)

        try:
            quality_path = save_dataset_quality_report(
                df,
                self.symbol,
                self.timeframe,
                base_dir=self.base_dir,
            )
            result.quality_report_path = str(quality_path)
        except Exception as exc:
            logger.warning("Quality report failed: %s", exc)

        result.status = "pass" if not result.errors else "warn"
        if val.status == "warn":
            result.status = "warn"
        return result
