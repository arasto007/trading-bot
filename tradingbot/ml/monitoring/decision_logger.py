"""Phase 15C — decision trace logger."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.monitoring.config import live_dir
from tradingbot.ml.phase15a.config import BUNDLE_VERSION


class DecisionLogger:
    """Log every TradingSignal / decision with full explainability fields."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._path = live_dir(base_dir) / "decisions.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def log(
        self,
        *,
        timestamp: str | None = None,
        symbol: str,
        timeframe: str,
        regime: str,
        engine: str | None,
        direction: str,
        confidence: float,
        quality: float,
        risk: float,
        latency_ms: dict[str, float],
        trace_id: str,
        checksum: str,
        decision_reason: list[str],
        bundle_version: str = BUNDLE_VERSION,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": regime,
            "engine": engine,
            "direction": direction,
            "confidence": round(confidence, 6),
            "quality": round(quality, 6),
            "risk": round(risk, 6),
            "latency": latency_ms,
            "trace_id": trace_id,
            "bundle_version": bundle_version,
            "checksum": checksum,
            "decision_reason": decision_reason,
        }
        if extra:
            record.update(extra)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        return record

    def read_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(ln) for ln in lines if ln.strip()]
        return rows[-limit:]

    def count(self) -> int:
        if not self._path.is_file():
            return 0
        return sum(1 for ln in self._path.read_text(encoding="utf-8").splitlines() if ln.strip())
