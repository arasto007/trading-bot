"""Phase 8.2 dataset research audit engine."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import reports_dir, research_audit_report_path
from tradingbot.ml.dataset.feature_analysis import analyze_features, save_feature_quality_report
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.label_analysis import analyze_label_distribution, save_label_quality_report
from tradingbot.ml.dataset.label_research import run_label_research, save_label_research_report
from tradingbot.ml.dataset.regime_analysis import analyze_regimes, save_regime_report
from tradingbot.ml.dataset.schema import DatasetBuildConfig
from tradingbot.ml.dataset.session_analysis import analyze_sessions, save_session_report
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset, validate_dataset_schema
from tradingbot.ml.features.registry.registry import feature_names

logger = logging.getLogger(__name__)


@dataclass
class ResearchAuditResult:
    symbol: str
    timeframe: str
    status: str
    generated_at_utc: str
    overview: dict[str, Any] = field(default_factory=dict)
    schema_validation: dict[str, Any] = field(default_factory=dict)
    label_analysis: dict[str, Any] = field(default_factory=dict)
    feature_analysis: dict[str, Any] = field(default_factory=dict)
    session_analysis: dict[str, Any] = field(default_factory=dict)
    regime_analysis: dict[str, Any] = field(default_factory=dict)
    label_research: dict[str, Any] = field(default_factory=dict)
    fingerprint: dict[str, Any] = field(default_factory=dict)
    report_paths: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status in ("pass", "warn")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "passed": self.passed,
            "generated_at_utc": self.generated_at_utc,
            "overview": self.overview,
            "schema_validation": self.schema_validation,
            "label_analysis": self.label_analysis,
            "feature_analysis": self.feature_analysis,
            "session_analysis": self.session_analysis,
            "regime_analysis": self.regime_analysis,
            "label_research": self.label_research,
            "fingerprint": self.fingerprint,
            "report_paths": self.report_paths,
            "errors": self.errors,
        }


class DatasetResearchAudit:
    """
    Load production dataset and generate a complete pre-training research report.

    No MT5, no model training, no kernel/risk/execution dependencies.
    """

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
        self._store = DatasetStore(base_dir)
        self._df: pd.DataFrame | None = None

    def load(self) -> pd.DataFrame | None:
        self._df = self._store.load(self.symbol, self.timeframe)
        return self._df

    def build_overview(self, df: pd.DataFrame) -> dict[str, Any]:
        feat_cols = [c for c in feature_names() if c in df.columns]
        date_range: dict[str, str | None] = {"start": None, "end": None}
        if "timestamp" in df.columns and not df.empty:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            date_range = {"start": ts.min().isoformat(), "end": ts.max().isoformat()}

        symbols = sorted(df["symbol"].dropna().unique().tolist()) if "symbol" in df.columns else [self.symbol]
        timeframes = (
            sorted(df["timeframe"].dropna().unique().tolist()) if "timeframe" in df.columns else [self.timeframe]
        )

        return {
            "rows": len(df),
            "columns": len(df.columns),
            "features_count": len(feat_cols),
            "date_range": date_range,
            "symbols": symbols,
            "timeframes": timeframes,
        }

    def run_features_only(self) -> ResearchAuditResult:
        result = ResearchAuditResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            status="fail",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        df = self.load()
        if df is None or df.empty:
            result.errors.append("no_dataset")
            return result

        feature_report = analyze_features(df, self.symbol, self.timeframe)
        result.feature_analysis = feature_report.to_dict()
        result.overview = {"rows": len(df), "features_count": len(feature_report.features)}

        try:
            path = save_feature_quality_report(df, self.symbol, self.timeframe, self.base_dir)
            result.report_paths["feature_quality"] = str(path)
        except Exception as exc:
            logger.warning("Feature quality report save failed: %s", exc)
            result.errors.append(f"feature_report: {exc}")

        result.status = "pass"
        return result

    def run_full_audit(self, *, include_label_research: bool = True) -> ResearchAuditResult:
        result = ResearchAuditResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            status="fail",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
        )

        df = self.load()
        if df is None or df.empty:
            result.errors.append("no_dataset")
            return result

        result.overview = self.build_overview(df)

        schema_errors = validate_dataset_schema(df)
        validation = validate_dataset(df)
        result.schema_validation = {
            "schema_errors": schema_errors,
            "validation": validation.to_dict(),
        }
        if schema_errors:
            result.errors.extend(schema_errors)

        label_report = analyze_label_distribution(df, self.symbol, self.timeframe)
        result.label_analysis = label_report.to_dict()

        feature_report = analyze_features(df, self.symbol, self.timeframe)
        result.feature_analysis = feature_report.to_dict()

        session_report = analyze_sessions(df, self.symbol, self.timeframe)
        result.session_analysis = session_report.to_dict()

        regime_report = analyze_regimes(df, self.symbol, self.timeframe)
        result.regime_analysis = regime_report.to_dict()

        if include_label_research:
            label_research = run_label_research(
                df, self.symbol, self.timeframe, base_dir=self.base_dir, config=self.config
            )
            result.label_research = label_research.to_dict()

        fp = compute_dataset_fingerprint(df, self.config)
        result.fingerprint = fp.to_dict()

        reports_dir(self.base_dir).mkdir(parents=True, exist_ok=True)
        try:
            result.report_paths["label_quality"] = str(
                save_label_quality_report(df, self.symbol, self.timeframe, self.base_dir)
            )
            result.report_paths["feature_quality"] = str(
                save_feature_quality_report(df, self.symbol, self.timeframe, self.base_dir)
            )
            result.report_paths["session"] = str(save_session_report(df, self.symbol, self.timeframe, self.base_dir))
            result.report_paths["regime"] = str(save_regime_report(df, self.symbol, self.timeframe, self.base_dir))
            if include_label_research:
                result.report_paths["label_research"] = str(
                    save_label_research_report(df, self.symbol, self.timeframe, self.base_dir, self.config)
                )
        except Exception as exc:
            logger.warning("Report save failed: %s", exc)
            result.errors.append(f"report_save: {exc}")

        audit_path = research_audit_report_path(self.symbol, self.timeframe, self.base_dir)
        audit_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        result.report_paths["research_audit"] = str(audit_path)

        if validation.status == "fail" or schema_errors:
            result.status = "fail"
        elif validation.status == "warn" or label_report.status == "warning":
            result.status = "warn"
        else:
            result.status = "pass"

        return result
