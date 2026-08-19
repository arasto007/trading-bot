"""Phase 20A — continuous live reporting."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.phase20a.config import reports_dir


class Phase20aReporter:
    """Thread-safe JSON report writer for live deployment."""

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        self._dir = reports_dir(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._live_trades: list[dict[str, Any]] = []
        self._equity: list[dict[str, Any]] = []
        self._risk_events: list[dict[str, Any]] = []
        self._execution_log: list[dict[str, Any]] = []
        self._latency: list[dict[str, Any]] = []
        self._drawdown: list[dict[str, Any]] = []
        self._health: list[dict[str, Any]] = []
        self._signals: list[dict[str, Any]] = []

    @property
    def output_dir(self) -> Path:
        return self._dir

    def log_signal(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._signals.append(row)
            if len(self._signals) > 5000:
                self._signals = self._signals[-3000:]

    def log_trade(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._live_trades.append(row)

    def log_risk(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._risk_events.append(row)

    def log_execution(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._execution_log.append(row)

    def log_latency(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._latency.append(row)

    def log_equity(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._equity.append(row)

    def log_drawdown(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._drawdown.append(row)

    def log_health(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._health.append(row)

    def flush_all(self) -> dict[str, str]:
        with self._lock:
            paths = {
                "live_trades": self._write("live_trades.json", self._live_trades),
                "live_equity": self._write("live_equity.json", self._equity),
                "risk_events": self._write("risk_events.json", self._risk_events),
                "execution_log": self._write("execution_log.json", self._execution_log),
                "latency_live": self._write("latency_live.json", self._latency),
                "drawdown_live": self._write("drawdown_live.json", self._drawdown),
                "health_live": self._write("health_live.json", self._health),
            }
        return paths

    def write_session_summary(self, summary: dict[str, Any]) -> str:
        path = self._dir / "session_summary.json"
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return str(path)

    def write_final_report(self, report: dict[str, Any]) -> str:
        path = self._dir / "phase20a_final_report.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return str(path)

    def _write(self, name: str, data: list[dict[str, Any]]) -> str:
        path = self._dir / name
        payload = {
            "phase": "20A",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(data),
            "records": data[-2000:],
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)
