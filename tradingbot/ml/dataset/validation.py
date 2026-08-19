"""Dataset quality validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, META_COLUMNS, SAMPLE_EVENT_TYPES
from tradingbot.ml.features.registry.registry import feature_names


@dataclass
class DatasetValidationIssue:
    code: str
    severity: str
    message: str
    count: int = 0


@dataclass
class DatasetValidationResult:
    status: str
    row_count: int
    issues: list[DatasetValidationIssue] = field(default_factory=list)
    label_distribution: dict[str, int] = field(default_factory=dict)
    event_distribution: dict[str, int] = field(default_factory=dict)
    missing_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "row_count": self.row_count,
            "issues": [
                {"code": i.code, "severity": i.severity, "message": i.message, "count": i.count}
                for i in self.issues
            ],
            "label_distribution": self.label_distribution,
            "event_distribution": self.event_distribution,
            "missing_columns": self.missing_columns,
        }


REQUIRED_META = (
    "timestamp",
    "symbol",
    "timeframe",
    "event_type",
    "event_time",
    "entry_price",
    "timeframe_role",
    "stop_loss",
    "take_profit",
    "label",
    "future_window_bars",
    "tp_hit",
    "sl_hit",
    "mfe",
    "mae",
    "future_return",
)


def validate_dataset_schema(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if df is None or df.empty:
        return ["empty dataset"]
    for col in REQUIRED_META:
        if col not in df.columns:
            errors.append(f"missing column: {col}")
    if "dataset_schema_version" in df.columns:
        versions = df["dataset_schema_version"].dropna().unique()
        if len(versions) != 1 or str(versions[0]) != DATASET_SCHEMA_VERSION:
            errors.append(f"unexpected dataset_schema_version: {versions.tolist()}")
    return errors


def validate_dataset(df: pd.DataFrame) -> DatasetValidationResult:
    issues: list[DatasetValidationIssue] = []
    if df is None or df.empty:
        return DatasetValidationResult(
            status="fail",
            row_count=0,
            issues=[DatasetValidationIssue("no_data", "error", "Empty dataset")],
        )

    schema_errors = validate_dataset_schema(df)
    missing_cols = [e.replace("missing column: ", "") for e in schema_errors if e.startswith("missing")]
    for err in schema_errors:
        issues.append(DatasetValidationIssue("schema", "error", err))

    dup_cols = ["event_id"] if "event_id" in df.columns else ["timestamp", "event_type"]
    if all(c in df.columns for c in dup_cols):
        dups = df.duplicated(subset=dup_cols, keep=False).sum()
        if dups > 0:
            issues.append(
                DatasetValidationIssue("duplicate_samples", "warn", "Duplicate decision points", int(dups))
            )

    if "label" in df.columns:
        for lbl in df["label"].dropna().unique():
            if int(lbl) not in (-1, 0, 1):
                issues.append(
                    DatasetValidationIssue("invalid_label", "error", f"Invalid label value: {lbl}")
                )

    if "event_type" in df.columns:
        invalid_events = ~df["event_type"].isin(SAMPLE_EVENT_TYPES)
        if invalid_events.any():
            issues.append(
                DatasetValidationIssue(
                    "invalid_event_type",
                    "warn",
                    "Unknown event types",
                    int(invalid_events.sum()),
                )
            )

    feature_cols = [c for c in feature_names() if c in df.columns]
    if feature_cols:
        nan_pct = float(df[feature_cols].isna().mean().mean() * 100)
        if nan_pct > 1:
            issues.append(
                DatasetValidationIssue("missing_features", "warn", f"Feature NaN {nan_pct:.1f}%")
            )

    label_dist = {}
    if "label" in df.columns:
        label_dist = {str(int(k)): int(v) for k, v in df["label"].value_counts().items()}

    event_dist = {}
    if "event_type" in df.columns:
        event_dist = {str(k): int(v) for k, v in df["event_type"].value_counts().items()}

    status = "pass"
    if any(i.severity == "error" for i in issues):
        status = "fail"
    elif issues:
        status = "warn"

    return DatasetValidationResult(
        status=status,
        row_count=len(df),
        issues=issues,
        label_distribution=label_dist,
        event_distribution=event_dist,
        missing_columns=missing_cols,
    )
