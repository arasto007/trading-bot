"""Phase 15C — engine and pipeline component monitor."""

from __future__ import annotations

import threading
from typing import Any

from tradingbot.ml.monitoring.statistics import ThreadSafeCounter, latency_summary


class _EngineStats:
    def __init__(self) -> None:
        self.calls = ThreadSafeCounter()
        self.success = ThreadSafeCounter()
        self.failures = ThreadSafeCounter()
        self._latencies: list[float] = []
        self._lock = threading.Lock()
        self.checksum: str | None = None
        self.version: str | None = None
        self.available = True

    def record(self, *, success: bool, latency_ms: float = 0.0) -> None:
        self.calls.inc()
        if success:
            self.success.inc()
        else:
            self.failures.inc()
        with self._lock:
            self._latencies.append(latency_ms)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            lats = list(self._latencies)
        return {
            "calls": self.calls.value,
            "success": self.success.value,
            "failures": self.failures.value,
            "latency": latency_summary(lats),
            "availability": self.available,
            "checksum": self.checksum,
            "version": self.version,
        }


class EngineMonitor:
    """Track phase9_9, trend_rf_v40, and pipeline layer health."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engines: dict[str, _EngineStats] = {
            "phase9_9": _EngineStats(),
            "trend_rf_v40": _EngineStats(),
            "decision": _EngineStats(),
            "calibration": _EngineStats(),
            "risk": _EngineStats(),
            "quality": _EngineStats(),
        }

    def record_call(self, engine_id: str, *, success: bool = True, latency_ms: float = 0.0) -> None:
        with self._lock:
            stats = self._engines.setdefault(engine_id, _EngineStats())
        stats.record(success=success, latency_ms=latency_ms)

    def set_engine_meta(self, engine_id: str, *, checksum: str | None, version: str | None, available: bool = True) -> None:
        with self._lock:
            stats = self._engines.setdefault(engine_id, _EngineStats())
        stats.checksum = checksum
        stats.version = version
        stats.available = available

    def build_report(self) -> dict[str, Any]:
        with self._lock:
            return {eid: eng.to_dict() for eid, eng in self._engines.items()}
