"""Phase 18A — latency profile for parallel shadow engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from tradingbot.ml.monitoring.statistics import latency_summary, percentile
from tradingbot.ml.research.phase18a.config import MAX_LATENCY_OVERHEAD


@dataclass
class LatencyProfiler:
    v40_ms: list[float] = field(default_factory=list)
    v41_ms: list[float] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)

    def add(self, v40: float, v41: float, total: float) -> None:
        self.v40_ms.append(float(v40))
        self.v41_ms.append(float(v41))
        self.total_ms.append(float(total))

    def to_dict(self) -> dict[str, Any]:
        warm40 = self.v40_ms[3:] if len(self.v40_ms) > 3 else self.v40_ms
        warm41 = self.v41_ms[3:] if len(self.v41_ms) > 3 else self.v41_ms
        mean40 = float(np.mean(warm40)) if warm40 else 0.0
        mean41 = float(np.mean(warm41)) if warm41 else 0.0
        med40 = float(np.median(warm40)) if warm40 else 0.0
        med41 = float(np.median(warm41)) if warm41 else 0.0
        # Steady-state gate uses median (mean is spike-skewed on Windows).
        overhead_median = ((med41 - med40) / med40) if med40 > 1e-9 else 0.0
        overhead_mean = ((mean41 - mean40) / mean40) if mean40 > 1e-9 else 0.0
        p95_40 = percentile(warm40, 0.95) if warm40 else 0.0
        p95_41 = percentile(warm41, 0.95) if warm41 else 0.0
        return {
            "phase": "18A",
            "v40": latency_summary(warm40),
            "v41": latency_summary(warm41),
            "total": latency_summary(self.total_ms[3:] if len(self.total_ms) > 3 else self.total_ms),
            "mean_delta_ms": round(mean41 - mean40, 4),
            "median_delta_ms": round(med41 - med40, 4),
            "p95_delta_ms": round(float(p95_41) - float(p95_40), 4),
            "overhead_ratio": round(overhead_median, 6),
            "overhead_pct": round(overhead_median * 100, 3),
            "overhead_mean_pct": round(overhead_mean * 100, 3),
            "max_allowed_overhead": MAX_LATENCY_OVERHEAD,
            "latency_ok": overhead_median <= MAX_LATENCY_OVERHEAD,
            "gate": "median",
        }
