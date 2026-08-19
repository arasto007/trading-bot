"""Phase 9.1.5 — ultra-strict read-only deep audit for dataset_v2 before training."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.leakage_report import (
    FORBIDDEN_FEATURE_SUBSTRINGS,
    SAFE_META_COLUMNS,
    DatasetLeakageAuditor,
)
from tradingbot.ml.dataset.schema import (
    DATASET_SCHEMA_VERSION,
    DEFAULT_FUTURE_WINDOW_M5,
    META_COLUMNS,
    Label,
)
from tradingbot.ml.dataset.splitter import verify_chronological_splits, verify_purge_gaps
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry.registry import feature_names, validate_integrity

PHASE = "9.1.5"
HEALTH_PASS_THRESHOLD = 85.0
MAX_FEATURE_NAN_PCT = 30.0
IMBALANCE_WARN_MINORITY = 0.20
OUTLIER_Z_THRESHOLD = 6.0

SMC_FEATURES = (
    "bos_state",
    "choch_state",
    "fvg_presence",
    "liquidity_sweep",
    "order_block_distance",
    "premium_discount_location",
    "structure_distance",
)
HTF_FEATURES = ("h4_structure_direction", "h4_trend_bias", "m15_market_state", "m5_entry_context")

WEIGHTS = {
    "structure": 0.20,
    "leakage": 0.30,
    "label_quality": 0.20,
    "feature_quality": 0.20,
    "temporal_integrity": 0.10,
}


def deep_audit_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "deep_audit_report.json"


@dataclass
class DeepAuditReport:
    symbol: str
    timeframe: str
    phase: str
    generated_at_utc: str
    dataset_path: str | None
    row_count: int
    column_count: int
    status: str
    health_score: float
    health_pass_threshold: float
    checks: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    critical_issues: list[str] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "phase": self.phase,
            "generated_at_utc": self.generated_at_utc,
            "dataset_path": self.dataset_path,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "status": self.status,
            "health_score": round(self.health_score, 2),
            "health_pass_threshold": self.health_pass_threshold,
            "checks": self.checks,
            "warnings": self.warnings,
            "critical_issues": self.critical_issues,
            "category_scores": {k: round(v, 2) for k, v in self.category_scores.items()},
        }


class DatasetDeepAuditor:
    """
    Read-only forensic audit of production dataset_v2.

    Does not modify data, connect to MT5, or recompute features.
    """

    def __init__(
        self,
        *,
        health_threshold: float = HEALTH_PASS_THRESHOLD,
        max_feature_nan_pct: float = MAX_FEATURE_NAN_PCT,
        purge_bars: int = DEFAULT_FUTURE_WINDOW_M5,
        expected_schema_version: str = DATASET_SCHEMA_VERSION,
    ) -> None:
        self.health_threshold = health_threshold
        self.max_feature_nan_pct = max_feature_nan_pct
        self.purge_bars = purge_bars
        self.expected_schema_version = expected_schema_version
        self._expected_features = feature_names()

    def audit(self, df: pd.DataFrame, symbol: str, timeframe: str) -> DeepAuditReport:
        sym = symbol.upper()
        tf = timeframe.upper()
        report = DeepAuditReport(
            symbol=sym,
            timeframe=tf,
            phase=PHASE,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            dataset_path=None,
            row_count=len(df) if df is not None else 0,
            column_count=len(df.columns) if df is not None else 0,
            status="FAIL",
            health_score=0.0,
            health_pass_threshold=self.health_threshold,
        )

        if df is None or df.empty:
            report.critical_issues.append("empty_dataset")
            report.checks = self._empty_checks()
            return self._finalize(report)

        work = df.copy()
        if "timestamp" in work.columns:
            work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)

        structure = self._audit_structure(work)
        temporal = self._audit_temporal(work)
        labels = self._audit_labels(work)
        features = self._audit_features(work)
        splits = self._audit_splits(work, tf)
        leakage = self._audit_leakage_strict(work, sym, tf)

        report.checks = {
            "structure": structure,
            "temporal": temporal,
            "labels": labels,
            "features": features,
            "splits": splits,
            "leakage": leakage,
        }

        report.category_scores = {
            "structure": float(structure.get("score", 0.0)),
            "temporal_integrity": float(temporal.get("score", 0.0)),
            "label_quality": float(labels.get("score", 0.0)),
            "feature_quality": float(features.get("score", 0.0)),
            "leakage": float(leakage.get("score", 0.0)),
        }

        for block in report.checks.values():
            for w in block.get("warnings", []):
                if w not in report.warnings:
                    report.warnings.append(w)
            for c in block.get("critical", []):
                if c not in report.critical_issues:
                    report.critical_issues.append(c)

        report.health_score = sum(
            report.category_scores[k] * WEIGHTS[k] for k in WEIGHTS
        )

        return self._finalize(report)

    def audit_from_store(
        self,
        symbol: str,
        timeframe: str,
        base_dir: str | Path | None = None,
    ) -> DeepAuditReport:
        store = DatasetStore(base_dir)
        path = store.resolve_v2_path(symbol, timeframe)
        df = store.load_v2(symbol, timeframe)
        report = self.audit(df if df is not None else pd.DataFrame(), symbol, timeframe)
        report.dataset_path = str(path) if path.is_file() else None
        return report

    def save_report(
        self,
        report: DeepAuditReport,
        base_dir: str | Path | None = None,
    ) -> Path:
        path = deep_audit_report_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def run_and_save(
        self,
        symbol: str,
        timeframe: str,
        base_dir: str | Path | None = None,
    ) -> tuple[DeepAuditReport, Path]:
        report = self.audit_from_store(symbol, timeframe, base_dir)
        path = self.save_report(report, base_dir)
        return report, path

    @staticmethod
    def print_summary(report: DeepAuditReport) -> None:
        labels = report.checks.get("labels", {})
        leakage = report.checks.get("leakage", {})
        dist = labels.get("distribution", {})
        print("=" * 60)
        print("PHASE 9.1.5 — DEEP DATASET AUDIT (READ-ONLY)")
        print("=" * 60)
        print(f"Symbol / TF     : {report.symbol} / {report.timeframe}")
        print(f"Dataset rows    : {report.row_count:,}")
        print(f"Columns         : {report.column_count}")
        print(f"Label dist      : TP={dist.get('tp', 0)} SL={dist.get('sl', 0)} "
              f"unresolved={dist.get('unresolved', 0)}")
        if dist.get("tp_rate") is not None:
            print(f"TP rate         : {dist.get('tp_rate', 0):.2%}")
        print(f"Leakage status  : {leakage.get('status', 'unknown')}")
        print(f"Health score    : {report.health_score:.1f} / 100 "
              f"(threshold {report.health_pass_threshold})")
        if report.critical_issues:
            print(f"Critical issues : {len(report.critical_issues)}")
            for issue in report.critical_issues[:5]:
                print(f"  - {issue}")
        if report.warnings:
            print(f"Warnings        : {len(report.warnings)}")
        print(f"FINAL VERDICT   : {report.status}")
        print("=" * 60)

    def _finalize(self, report: DeepAuditReport) -> DeepAuditReport:
        if report.critical_issues:
            report.status = "FAIL"
        elif report.health_score >= self.health_threshold:
            report.status = "PASS"
        else:
            report.status = "FAIL"
            if "health_score_below_threshold" not in report.critical_issues:
                report.critical_issues.append(
                    f"health_score_below_threshold:{report.health_score:.2f}<{self.health_threshold}"
                )
        report.health_score = round(report.health_score, 2)
        return report

    @staticmethod
    def _empty_checks() -> dict[str, Any]:
        keys = ("structure", "temporal", "labels", "features", "splits", "leakage")
        return {k: {"status": "fail", "score": 0.0, "critical": ["empty_dataset"], "warnings": []} for k in keys}

    def _audit_structure(self, df: pd.DataFrame) -> dict[str, Any]:
        critical: list[str] = []
        warnings: list[str] = []
        expected_cols = set(self._expected_features) | set(META_COLUMNS)
        actual_cols = list(df.columns)
        col_set = set(actual_cols)

        if len(actual_cols) != len(col_set):
            critical.append("duplicate_column_names")

        missing_meta = [c for c in META_COLUMNS if c not in col_set]
        missing_feat = [c for c in self._expected_features if c not in col_set]
        extra = [c for c in actual_cols if c not in expected_cols]

        if missing_meta:
            critical.append(f"missing_meta_columns:{missing_meta}")
        if missing_feat:
            critical.append(f"missing_features:{missing_feat}")
        if extra:
            critical.append(f"extra_columns:{extra}")

        expected_total = len(self._expected_features) + len(META_COLUMNS)
        if len(actual_cols) != expected_total:
            critical.append(f"column_count_mismatch:expected={expected_total},actual={len(actual_cols)}")

        registry_issues = validate_integrity()
        if registry_issues:
            warnings.append(f"feature_registry_integrity:{registry_issues}")

        if "dataset_schema_version" in df.columns:
            versions = df["dataset_schema_version"].dropna().unique().tolist()
            if len(versions) != 1 or str(versions[0]) != self.expected_schema_version:
                warnings.append(f"schema_version_mismatch:{versions}")

        if "event_id" in df.columns:
            dup_events = int(df["event_id"].duplicated().sum())
            if dup_events > 0:
                critical.append(f"duplicate_event_ids:{dup_events}")

        score = 100.0
        score -= 25.0 * len([c for c in critical if "missing" in c or "extra" in c or "column_count" in c])
        score -= 50.0 if "duplicate_column_names" in critical else 0.0
        score -= min(25.0, 5.0 * len([c for c in critical if c.startswith("duplicate_event")]))
        score = max(0.0, score)

        return {
            "status": "fail" if critical else "pass",
            "score": score,
            "expected_columns": expected_total,
            "actual_columns": len(actual_cols),
            "feature_count": len([c for c in self._expected_features if c in col_set]),
            "meta_count": len([c for c in META_COLUMNS if c in col_set]),
            "missing_meta": missing_meta,
            "missing_features": missing_feat,
            "extra_columns": extra,
            "registry_integrity": registry_issues,
            "critical": critical,
            "warnings": warnings,
        }

    def _audit_temporal(self, df: pd.DataFrame) -> dict[str, Any]:
        critical: list[str] = []
        warnings: list[str] = []

        if "timestamp" not in df.columns:
            critical.append("missing_timestamp_column")
            return {"status": "fail", "score": 0.0, "critical": critical, "warnings": warnings}

        ts = pd.to_datetime(df["timestamp"], utc=True)
        monotonic = bool(ts.is_monotonic_increasing)
        if not monotonic:
            critical.append("timestamp_not_monotonic_increasing")

        dup_ts = int(ts.duplicated().sum())
        dup_ts_rows = int(ts.duplicated(keep=False).sum())
        dup_pair = 0
        if "event_id" in df.columns:
            dup_pair = int(df.duplicated(subset=["timestamp", "event_id"]).sum())
            if dup_pair > 0:
                critical.append(f"duplicate_timestamp_event_id_pairs:{dup_pair}")
            elif dup_ts > 0:
                warnings.append(
                    f"shared_bar_timestamps:{dup_ts} (multiple distinct events per M5 bar — expected)"
                )
        elif dup_ts > 0:
            critical.append(f"duplicate_timestamps:{dup_ts}")

        if not ts.dt.tz:
            warnings.append("timestamps_not_timezone_aware")

        reversed_window = 0
        if "event_time" in df.columns:
            ev = pd.to_datetime(df["event_time"], utc=True, errors="coerce")
            future_ts_leak = int((ts > ev).sum())
            if future_ts_leak > 0:
                critical.append(f"feature_timestamp_after_event_time:{future_ts_leak}")
            reversed_window = int((ts < ev).sum())

        shuffled = False
        if len(df) > 2:
            diffs = ts.diff().dropna()
            if (diffs < pd.Timedelta(0)).any():
                shuffled = True
                critical.append("shuffled_or_non_chronological_rows")

        score = 100.0
        if not monotonic:
            score -= 40.0
        if dup_ts:
            score -= min(30.0, dup_ts * 0.01)
        if any("feature_timestamp_after" in c for c in critical):
            score -= 30.0
        score = max(0.0, score)

        return {
            "status": "fail" if critical else "pass",
            "score": score,
            "monotonic_increasing": monotonic,
            "duplicate_timestamps": dup_ts,
            "duplicate_timestamp_rows": dup_ts_rows,
            "duplicate_timestamp_event_id_pairs": dup_pair,
            "reversed_event_windows": reversed_window,
            "shuffled_detected": shuffled,
            "start_utc": ts.min().isoformat() if len(ts) else None,
            "end_utc": ts.max().isoformat() if len(ts) else None,
            "critical": critical,
            "warnings": warnings,
        }

    def _audit_labels(self, df: pd.DataFrame) -> dict[str, Any]:
        critical: list[str] = []
        warnings: list[str] = []

        if "label" not in df.columns:
            critical.append("missing_label_column")
            return {"status": "fail", "score": 0.0, "critical": critical, "warnings": warnings}

        labels = df["label"]
        label_nan = int(labels.isna().sum())
        if label_nan > 0:
            critical.append(f"nan_in_label_column:{label_nan}")

        valid_set = {int(Label.SL_FIRST), int(Label.TP_FIRST), int(Label.NO_RESOLUTION)}
        invalid = ~labels.isin(list(valid_set))
        if invalid.any():
            critical.append(f"invalid_label_values:{int(invalid.sum())}")

        tp = int((labels == int(Label.TP_FIRST)).sum())
        sl = int((labels == int(Label.SL_FIRST)).sum())
        unresolved = int((labels == int(Label.NO_RESOLUTION)).sum())
        resolved = tp + sl
        tp_rate = round(tp / resolved, 4) if resolved else 0.0
        sl_rate = round(sl / resolved, 4) if resolved else 0.0
        unresolved_rate = round(unresolved / len(df), 4) if len(df) else 0.0

        minority = min(tp, sl) / resolved if resolved else 0.0
        if resolved and minority < IMBALANCE_WARN_MINORITY:
            warnings.append(f"severe_label_imbalance_minority={minority:.2%}")
        elif resolved and minority < 0.35:
            warnings.append(f"label_imbalance_minority={minority:.2%}")

        score = 100.0
        if label_nan:
            score = 0.0
        elif invalid.any():
            score -= 50.0
        elif minority < IMBALANCE_WARN_MINORITY:
            score -= 30.0
        elif minority < 0.35:
            score -= 10.0
        if unresolved_rate > 0.05:
            warnings.append(f"high_unresolved_rate:{unresolved_rate:.2%}")
            score -= min(15.0, unresolved_rate * 100)

        return {
            "status": "fail" if critical else "pass",
            "score": max(0.0, score),
            "distribution": {
                "tp": tp,
                "sl": sl,
                "unresolved": unresolved,
                "tp_rate": tp_rate,
                "sl_rate": sl_rate,
                "unresolved_rate": unresolved_rate,
            },
            "minority_class_rate": round(minority, 4) if resolved else None,
            "critical": critical,
            "warnings": warnings,
        }

    def _audit_features(self, df: pd.DataFrame) -> dict[str, Any]:
        critical: list[str] = []
        warnings: list[str] = []
        per_feature: dict[str, dict[str, Any]] = {}
        frozen: list[str] = []
        high_nan: list[str] = []
        unstable: list[str] = []
        smc_zero: list[str] = []
        htf_zero: list[str] = []

        inf_total = 0
        for col in self._expected_features:
            if col not in df.columns:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            nan_pct = float(s.isna().mean() * 100.0)
            vals = s.replace([np.inf, -np.inf], np.nan).dropna()
            inf_count = int(np.isinf(pd.to_numeric(df[col], errors="coerce")).sum())
            inf_total += inf_count

            if nan_pct > self.max_feature_nan_pct:
                critical.append(f"feature_nan_exceeds_threshold:{col}:{nan_pct:.2f}%")
                high_nan.append(col)

            std = float(vals.std()) if len(vals) else 0.0
            mean = float(vals.mean()) if len(vals) else 0.0
            vmin = float(vals.min()) if len(vals) else 0.0
            vmax = float(vals.max()) if len(vals) else 0.0
            nunique = int(vals.nunique())

            outlier_ratio = 0.0
            if len(vals) > 10 and std > 1e-12:
                z = np.abs((vals - mean) / std)
                outlier_ratio = float((z > OUTLIER_Z_THRESHOLD).mean())

            per_feature[col] = {
                "mean": round(mean, 6),
                "std": round(std, 6),
                "min": round(vmin, 6),
                "max": round(vmax, 6),
                "nan_pct": round(nan_pct, 4),
                "nunique": nunique,
                "outlier_ratio": round(outlier_ratio, 4),
            }

            if nunique <= 1:
                frozen.append(col)
                warnings.append(f"zero_variance_feature:{col}")
            elif std < 1e-9:
                frozen.append(col)

            if outlier_ratio > 0.05:
                unstable.append(col)
                warnings.append(f"high_outlier_ratio:{col}:{outlier_ratio:.2%}")

        if inf_total > 0:
            critical.append(f"inf_values_detected:{inf_total}")

        for col in SMC_FEATURES:
            if col in df.columns and pd.to_numeric(df[col], errors="coerce").abs().sum() == 0:
                smc_zero.append(col)
        if len(smc_zero) == len([c for c in SMC_FEATURES if c in df.columns]) and smc_zero:
            warnings.append(f"all_smc_features_zero:{smc_zero}")

        for col in HTF_FEATURES:
            if col in df.columns and pd.to_numeric(df[col], errors="coerce").abs().sum() == 0:
                htf_zero.append(col)
        if len(htf_zero) == len([c for c in HTF_FEATURES if c in df.columns]) and htf_zero:
            warnings.append(f"all_htf_context_features_zero:{htf_zero}")

        score = 100.0
        score -= min(40.0, len(high_nan) * 10.0)
        score -= min(20.0, len(frozen) * 2.0)
        score -= min(15.0, len(unstable) * 3.0)
        if inf_total:
            score = 0.0
        score = max(0.0, score)

        return {
            "status": "fail" if critical else "pass",
            "score": score,
            "per_feature": per_feature,
            "frozen_features": frozen,
            "high_nan_features": high_nan,
            "unstable_features": unstable,
            "smc_all_zero": smc_zero,
            "htf_all_zero": htf_zero,
            "inf_total": inf_total,
            "critical": critical,
            "warnings": warnings,
        }

    def _audit_splits(self, df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
        critical: list[str] = []
        warnings: list[str] = []

        if "split" not in df.columns:
            critical.append("missing_split_column")
            return {"status": "fail", "score": 0.0, "critical": critical, "warnings": warnings}

        counts = {str(k): int(v) for k, v in df["split"].value_counts().items()}
        allowed = {"train", "validation", "test", "purge"}
        unexpected = [k for k in counts if k not in allowed]
        if unexpected:
            warnings.append(f"unexpected_split_values:{unexpected}")

        for required in ("train", "validation", "test"):
            if required not in counts:
                critical.append(f"missing_split:{required}")

        chrono_ok = verify_chronological_splits(df)
        if not chrono_ok:
            critical.append("split_chronology_violation")

        purge_ok = verify_purge_gaps(df, purge_bars=self.purge_bars, timeframe=timeframe)
        if not purge_ok:
            critical.append(f"purge_gap_violation:expected>={self.purge_bars}_bars")

        random_mix = False
        if "timestamp" in df.columns and chrono_ok:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            for split_name in ("train", "validation", "test"):
                part = df[df["split"] == split_name]
                if part.empty:
                    continue
                part_ts = pd.to_datetime(part["timestamp"], utc=True)
                if not part_ts.is_monotonic_increasing:
                    random_mix = True
                    critical.append(f"non_monotonic_within_split:{split_name}")

        bounds: dict[str, Any] = {}
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            work = df.assign(_ts=ts)
            for name in ("train", "validation", "test"):
                part = work[work["split"] == name]
                if part.empty:
                    bounds[name] = None
                else:
                    bounds[name] = {
                        "min": part["_ts"].min().isoformat(),
                        "max": part["_ts"].max().isoformat(),
                        "count": len(part),
                    }

        score = 100.0
        if not chrono_ok or not purge_ok:
            score -= 50.0
        score -= 15.0 * len([c for c in critical if c.startswith("missing_split")])
        if random_mix:
            score -= 25.0
        score = max(0.0, score)

        return {
            "status": "fail" if critical else "pass",
            "score": score,
            "distribution": counts,
            "chronological": chrono_ok,
            "purge_gap_ok": purge_ok,
            "purge_bars_expected": self.purge_bars,
            "boundaries": bounds,
            "random_mix_detected": random_mix,
            "critical": critical,
            "warnings": warnings,
        }

    def _audit_leakage_strict(self, df: pd.DataFrame, symbol: str, timeframe: str) -> dict[str, Any]:
        critical: list[str] = []
        warnings: list[str] = []

        base = DatasetLeakageAuditor().audit(df, symbol, timeframe)
        if base.status == "fail":
            critical.extend(base.issues)
        elif base.status == "warn":
            warnings.extend(base.issues)

        forbidden_in_features: list[str] = []
        for col in df.columns:
            if col in SAFE_META_COLUMNS:
                continue
            if col not in self._expected_features:
                continue
            lower = col.lower()
            for pattern in FORBIDDEN_FEATURE_SUBSTRINGS:
                if pattern in lower:
                    forbidden_in_features.append(col)

        if forbidden_in_features:
            critical.append(f"forbidden_substrings_in_feature_columns:{forbidden_in_features}")

        outcome_cols = ("future_return", "mfe", "mae", "tp_hit", "sl_hit")
        present_outcome = [c for c in outcome_cols if c in df.columns]
        feature_cols = [c for c in self._expected_features if c in df.columns]
        high_corr: list[dict[str, Any]] = []
        if present_outcome and feature_cols:
            for outcome in present_outcome:
                if outcome not in df.columns:
                    continue
                o = pd.to_numeric(df[outcome], errors="coerce")
                if o.notna().sum() < 10:
                    continue
                for feat in feature_cols:
                    f = pd.to_numeric(df[feat], errors="coerce")
                    if f.std() < 1e-12:
                        continue
                    corr = float(f.corr(o))
                    if abs(corr) > 0.98:
                        high_corr.append({"feature": feat, "outcome": outcome, "corr": round(corr, 4)})
        if high_corr:
            warnings.append(f"suspicious_feature_outcome_correlation:{high_corr[:5]}")

        score = 100.0
        if base.split_leakage or base.timestamp_leakage_count > 0 or base.forbidden_feature_columns:
            score = 0.0
        elif base.status == "warn":
            score -= 20.0
        if forbidden_in_features:
            score = 0.0
        score -= min(10.0, len(high_corr) * 2.0)
        score = max(0.0, score)

        return {
            "status": "fail" if critical else ("warn" if warnings else "pass"),
            "score": score,
            "base_audit": base.to_dict(),
            "forbidden_in_feature_space": forbidden_in_features,
            "high_outcome_correlations": high_corr,
            "critical": critical,
            "warnings": warnings,
        }
