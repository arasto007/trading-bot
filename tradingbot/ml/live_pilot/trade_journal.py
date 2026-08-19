"""Phase 12 — live pilot trade journal."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    live_pilot_config_path,
    live_pilot_daily_report_path,
    live_pilot_equity_path,
    live_pilot_errors_path,
    live_pilot_execution_path,
    live_pilot_orders_path,
    live_pilot_risk_path,
    live_pilot_run_dir,
    live_pilot_signals_path,
    live_pilot_trades_path,
)


class TradeJournal:
    """Append-only JSON journal for live pilot runs."""

    def __init__(self, run_id: str, *, base_dir: str | Path | None = None) -> None:
        self.run_id = run_id
        self.base_dir = base_dir
        self.run_dir = live_pilot_run_dir(run_id, base_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._buffers: dict[str, list[Any]] = {
            "trades": [],
            "orders": [],
            "signals": [],
            "risk": [],
            "execution": [],
            "errors": [],
            "equity_curve": [],
        }

    def write_config(self, config: dict[str, Any]) -> None:
        live_pilot_config_path(self.run_id, self.base_dir).write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )

    def log_signal(self, row: dict[str, Any]) -> None:
        self._buffers["signals"].append({**row, "logged_at": _now()})

    def log_risk(self, row: dict[str, Any]) -> None:
        self._buffers["risk"].append({**row, "logged_at": _now()})

    def log_order(self, row: dict[str, Any]) -> None:
        self._buffers["orders"].append({**row, "logged_at": _now()})

    def log_execution(self, row: dict[str, Any]) -> None:
        self._buffers["execution"].append({**row, "logged_at": _now()})

    def log_trade(self, row: dict[str, Any]) -> None:
        self._buffers["trades"].append({**row, "logged_at": _now()})

    def log_error(self, row: dict[str, Any]) -> None:
        self._buffers["errors"].append({**row, "logged_at": _now()})

    def log_equity(self, row: dict[str, Any]) -> None:
        self._buffers["equity_curve"].append({**row, "logged_at": _now()})

    def flush(self) -> dict[str, str]:
        paths = {
            "trades": _write_json(live_pilot_trades_path(self.run_id, self.base_dir), self._buffers["trades"]),
            "orders": _write_json(live_pilot_orders_path(self.run_id, self.base_dir), self._buffers["orders"]),
            "signals": _write_json(live_pilot_signals_path(self.run_id, self.base_dir), self._buffers["signals"]),
            "risk": _write_json(live_pilot_risk_path(self.run_id, self.base_dir), self._buffers["risk"]),
            "execution": _write_json(
                live_pilot_execution_path(self.run_id, self.base_dir), self._buffers["execution"]
            ),
            "errors": _write_json(live_pilot_errors_path(self.run_id, self.base_dir), self._buffers["errors"]),
            "equity_curve": _write_json(
                live_pilot_equity_path(self.run_id, self.base_dir), self._buffers["equity_curve"]
            ),
        }
        return {k: str(v) for k, v in paths.items()}

    def write_daily_report(self, report: dict[str, Any]) -> Path:
        path = live_pilot_daily_report_path(self.run_id, self.base_dir)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, rows: list[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, list):
            rows = existing + rows
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return path
