"""Phase 9.1 — production dataset build from verified 5Y historical candles."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.historical_quality_validator import (
    HistoricalQualityValidator,
    normalize_candles,
    production_date_range,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.data.paths import (
    dataset_path,
    dataset_v2_path,
    datasets_root,
    reports_dir,
)
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.label_quality import LabelQualityValidator
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor, save_leakage_audit
from tradingbot.ml.dataset.preflight import run_preflight
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.report import build_dataset_quality_report, save_dataset_quality_report
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig, META_COLUMNS
from tradingbot.ml.dataset.sparse_event_builder import (
    SparseEventDatasetBuilder,
    filter_candles_to_production_window,
    patch_spread_features,
)
from tradingbot.ml.dataset.splitter import verify_chronological_splits, verify_purge_gaps
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset
from tradingbot.ml.features.registry.registry import feature_names, validate_integrity

logger = logging.getLogger(__name__)

PHASE9_REPORT_FILES = (
    "dataset_build_report.json",
    "dataset_quality_report.json",
    "leakage_report.json",
    "label_quality_report.json",
)

ARCHIVE_DIR_NAME = "archive"
DEPRECATED_V1_NAME = "XAUUSD_M5_dataset_v1_deprecated.parquet"


@dataclass
class Phase91BuildResult:
    symbol: str
    timeframe: str
    status: str
    phase: str = "9.1"
    preflight: dict[str, Any] | None = None
    historical_quality: dict[str, Any] | None = None
    source_build: dict[str, Any] | None = None
    v2_build: dict[str, Any] | None = None
    sanity_gate: dict[str, Any] | None = None
    leakage_audit: dict[str, Any] | None = None
    label_quality: dict[str, Any] | None = None
    feature_validation: dict[str, Any] | None = None
    fingerprint: dict[str, Any] | None = None
    dataset_path: str | None = None
    row_count: int = 0
    feature_count: int = 0
    split_distribution: dict[str, int] = field(default_factory=dict)
    label_distribution: dict[str, int] = field(default_factory=dict)
    reports: dict[str, str] = field(default_factory=dict)
    archived_v1: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "phase": self.phase,
            "status": self.status,
            "passed": self.passed,
            "preflight": self.preflight,
            "historical_quality": self.historical_quality,
            "source_build": self.source_build,
            "v2_build": self.v2_build,
            "sanity_gate": self.sanity_gate,
            "leakage_audit": self.leakage_audit,
            "label_quality": self.label_quality,
            "feature_validation": self.feature_validation,
            "fingerprint": self.fingerprint,
            "dataset_path": self.dataset_path,
            "row_count": self.row_count,
            "feature_count": self.feature_count,
            "split_distribution": self.split_distribution,
            "label_distribution": self.label_distribution,
            "reports": self.reports,
            "archived_v1": self.archived_v1,
            "errors": self.errors,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }


def _phase9_report_path(name: str, base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / name


def _save_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def archive_deprecated_v1(symbol: str, timeframe: str, base_dir: str | Path | None = None) -> str | None:
    """Move placeholder v1 dataset to archive — must not be used for training."""
    src = dataset_path(symbol, timeframe, base_dir)
    if not src.is_file():
        return None

    archive_dir = datasets_root(base_dir) / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / DEPRECATED_V1_NAME

    if dest.is_file():
        dest.unlink()
    shutil.move(str(src), str(dest))

    readme = {
        "status": "DEPRECATED",
        "reason": "Phase 9.1 placeholder — OHLCV-only v1, not labeled, not on 5Y MT5 data",
        "archived_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_path": str(src),
        "archive_path": str(dest),
        "replacement": str(dataset_v2_path(symbol, timeframe, base_dir)),
        "do_not_use_for_training": True,
    }
    _save_json(archive_dir / "DEPRECATED_v1_README.json", readme)
    logger.info("Archived deprecated v1 dataset: %s -> %s", src, dest)
    return str(dest)


class Phase91ProductionBuilder:
    """
    End-to-end Phase 9.1 dataset pipeline:

    preflight → historical quality → v1 source build → v2 split/hardening →
    sanity → leakage → label quality → reports → archive v1 placeholder.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        *,
        timeframe: str = "M5",
        base_dir: str | Path | None = None,
        config: DatasetBuildConfig | None = None,
        min_samples: int = 500,
    ) -> None:
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.base_dir = base_dir
        self.config = config or DatasetBuildConfig(symbol=self.symbol, timeframe=self.timeframe)
        self._store = DatasetStore(base_dir)
        self._sparse_builder = SparseEventDatasetBuilder(config=self.config, base_dir=base_dir)
        self._v2_builder = ProductionDatasetV2Builder(
            self.symbol,
            timeframe=self.timeframe,
            base_dir=base_dir,
            config=self.config,
            min_samples=min_samples,
            rebuild_source=False,
        )

    def run_preflight_checks(self) -> tuple[dict[str, Any], dict[str, Any], bool]:
        preflight = run_preflight(self.symbol, base_dir=self.base_dir).to_dict()

        validator = HistoricalQualityValidator(base_dir=self.base_dir)
        hq = validator.validate_all(self.symbol, check_date_range=False)
        hq_dict = hq.to_dict()

        ok = bool(preflight.get("passed")) and bool(hq.passed)
        return preflight, hq_dict, ok

    def _validate_features(self, df: pd.DataFrame) -> dict[str, Any]:
        expected = feature_names()
        present = [c for c in expected if c in df.columns]
        missing = [c for c in expected if c not in df.columns]
        integrity = validate_integrity()
        meta_set = set(META_COLUMNS)
        leaked_meta_in_features = [c for c in present if c in {"future_return", "tp_hit", "sl_hit", "mfe", "mae"}]
        return {
            "status": "pass" if not missing and not integrity and not leaked_meta_in_features else "fail",
            "expected_count": len(expected),
            "present_count": len(present),
            "missing_features": missing,
            "registry_integrity_issues": integrity,
            "forbidden_in_feature_columns": leaked_meta_in_features,
        }

    def build(self, *, archive_v1: bool = True) -> Phase91BuildResult:
        result = Phase91BuildResult(symbol=self.symbol, timeframe=self.timeframe, status="fail")

        preflight, hq, preflight_ok = self.run_preflight_checks()
        result.preflight = preflight
        result.historical_quality = hq
        if not preflight_ok:
            result.errors.append("preflight_failed")
            result.errors.extend(preflight.get("issues", []))
            result.errors.extend(hq.get("issues", []))
            self._write_reports(result)
            return result

        v1_df, sparse_result, v1_path = self._sparse_builder.build_and_store(self.symbol, self.timeframe)
        result.source_build = sparse_result.to_dict()
        if v1_path:
            result.source_build["dataset_path"] = str(v1_path)
        if not sparse_result.passed or v1_df.empty:
            result.errors.append("sparse_source_build_failed")
            result.errors.extend(sparse_result.errors)
            self._write_reports(result)
            return result

        v2_result = self._v2_builder.build_v2()
        result.v2_build = v2_result.to_dict()
        v2_ok = v2_result.passed or (
            v2_result.status in ("pass", "warn")
            and v2_result.dataset_path
            and not any(e for e in v2_result.errors if "sanity_gate_blocked" in e)
        )
        if not v2_ok:
            result.errors.append("v2_build_failed")
            result.errors.extend(v2_result.errors)
            self._write_reports(result)
            return result

        df = self._store.load_v2(self.symbol, self.timeframe)
        if df is None or df.empty:
            result.errors.append("v2_dataset_missing_after_build")
            self._write_reports(result)
            return result

        return self._complete_validation(result, df, archive_v1=archive_v1)

    def finalize(self, *, archive_v1: bool = True) -> Phase91BuildResult:
        """Validate and report on an existing v2 dataset without rebuilding."""
        result = Phase91BuildResult(symbol=self.symbol, timeframe=self.timeframe, status="fail")

        df = self._store.load_v2(self.symbol, self.timeframe)
        if df is None or df.empty:
            result.errors.append("v2_dataset_missing")
            self._write_reports(result)
            return result

        m5 = normalize_candles(CandleStore(self.base_dir).load(self.symbol, self.timeframe))
        if m5 is not None and not m5.empty:
            start, end = production_date_range()
            m5_window = filter_candles_to_production_window(m5, start=start, end=end)
            df = patch_spread_features(df, m5_window, self.symbol)
            path = self._store.store_v2(self.symbol, self.timeframe, df)
            result.source_build = {"patched_spread_features": True, "dataset_path": str(path)}

        return self._complete_validation(result, df, archive_v1=archive_v1)

    def _complete_validation(
        self,
        result: Phase91BuildResult,
        df: pd.DataFrame,
        *,
        archive_v1: bool,
    ) -> Phase91BuildResult:
        sanity = DatasetSanityGate(min_samples=500, imbalance_warn=0.34).evaluate(df, self.symbol, self.timeframe)
        result.sanity_gate = sanity.to_dict()
        if sanity.blocked:
            result.errors.append("sanity_gate_blocked")
            for issue in sanity.issues:
                if issue.severity == "error":
                    result.errors.append(f"{issue.code}: {issue.message}")
            self._write_reports(result, df=df)
            return result
        if sanity.status == "fail":
            result.errors.append("sanity_gate_failed")
            self._write_reports(result, df=df)
            return result

        leakage = DatasetLeakageAuditor().audit(df, self.symbol, self.timeframe)
        result.leakage_audit = leakage.to_dict()
        if leakage.status == "fail":
            result.errors.append("leakage_audit_failed")
            result.errors.extend(leakage.issues)
            self._write_reports(result, df=df)
            return result

        label_q = LabelQualityValidator().validate(df)
        result.label_quality = label_q.to_dict()
        if label_q.status == "fail":
            result.errors.append("label_quality_failed")
            result.errors.extend(label_q.issues)

        feat_val = self._validate_features(df)
        result.feature_validation = feat_val
        if feat_val["status"] == "fail":
            result.errors.append("feature_validation_failed")
            if feat_val.get("missing_features"):
                result.errors.append(f"missing_features: {feat_val['missing_features']}")

        val = validate_dataset(df)
        if val.status == "fail":
            result.errors.append("dataset_validation_failed")

        if not verify_chronological_splits(df):
            result.errors.append("split_not_chronological")
        if not verify_purge_gaps(df, purge_bars=self.config.purge_bars, timeframe=self.timeframe):
            result.errors.append("purge_gaps_insufficient")

        result.dataset_path = str(self._store.resolve_v2_path(self.symbol, self.timeframe))
        result.row_count = len(df)
        result.feature_count = int(feat_val.get("present_count", 0))
        result.fingerprint = compute_dataset_fingerprint(df, self.config).to_dict()

        if "split" in df.columns:
            result.split_distribution = {str(k): int(v) for k, v in df["split"].value_counts().items()}
        if "label" in df.columns:
            result.label_distribution = {str(int(k)): int(v) for k, v in df["label"].value_counts().items()}

        if archive_v1:
            result.archived_v1 = archive_deprecated_v1(self.symbol, self.timeframe, self.base_dir)

        result.status = "fail" if result.errors else "pass"
        self._write_reports(result, df=df)
        return result

    def _write_reports(self, result: Phase91BuildResult, df: pd.DataFrame | None = None) -> None:
        build_path = _save_json(_phase9_report_path("dataset_build_report.json", self.base_dir), result.to_dict())
        result.reports["dataset_build_report"] = str(build_path)

        if df is not None and not df.empty:
            quality = build_dataset_quality_report(df, self.symbol, self.timeframe)
            quality_payload = quality.to_dict()
            quality_payload["phase"] = "9.1"
            quality_payload["feature_count"] = result.feature_count
            quality_payload["split_distribution"] = result.split_distribution
            quality_path = _save_json(
                _phase9_report_path("dataset_quality_report.json", self.base_dir),
                quality_payload,
            )
            result.reports["dataset_quality_report"] = str(quality_path)

            save_dataset_quality_report(df, self.symbol, self.timeframe, self.base_dir)

            leakage_path = save_leakage_audit(df, self.symbol, self.timeframe, self.base_dir)
            leakage_payload = json.loads(leakage_path.read_text(encoding="utf-8"))
            leakage_payload["phase"] = "9.1"
            phase9_leak_path = _save_json(
                _phase9_report_path("leakage_report.json", self.base_dir),
                leakage_payload,
            )
            result.reports["leakage_report"] = str(phase9_leak_path)

            label_q = LabelQualityValidator().validate(df)
            label_path = _save_json(
                _phase9_report_path("label_quality_report.json", self.base_dir),
                {**label_q.to_dict(), "phase": "9.1", "symbol": self.symbol, "timeframe": self.timeframe},
            )
            result.reports["label_quality_report"] = str(label_path)

            build_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
