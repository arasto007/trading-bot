"""Phase 8.5 dataset sanity gate — training-readiness checks before ML."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.roles import CONTEXT_TIMEFRAME, ENTRY_TIMEFRAME, HIGHER_TIMEFRAME_BIAS
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.dataset.splitter import verify_chronological_splits, verify_purge_gaps
from tradingbot.ml.features.registry.registry import feature_names

DEFAULT_MIN_SAMPLES = 500
DEFAULT_MAX_FEATURE_NAN_PCT = 1.0
DEFAULT_IMBALANCE_WARN = 0.35
DEFAULT_IMBALANCE_FAIL = 0.20
REGIME_COLUMNS = ("volatility_regime", "trend_strength", "h4_trend_bias")
MIN_REGIME_BUCKET_SAMPLES = 10


@dataclass
class SanityIssue:
    code: str
    severity: str
    message: str
    count: int = 0


@dataclass
class SanityReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    status: str
    row_count: int
    passed: bool
    blocked: bool
    issues: list[SanityIssue] = field(default_factory=list)
    label_balance: dict[str, Any] = field(default_factory=dict)
    feature_health: dict[str, Any] = field(default_factory=dict)
    regime_coverage: dict[str, Any] = field(default_factory=dict)
    timeframe_alignment: dict[str, Any] = field(default_factory=dict)
    rows_filtered: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at_utc": self.generated_at_utc,
            "status": self.status,
            "row_count": self.row_count,
            "passed": self.passed,
            "blocked": self.blocked,
            "issues": [asdict(i) for i in self.issues],
            "label_balance": self.label_balance,
            "feature_health": self.feature_health,
            "regime_coverage": self.regime_coverage,
            "timeframe_alignment": self.timeframe_alignment,
            "rows_filtered": self.rows_filtered,
        }


class DatasetSanityGate:
    """
    Strict pre-training sanity checks on labeled datasets.

    No MT5, no model training, no trading logic.
    """

    def __init__(
        self,
        *,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        max_feature_nan_pct: float = DEFAULT_MAX_FEATURE_NAN_PCT,
        imbalance_warn: float = DEFAULT_IMBALANCE_WARN,
        imbalance_fail: float = DEFAULT_IMBALANCE_FAIL,
        min_regime_bucket: int = MIN_REGIME_BUCKET_SAMPLES,
    ) -> None:
        self.min_samples = min_samples
        self.max_feature_nan_pct = max_feature_nan_pct
        self.imbalance_warn = imbalance_warn
        self.imbalance_fail = imbalance_fail
        self.min_regime_bucket = min_regime_bucket

    def evaluate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SanityReport:
        now = datetime.now(timezone.utc).isoformat()
        report = SanityReport(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            generated_at_utc=now,
            status="pass",
            row_count=len(df) if df is not None else 0,
            passed=True,
            blocked=False,
        )

        if df is None or df.empty:
            report.status = "fail"
            report.passed = False
            report.blocked = True
            report.issues.append(SanityIssue("empty_dataset", "error", "Dataset is empty"))
            return report

        self._check_size(df, report)
        self._check_labels(df, report)
        self._check_nan_inf(df, report)
        self._check_feature_variance(df, report)
        self._check_timeframe_alignment(df, report)
        self._check_regime_coverage(df, report)
        self._check_split_stability(df, report)

        has_error = any(i.severity == "error" for i in report.issues)
        has_warn = any(i.severity == "warn" for i in report.issues)
        if has_error:
            report.status = "fail"
            report.passed = False
            report.blocked = True
        elif has_warn:
            report.status = "warn"
            report.passed = True
            report.blocked = False
        else:
            report.status = "pass"
            report.passed = True
            report.blocked = False

        return report

    def filter_dataset(
        self,
        df: pd.DataFrame,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> tuple[pd.DataFrame, int]:
        """Remove invalid samples — deterministic row filtering."""
        if df is None or df.empty:
            return pd.DataFrame(), 0

        work = df.copy()
        n0 = len(work)
        mask = pd.Series(True, index=work.index)

        if symbol and "symbol" in work.columns:
            mask &= work["symbol"].astype(str).str.upper() == symbol.upper()
        if timeframe and "timeframe" in work.columns:
            mask &= work["timeframe"].astype(str).str.upper() == timeframe.upper()

        if "label" in work.columns:
            mask &= work["label"].isin([int(Label.SL_FIRST), int(Label.TP_FIRST), int(Label.NO_RESOLUTION)])

        feat_cols = [c for c in feature_names() if c in work.columns]
        if feat_cols:
            numeric = work[feat_cols].replace([np.inf, -np.inf], np.nan)
            row_nan = numeric.isna().any(axis=1)
            mask &= ~row_nan

        if "timestamp" in work.columns and "event_time" in work.columns:
            ts = pd.to_datetime(work["timestamp"], utc=True)
            ev = pd.to_datetime(work["event_time"], utc=True)
            mask &= ts >= ev

        for col in REGIME_COLUMNS:
            if col in work.columns:
                mask &= work[col].notna()

        filtered = work[mask].copy()
        if "timestamp" in filtered.columns:
            sort_cols = ["timestamp", "event_id"] if "event_id" in filtered.columns else ["timestamp"]
            filtered = filtered.sort_values(sort_cols).reset_index(drop=True)

        return filtered, n0 - len(filtered)

    def _check_size(self, df: pd.DataFrame, report: SanityReport) -> None:
        if len(df) < self.min_samples:
            report.issues.append(
                SanityIssue(
                    "insufficient_samples",
                    "error",
                    f"Row count {len(df)} < minimum {self.min_samples}",
                    len(df),
                )
            )

    def _check_labels(self, df: pd.DataFrame, report: SanityReport) -> None:
        if "label" not in df.columns:
            report.issues.append(SanityIssue("missing_label", "error", "No label column"))
            return

        invalid = ~df["label"].isin([int(Label.SL_FIRST), int(Label.TP_FIRST), int(Label.NO_RESOLUTION)])
        if invalid.any():
            report.issues.append(
                SanityIssue("invalid_labels", "error", "Invalid label values", int(invalid.sum()))
            )

        resolved = df[df["label"].isin([0, 1])]
        tp = int((resolved["label"] == 1).sum())
        sl = int((resolved["label"] == 0).sum())
        total = tp + sl
        tp_rate = round(tp / total, 4) if total else 0.0
        report.label_balance = {"tp": tp, "sl": sl, "tp_rate": tp_rate, "resolved": total}

        if total > 0:
            minority = min(tp, sl) / total
            if minority < self.imbalance_fail:
                report.issues.append(
                    SanityIssue("label_imbalance", "error", f"Severe imbalance minority={minority:.2%}")
                )
            elif minority < self.imbalance_warn:
                report.issues.append(
                    SanityIssue("label_imbalance", "warn", f"Imbalanced labels minority={minority:.2%}")
                )

    def _check_nan_inf(self, df: pd.DataFrame, report: SanityReport) -> None:
        feat_cols = [c for c in feature_names() if c in df.columns]
        if not feat_cols:
            report.issues.append(SanityIssue("no_features", "error", "No registered features in dataset"))
            return

        nan_pct: dict[str, float] = {}
        inf_count = 0
        for col in feat_cols:
            s = df[col]
            nan_pct[col] = round(float(s.isna().mean() * 100), 4)
            vals = pd.to_numeric(s, errors="coerce")
            inf_count += int(np.isinf(vals.to_numpy()).sum())

        mean_nan = float(np.mean(list(nan_pct.values())))
        report.feature_health["mean_nan_pct"] = round(mean_nan, 4)
        report.feature_health["inf_count"] = inf_count
        report.feature_health["per_feature_nan"] = nan_pct

        if inf_count > 0:
            report.issues.append(SanityIssue("inf_values", "error", "Inf values in features", inf_count))
        if mean_nan > self.max_feature_nan_pct:
            report.issues.append(
                SanityIssue(
                    "nan_spike",
                    "error",
                    f"Mean feature NaN {mean_nan:.2f}% > {self.max_feature_nan_pct}%",
                )
            )

    def _check_feature_variance(self, df: pd.DataFrame, report: SanityReport) -> None:
        constants: list[str] = []
        for col in feature_names():
            if col not in df.columns:
                continue
            s = df[col].dropna()
            if s.empty or s.nunique() <= 1:
                constants.append(col)
        report.feature_health["constant_features"] = constants
        if constants:
            report.issues.append(
                SanityIssue(
                    "constant_features",
                    "warn",
                    f"Zero-variance features: {constants[:5]}",
                    len(constants),
                )
            )

    def _check_timeframe_alignment(self, df: pd.DataFrame, report: SanityReport) -> None:
        alignment: dict[str, Any] = {
            "expected_entry": ENTRY_TIMEFRAME,
            "expected_context": CONTEXT_TIMEFRAME,
            "expected_bias": HIGHER_TIMEFRAME_BIAS,
        }
        if "timeframe" in df.columns:
            tfs = sorted(df["timeframe"].dropna().unique().tolist())
            alignment["dataset_timeframes"] = tfs
            if len(tfs) != 1 or tfs[0].upper() != report.timeframe:
                report.issues.append(
                    SanityIssue("timeframe_mismatch", "warn", f"Unexpected timeframes: {tfs}")
                )

        if "timestamp" in df.columns and "event_time" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            ev = pd.to_datetime(df["event_time"], utc=True)
            leak = int((ts < ev).sum())
            alignment["timestamp_before_event"] = leak
            if leak > 0:
                report.issues.append(
                    SanityIssue("timestamp_leakage", "error", "Feature timestamp before event_time", leak)
                )

        report.timeframe_alignment = alignment

    def _check_regime_coverage(self, df: pd.DataFrame, report: SanityReport) -> None:
        coverage: dict[str, Any] = {}
        weak_buckets = 0
        for col in REGIME_COLUMNS:
            if col not in df.columns:
                report.issues.append(SanityIssue("missing_regime_feature", "warn", f"Missing {col}"))
                continue
            counts = df[col].value_counts().to_dict()
            coverage[col] = {str(k): int(v) for k, v in counts.items()}
            # Continuous regime signals (e.g. trend_strength) are not bucket-classified.
            if df[col].nunique() > 100:
                continue
            if len(counts) < 2:
                weak_buckets += 1
            elif min(counts.values()) < self.min_regime_bucket:
                weak_buckets += 1

        report.regime_coverage = coverage
        if weak_buckets > 0:
            report.issues.append(
                SanityIssue("weak_regime_coverage", "warn", "Insufficient regime bucket diversity", weak_buckets)
            )

    def _check_split_stability(self, df: pd.DataFrame, report: SanityReport) -> None:
        if "split" not in df.columns:
            return
        if not verify_chronological_splits(df):
            report.issues.append(SanityIssue("split_order", "error", "Non-chronological train/val/test splits"))
        purge = int(df.get("future_window_bars", pd.Series([72])).iloc[0]) if "future_window_bars" in df.columns else 72
        if not verify_purge_gaps(df, purge_bars=purge, timeframe=report.timeframe):
            report.issues.append(SanityIssue("purge_gap", "warn", "Purge gaps below configured window"))
