"""Phase 12 — execution latency tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LatencySample:
    latency_ms: float
    success: bool
    symbol: str = ""


class LatencyTracker:
    def __init__(self) -> None:
        self._samples: list[LatencySample] = []
        self._start: float | None = None

    def begin(self) -> None:
        self._start = time.perf_counter()

    def end(self, *, success: bool, symbol: str = "") -> float:
        if self._start is None:
            return 0.0
        ms = (time.perf_counter() - self._start) * 1000.0
        self._samples.append(LatencySample(latency_ms=ms, success=success, symbol=symbol))
        self._start = None
        return ms

    def summary(self) -> dict[str, Any]:
        if not self._samples:
            return {"count": 0, "mean_ms": 0.0, "p95_ms": 0.0}
        values = sorted(s.latency_ms for s in self._samples)
        p95_idx = min(len(values) - 1, int(len(values) * 0.95))
        return {
            "count": len(values),
            "mean_ms": round(sum(values) / len(values), 2),
            "p95_ms": round(values[p95_idx], 2),
            "success_rate": round(sum(1 for s in self._samples if s.success) / len(self._samples), 4),
        }
