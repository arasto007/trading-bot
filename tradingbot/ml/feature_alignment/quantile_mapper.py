"""Phase 16A — monotonic quantile mapping (PCHIP)."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator

from tradingbot.ml.feature_alignment.feature_statistics import FeatureStats


def _dedupe_monotonic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(x) == 0:
        return x, y
    keep = [0]
    for i in range(1, len(x)):
        if x[i] > x[keep[-1]]:
            keep.append(i)
        elif x[i] == x[keep[-1]]:
            y[keep[-1]] = y[i]
    return x[keep], y[keep]


class QuantileMapper:
    """Map live feature values to training distribution via rank-preserving PCHIP."""

    def __init__(self, *, live: FeatureStats, train: FeatureStats) -> None:
        self.feature = train.feature
        self.train_min = float(train.min)
        self.train_max = float(train.max)
        lx, ty = _dedupe_monotonic(live.quantiles.copy(), train.quantiles.copy())
        if len(lx) < 2:
            lx = np.array([live.min, live.max], dtype=float)
            ty = np.array([train.min, train.max], dtype=float)
        self._interp = PchipInterpolator(lx, ty, extrapolate=False)

    def map_value(self, value: float) -> float:
        v = float(value)
        lo = float(self._interp.x.min())
        hi = float(self._interp.x.max())
        if v <= lo:
            return float(np.clip(self._interp(lo), self.train_min, self.train_max))
        if v >= hi:
            return float(np.clip(self._interp(hi), self.train_min, self.train_max))
        mapped = float(self._interp(v))
        if not np.isfinite(mapped):
            mapped = float(np.clip(v, self.train_min, self.train_max))
        return float(np.clip(mapped, self.train_min, self.train_max))

    def is_monotonic_on_grid(self, n: int = 50) -> bool:
        lo = float(self._interp.x.min())
        hi = float(self._interp.x.max())
        grid = np.linspace(lo, hi, n)
        out = np.array([self.map_value(float(x)) for x in grid])
        return bool(np.all(np.diff(out) >= -1e-9))
