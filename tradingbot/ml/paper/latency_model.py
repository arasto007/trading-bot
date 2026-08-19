"""Latency simulation — execution delay in bars."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class LatencyModel:
    """Map 50–300ms equivalent delay to bar offsets (M5 ≈ 1 bar per 300ms bucket)."""

    min_ms: int = 50
    max_ms: int = 300
    ms_per_bar: int = 300
    deterministic: bool = False
    seed: int = 42

    def delay_bars(self, rng: np.random.Generator | None = None) -> int:
        if self.deterministic and rng is not None:
            ms = int(rng.integers(self.min_ms, self.max_ms + 1))
        elif rng is not None:
            ms = int(rng.integers(self.min_ms, self.max_ms + 1))
        else:
            ms = (self.min_ms + self.max_ms) // 2
        return max(0, ms // self.ms_per_bar)
