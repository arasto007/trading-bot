"""Phase 15H — mapping curve validation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.confidence_mapping.confidence_mapper import ConfidenceMapper
from tradingbot.ml.confidence_mapping.mapping_types import MappingCurve
from tradingbot.ml.risk_intelligence.risk_policy import MIN_CONFIDENCE_FOR_RISK


def validate_mapping_curve(
    mapper: ConfidenceMapper,
    *,
    pairs: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    curve = mapper.curve
    grid = np.linspace(0.0, curve.frozen_ceiling, 50)
    mapped = [mapper.map(float(x)) for x in grid]
    diffs = [mapped[i + 1] - mapped[i] for i in range(len(mapped) - 1)]
    discontinuities = sum(1 for d in diffs if d < -1e-6)

    pair_errors: list[float] = []
    if pairs:
        for frozen, research in pairs:
            pair_errors.append(abs(mapper.map(frozen) - research))

    frozen_at_risk = mapper.map(curve.frozen_ceiling)
    passes_risk_at_ceiling = frozen_at_risk >= MIN_CONFIDENCE_FOR_RISK

    return {
        "monotonic": mapper.is_monotonic(),
        "continuous": discontinuities == 0,
        "discontinuity_count": discontinuities,
        "frozen_ceiling": curve.frozen_ceiling,
        "mapped_ceiling": round(frozen_at_risk, 6),
        "passes_risk_gate_at_frozen_ceiling": passes_risk_at_ceiling,
        "mean_pair_error": round(float(np.mean(pair_errors)), 6) if pair_errors else None,
        "max_pair_error": round(float(np.max(pair_errors)), 6) if pair_errors else None,
    }
