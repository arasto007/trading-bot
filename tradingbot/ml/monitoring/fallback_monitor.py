"""Phase 15C — fallback event monitor."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.monitoring.config import live_dir
from tradingbot.ml.monitoring.statistics import ThreadSafeCounter, rate


class FallbackMonitor:
    """Record ML → legacy fallback events with categorized reasons."""

    CATEGORIES = (
        "ml_unavailable",
        "bundle_missing",
        "checksum_mismatch",
        "prediction_failure",
        "legacy_fallback",
        "pipeline_timeout",
        "unexpected_exception",
    )

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._path = live_dir(base_dir) / "fallback_events.json"
        self._jsonl = live_dir(base_dir) / "fallback_events.jsonl"
        self._total = ThreadSafeCounter()
        self._events: list[dict[str, Any]] = []

    def _classify(self, reason: str) -> str:
        r = reason.lower()
        if "bundle_or_checksum_missing" in r or ("bundle" in r and "missing" in r):
            return "bundle_missing"
        if "checksum" in r:
            return "checksum_mismatch"
        if "timeout" in r:
            return "pipeline_timeout"
        if "prediction" in r:
            return "prediction_failure"
        if "unavailable" in r or "registry" in r:
            return "ml_unavailable"
        if "exception" in r:
            return "unexpected_exception"
        return "legacy_fallback"

    def record(self, reason: str, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        category = self._classify(reason)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "category": category,
            "detail": detail or {},
        }
        with self._lock:
            self._events.append(event)
            self._total.inc()
            self._jsonl.parent.mkdir(parents=True, exist_ok=True)
            with self._jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
        return event

    def build_report(self, *, total_decisions: int = 0) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
        by_cat: dict[str, int] = {}
        for ev in events:
            cat = ev.get("category", "legacy_fallback")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        return {
            "total_fallbacks": len(events),
            "fallback_rate": rate(len(events), total_decisions),
            "by_category": by_cat,
            "recent": events[-50:],
        }

    def write_report(self, *, total_decisions: int = 0) -> Path:
        report = self.build_report(total_decisions=total_decisions)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return self._path
