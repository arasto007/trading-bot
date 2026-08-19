"""Memory profiling helpers."""

from __future__ import annotations

import tracemalloc
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class MemorySnapshot:
    current_mb: float
    peak_mb: float

    def to_dict(self) -> dict[str, float]:
        return {"current_mb": round(self.current_mb, 4), "peak_mb": round(self.peak_mb, 4)}


class MemoryProfiler:
    """Track RAM usage during ML shadow operations."""

    def __init__(self) -> None:
        self._active = False

    def start(self) -> None:
        if not self._active:
            tracemalloc.start()
            self._active = True

    def stop(self) -> None:
        if self._active:
            tracemalloc.stop()
            self._active = False

    def snapshot(self) -> MemorySnapshot:
        if not self._active:
            self.start()
        current, peak = tracemalloc.get_traced_memory()
        return MemorySnapshot(current_mb=current / (1024 * 1024), peak_mb=peak / (1024 * 1024))

    def measure(self, func: Callable[[], T]) -> tuple[T, MemorySnapshot]:
        self.start()
        tracemalloc.clear_traces()
        result = func()
        snap = self.snapshot()
        return result, snap

    def measure_parquet_load(self, loader: Callable[[], T]) -> tuple[T, MemorySnapshot]:
        return self.measure(loader)

    def measure_model_load(self, loader: Callable[[], T]) -> tuple[T, MemorySnapshot]:
        return self.measure(loader)

    def measure_report_generation(self, generator: Callable[[], T]) -> tuple[T, MemorySnapshot]:
        return self.measure(generator)
