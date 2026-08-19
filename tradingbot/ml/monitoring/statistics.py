"""Phase 15C — thread-safe statistical helpers."""

from __future__ import annotations

import statistics
import threading
from typing import Any


class ThreadSafeCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def inc(self, n: int = 1) -> int:
        with self._lock:
            self._value += n
            return self._value

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


class ThreadSafeStore:
    """Append-only thread-safe record store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * pct), len(ordered) - 1)
    return float(ordered[idx])


def latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "count": 0}
    return {
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "p99": round(percentile(values, 0.99), 3),
        "max": round(max(values), 3),
        "count": len(values),
    }


def rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
