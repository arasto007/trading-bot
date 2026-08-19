"""Phase 15C — latency measurement and reporting."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from tradingbot.ml.monitoring.config import live_dir
from tradingbot.ml.monitoring.statistics import ThreadSafeStore, latency_summary


class LatencyMonitor:
    """Measure per-stage inference latency."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._store = ThreadSafeStore()
        self._report_path = live_dir(base_dir) / "latency_report.json"

    def record(
        self,
        *,
        feature_ms: float = 0.0,
        regime_ms: float = 0.0,
        engine_ms: float = 0.0,
        decision_ms: float = 0.0,
        risk_ms: float = 0.0,
        quality_ms: float = 0.0,
        total_ms: float = 0.0,
        mapping_ms: float = 0.0,
    ) -> dict[str, float]:
        entry = {
            "feature_ms": round(feature_ms, 3),
            "regime_ms": round(regime_ms, 3),
            "engine_ms": round(engine_ms, 3),
            "decision_ms": round(decision_ms, 3),
            "risk_ms": round(risk_ms, 3),
            "quality_ms": round(quality_ms, 3),
            "mapping_ms": round(mapping_ms, 3),
            "total_inference_ms": round(total_ms, 3),
        }
        self._store.append(entry)
        return entry

    def record_from_breakdown(self, breakdown: dict[str, float]) -> dict[str, float]:
        return self.record(
            feature_ms=breakdown.get("features_ms", 0.0),
            regime_ms=breakdown.get("regime_ms", 0.0),
            engine_ms=breakdown.get("engine_ms", 0.0),
            decision_ms=breakdown.get("decision_ms", 0.0),
            risk_ms=breakdown.get("risk_ms", 0.0),
            quality_ms=breakdown.get("quality_ms", 0.0),
            mapping_ms=breakdown.get("mapping_ms", 0.0),
            total_ms=breakdown.get("total_ms", 0.0),
        )

    def build_report(self) -> dict[str, Any]:
        rows = self._store.snapshot()
        totals = [r["total_inference_ms"] for r in rows]
        report = {
            "total_inference": latency_summary(totals),
            "feature_time": latency_summary([r["feature_ms"] for r in rows]),
            "regime_time": latency_summary([r["regime_ms"] for r in rows]),
            "engine_time": latency_summary([r["engine_ms"] for r in rows]),
            "decision_time": latency_summary([r["decision_ms"] for r in rows]),
            "risk_time": latency_summary([r["risk_ms"] for r in rows]),
            "quality_time": latency_summary([r["quality_ms"] for r in rows]),
            "samples": len(rows),
        }
        return report

    def write_report(self) -> Path:
        report = self.build_report()
        with self._lock:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return self._report_path
