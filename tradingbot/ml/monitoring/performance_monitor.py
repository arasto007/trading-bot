"""Phase 15C — signal performance statistics."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingbot.ml.monitoring.config import live_dir
from tradingbot.ml.monitoring.statistics import rate


class PerformanceMonitor:
    """Aggregate signals/hour, direction mix, regime/engine share."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._decisions: list[dict[str, Any]] = []
        self._fallbacks = 0

    def ingest_decision(self, record: dict[str, Any]) -> None:
        self._decisions.append(record)

    def ingest_fallback(self) -> None:
        self._fallbacks += 1

    def build_report(self) -> dict[str, Any]:
        if not self._decisions:
            return {
                "signals_per_hour": 0.0,
                "buy": 0, "sell": 0, "hold": 0,
                "regime_pct": {}, "engine_pct": {},
                "fallback_pct": 0.0,
                "avg_confidence": 0.0, "avg_quality": 0.0, "avg_risk": 0.0,
            }

        directions = Counter(str(d.get("direction", "HOLD")) for d in self._decisions)
        regimes = Counter(str(d.get("regime", "UNKNOWN")) for d in self._decisions)
        engines = Counter(str(d.get("engine") or "none") for d in self._decisions)
        n = len(self._decisions)

        timestamps = []
        for d in self._decisions:
            try:
                timestamps.append(datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00")))
            except Exception:
                pass
        hours_span = 1.0
        if len(timestamps) >= 2:
            hours_span = max((timestamps[-1] - timestamps[0]).total_seconds() / 3600.0, 0.01)

        confidences = [float(d.get("confidence", 0)) for d in self._decisions]
        qualities = [float(d.get("quality", 0)) for d in self._decisions]
        risks = [float(d.get("risk", 0)) for d in self._decisions]

        return {
            "signals_per_hour": round(n / hours_span, 2),
            "buy": directions.get("BUY", 0),
            "sell": directions.get("SELL", 0),
            "hold": directions.get("HOLD", 0),
            "regime_pct": {k: rate(v, n) for k, v in regimes.items()},
            "engine_pct": {k: rate(v, n) for k, v in engines.items()},
            "fallback_pct": rate(self._fallbacks, n + self._fallbacks),
            "avg_confidence": round(sum(confidences) / n, 4),
            "avg_quality": round(sum(qualities) / n, 4),
            "avg_risk": round(sum(risks) / n, 4),
            "total_decisions": n,
            "total_fallbacks": self._fallbacks,
        }

    def write_report(self) -> Path:
        report = self.build_report()
        path = live_dir(self._base_dir) / "performance_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path
