"""Phase 16A — alignment validation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.feature_alignment.distribution_aligner import DistributionAligner
from tradingbot.ml.feature_alignment.config import SHIFTED_FEATURES
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS


def validate_aligner(aligner: DistributionAligner) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["has_shifted_mappers"] = len(aligner._mappers) == len(SHIFTED_FEATURES)
    if not checks["has_shifted_mappers"]:
        failures.append("missing_shifted_mappers")

    for feat, mapper in aligner._mappers.items():
        if not mapper.is_monotonic_on_grid():
            checks[f"monotonic_{feat}"] = False
            failures.append(f"non_monotonic_{feat}")
        else:
            checks[f"monotonic_{feat}"] = True

    sample = {f: float(i + 1) for i, f in enumerate(TREND_ML_FEATURE_COLUMNS)}
    aligned = aligner.align(sample)
    checks["no_nan"] = all(np.isfinite(float(aligned[f])) for f in TREND_ML_FEATURE_COLUMNS if f in aligned)
    checks["feature_count_preserved"] = len(aligned) >= len(sample)
    if not checks["no_nan"]:
        failures.append("nan_in_output")

    healthy = [f for f in TREND_ML_FEATURE_COLUMNS if f not in SHIFTED_FEATURES]
    unchanged = all(abs(float(aligned[h]) - float(sample[h])) < 1e-12 for h in healthy if h in aligned)
    checks["healthy_features_unchanged"] = unchanged
    if not unchanged:
        failures.append("healthy_feature_modified")

    return {
        "checks": checks,
        "all_passed": all(checks.values()) and len(failures) == 0,
        "failed": failures,
    }
