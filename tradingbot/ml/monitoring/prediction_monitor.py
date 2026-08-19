"""Phase 15C — per-prediction monitor."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from tradingbot.ml.monitoring.config import live_dir
from tradingbot.ml.monitoring.statistics import ThreadSafeCounter, rate


class PredictionMonitor:
    """Store engine probability, confidence, accept/block per prediction."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._accepted = ThreadSafeCounter()
        self._blocked = ThreadSafeCounter()
        self._report_path = live_dir(base_dir) / "prediction_statistics.json"

    def record(
        self,
        *,
        engine: str | None,
        probability: float,
        confidence: float,
        accepted: bool,
        block_reason: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "engine": engine,
            "probability": round(probability, 6),
            "confidence": round(confidence, 6),
            "accepted": accepted,
            "block_reason": block_reason,
            "regime": regime,
        }
        with self._lock:
            self._records.append(entry)
        if accepted:
            self._accepted.inc()
        else:
            self._blocked.inc()
        return entry

    def build_report(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)
        by_engine: dict[str, int] = {}
        block_reasons: dict[str, int] = {}
        confidences: list[float] = []
        for r in records:
            eng = str(r.get("engine") or "none")
            by_engine[eng] = by_engine.get(eng, 0) + 1
            confidences.append(float(r.get("confidence", 0)))
            if not r.get("accepted"):
                reason = str(r.get("block_reason") or "unknown")
                block_reasons[reason] = block_reasons.get(reason, 0) + 1
        return {
            "total_predictions": len(records),
            "accepted": self._accepted.value,
            "blocked": self._blocked.value,
            "accept_rate": rate(self._accepted.value, len(records)),
            "by_engine": by_engine,
            "block_reasons": block_reasons,
            "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
            "recent": records[-50:],
        }

    def write_report(self) -> Path:
        report = self.build_report()
        with self._lock:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return self._report_path
