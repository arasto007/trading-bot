"""Feature column validation against registry constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.features.registry.enrichment import FEATURE_ENRICHMENT
from tradingbot.ml.features.registry.registry import all_features, feature_names


@dataclass
class FeatureValidationIssue:
    feature: str
    code: str
    severity: str
    message: str
    count: int = 0


@dataclass
class FeatureValidationResult:
    status: str
    row_count: int
    feature_count: int
    issues: list[FeatureValidationIssue] = field(default_factory=list)
    per_feature: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "row_count": self.row_count,
            "feature_count": self.feature_count,
            "issues": [
                {
                    "feature": i.feature,
                    "code": i.code,
                    "severity": i.severity,
                    "message": i.message,
                    "count": i.count,
                }
                for i in self.issues
            ],
            "per_feature": self.per_feature,
        }


def _is_constant(series: pd.Series) -> bool:
    clean = series.dropna()
    if clean.empty:
        return True
    return clean.nunique() <= 1


def _outlier_count(series: pd.Series, z_threshold: float = 5.0) -> int:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 10:
        return 0
    mean = float(clean.mean())
    std = float(clean.std())
    if std <= 0:
        return 0
    z = ((clean - mean) / std).abs()
    return int((z > z_threshold).sum())


def _range_violations(series: pd.Series, spec: dict[str, Any]) -> int:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return 0
    count = 0
    if "min" in spec:
        count += int((clean < spec["min"]).sum())
    if "max" in spec:
        count += int((clean > spec["max"]).sum())
    if "allowed_values" in spec:
        allowed = set(spec["allowed_values"])
        count += int((~clean.isin(allowed)).sum())
    return count


def validate_feature_dataframe(
    df: pd.DataFrame,
    *,
    reference_df: pd.DataFrame | None = None,
    drift_threshold: float = 0.25,
) -> FeatureValidationResult:
    """
    Validate feature matrix quality.

    Checks: NaN %, constants, outliers, drift vs reference, invalid ranges.
    """
    feature_cols = [c for c in feature_names() if c in df.columns]
    issues: list[FeatureValidationIssue] = []
    per_feature: dict[str, dict[str, Any]] = {}

    if df is None or df.empty:
        return FeatureValidationResult(
            status="fail",
            row_count=0,
            feature_count=0,
            issues=[FeatureValidationIssue("", "no_data", "error", "Empty feature dataframe")],
        )

    schema_col = "feature_schema_version"
    if schema_col in df.columns:
        versions = df[schema_col].dropna().unique()
        if len(versions) != 1:
            issues.append(
                FeatureValidationIssue(
                    schema_col,
                    "schema_version_mismatch",
                    "error",
                    f"Multiple schema versions: {versions.tolist()}",
                )
            )

    missing = set(feature_names()) - set(feature_cols)
    if missing:
        issues.append(
            FeatureValidationIssue(
                "",
                "missing_columns",
                "error",
                f"Missing registered features: {sorted(missing)}",
                count=len(missing),
            )
        )

    for col in feature_cols:
        series = df[col]
        spec = FEATURE_ENRICHMENT.get(col, {})
        nan_pct = float(series.isna().mean() * 100)
        stats = {
            "nan_pct": round(nan_pct, 4),
            "min": float(series.min()) if series.notna().any() else None,
            "max": float(series.max()) if series.notna().any() else None,
            "constant": _is_constant(series),
            "outlier_count": _outlier_count(series),
        }
        per_feature[col] = stats

        policy = spec.get("nullable_policy", all_features()[0].nullable_policy if all_features() else "zero_fill")
        if nan_pct > 0 and policy == "forbidden":
            issues.append(
                FeatureValidationIssue(col, "nan_forbidden", "error", "NaN not allowed", int(series.isna().sum()))
            )
        elif nan_pct > 5:
            issues.append(
                FeatureValidationIssue(col, "high_nan", "warn", f"NaN {nan_pct:.1f}%", int(series.isna().sum()))
            )

        if _is_constant(series):
            issues.append(FeatureValidationIssue(col, "constant", "warn", "Constant feature"))

        outliers = stats["outlier_count"]
        if outliers > 0:
            issues.append(
                FeatureValidationIssue(col, "outliers", "warn", f"Extreme outliers (|z|>5)", outliers)
            )

        violations = _range_violations(series, spec)
        if violations > 0:
            issues.append(
                FeatureValidationIssue(col, "invalid_range", "error", "Values outside allowed range", violations)
            )

        if reference_df is not None and col in reference_df.columns:
            ref = reference_df[col].dropna()
            cur = series.dropna()
            if len(ref) > 10 and len(cur) > 10:
                ref_mean = float(ref.mean())
                cur_mean = float(cur.mean())
                denom = abs(ref_mean) if abs(ref_mean) > 1e-9 else 1.0
                drift = abs(cur_mean - ref_mean) / denom
                stats["drift_ratio"] = round(drift, 4)
                if drift > drift_threshold:
                    issues.append(
                        FeatureValidationIssue(
                            col,
                            "drift",
                            "warn",
                            f"Mean drift ratio {drift:.2f}",
                        )
                    )

    status = "pass"
    if any(i.severity == "error" for i in issues):
        status = "fail"
    elif issues:
        status = "warn"

    return FeatureValidationResult(
        status=status,
        row_count=len(df),
        feature_count=len(feature_cols),
        issues=issues,
        per_feature=per_feature,
    )
