"""Phase 15H — monotone frozen → research confidence mapper."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator

from tradingbot.ml.confidence_mapping.mapping_types import MappingCurve, MappingResult


class ConfidenceMapper:
    """
    Maps frozen-bundle calibrated confidence to research-equivalent scale.

    Monotone, continuous (PCHIP), derived from Phase 15G empirical anchors.
    """

    def __init__(self, curve: MappingCurve) -> None:
        self.curve = curve
        xs = np.array([a.frozen for a in curve.anchors], dtype=float)
        ys = np.array([a.research for a in curve.anchors], dtype=float)
        if len(xs) < 2:
            xs = np.array([0.0, curve.frozen_ceiling], dtype=float)
            ys = np.array([0.0, curve.research_ceiling], dtype=float)
        self._interp = PchipInterpolator(xs, ys, extrapolate=True)
        self._x_min = float(xs.min())
        self._x_max = float(xs.max())

    def map(self, frozen_confidence: float) -> float:
        x = float(frozen_confidence)
        if x <= 0.0:
            return 0.0
        y = float(self._interp(x))
        return float(np.clip(y, 0.0, 1.0))

    def map_result(self, frozen_confidence: float) -> MappingResult:
        mapped = self.map(frozen_confidence)
        segment = "below_range" if frozen_confidence < self._x_min else (
            "above_range" if frozen_confidence > self._x_max else "interpolated"
        )
        return MappingResult(
            frozen_confidence=frozen_confidence,
            mapped_confidence=mapped,
            curve_segment=segment,
        )

    def is_monotonic(self, *, samples: int = 100) -> bool:
        grid = np.linspace(0.0, self.curve.frozen_ceiling, samples)
        vals = [self.map(float(v)) for v in grid]
        return all(vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "curve": self.curve.to_dict(),
            "monotonic": self.is_monotonic(),
        }
