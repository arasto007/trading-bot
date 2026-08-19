"""Dataset leakage audit — features, timestamps, and split boundaries."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import dataset_leakage_audit_path, reports_dir

from tradingbot.ml.dataset.schema import META_COLUMNS

FORBIDDEN_FEATURE_SUBSTRINGS = (
    "future",
    "future_return",
    "return_after",
    "outcome",
    "tp_hit",
    "sl_hit",
    "mfe",
    "mae",
)

SAFE_META_COLUMNS = frozenset(META_COLUMNS) | frozenset(
    {
        "feature_schema_version",
        "dataset_schema_version",
        "risk_unit",
        "direction",
        "event_id",
    }
)


@dataclass
class LeakageAuditResult:
    symbol: str
    timeframe: str
    generated_at_utc: str
    status: str
    timestamp_leakage_count: int = 0
    forbidden_feature_columns: list[str] = field(default_factory=list)
    split_leakage: bool = False
    split_boundaries: dict[str, str | None] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetLeakageAuditor:
    """Audit dataset for feature leakage and split contamination."""

    def audit(self, df: pd.DataFrame, symbol: str, timeframe: str) -> LeakageAuditResult:
        result = LeakageAuditResult(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            status="pass",
        )
        if df is None or df.empty:
            result.status = "fail"
            result.issues.append("empty dataset")
            return result

        self._check_timestamp_leakage(df, result)
        self._check_forbidden_features(df, result)
        self._check_split_leakage(df, result)

        if result.timestamp_leakage_count > 0 or result.forbidden_feature_columns or result.split_leakage:
            result.status = "fail"
        elif result.issues:
            result.status = "warn"

        return result

    def _check_timestamp_leakage(self, df: pd.DataFrame, result: LeakageAuditResult) -> None:
        if "timestamp" not in df.columns or "event_time" not in df.columns:
            return
        ts = pd.to_datetime(df["timestamp"], utc=True)
        ev = pd.to_datetime(df["event_time"], utc=True, errors="coerce")
        leaks = (ts > ev).sum()
        result.timestamp_leakage_count = int(leaks)
        if leaks > 0:
            result.issues.append(f"{leaks} rows where feature timestamp > event_time")

    def _check_forbidden_features(self, df: pd.DataFrame, result: LeakageAuditResult) -> None:
        forbidden: list[str] = []
        for col in df.columns:
            if col in SAFE_META_COLUMNS:
                continue
            lower = col.lower()
            for pattern in FORBIDDEN_FEATURE_SUBSTRINGS:
                if pattern in lower:
                    forbidden.append(col)
                    break
        result.forbidden_feature_columns = sorted(set(forbidden))
        if forbidden:
            result.issues.append(f"forbidden feature columns: {forbidden}")

    def _check_split_leakage(self, df: pd.DataFrame, result: LeakageAuditResult) -> None:
        if "split" not in df.columns or "timestamp" not in df.columns:
            return
        ts = pd.to_datetime(df["timestamp"], utc=True)
        work = df.assign(_ts=ts)

        bounds: dict[str, str | None] = {}
        for name in ("train", "validation", "test"):
            part = work[work["split"] == name]
            if part.empty:
                bounds[f"{name}_min"] = None
                bounds[f"{name}_max"] = None
            else:
                bounds[f"{name}_min"] = part["_ts"].min().isoformat()
                bounds[f"{name}_max"] = part["_ts"].max().isoformat()
        result.split_boundaries = bounds

        train = work[work["split"] == "train"]
        val = work[work["split"] == "validation"]
        test = work[work["split"] == "test"]

        if not train.empty and not val.empty:
            if train["_ts"].max() >= val["_ts"].min():
                result.split_leakage = True
                result.issues.append("train max timestamp >= validation min timestamp")

        if not val.empty and not test.empty:
            if val["_ts"].max() >= test["_ts"].min():
                result.split_leakage = True
                result.issues.append("validation max timestamp >= test min timestamp")


def save_leakage_audit(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    auditor = DatasetLeakageAuditor()
    result = auditor.audit(df, symbol, timeframe)
    path = dataset_leakage_audit_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
