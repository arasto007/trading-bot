"""Phase 20C — load real broker execution records from Phase 20A only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase20c.config import MIN_REAL_TRADES, phase20a_reports_dir


def _load_json(path: Path) -> dict[str, Any] | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _records(payload: dict[str, Any] | list | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        recs = payload.get("records")
        if isinstance(recs, list):
            return [r for r in recs if isinstance(r, dict)]
    return []


def _is_real_fill(row: dict[str, Any]) -> bool:
    """True only for successful broker fills (ticket present or success=True)."""
    if row.get("blocked"):
        return False
    if row.get("success") is False:
        return False
    ticket = row.get("ticket")
    if ticket is not None and str(ticket) not in ("", "0", "None"):
        return True
    if row.get("success") is True and row.get("fill_price") is not None:
        return True
    return False


def load_broker_executions(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Load Phase 20A live reports — real broker data only, no simulation."""
    root = phase20a_reports_dir(base_dir)
    files = {
        "live_trades": root / "live_trades.json",
        "execution_log": root / "execution_log.json",
        "latency_live": root / "latency_live.json",
        "risk_events": root / "risk_events.json",
        "live_equity": root / "live_equity.json",
        "drawdown_live": root / "drawdown_live.json",
        "health_live": root / "health_live.json",
        "session_summary": root / "session_summary.json",
        "final_report": root / "phase20a_final_report.json",
    }
    loaded = {k: _load_json(p) for k, p in files.items()}

    executions = _records(loaded["execution_log"])
    trades = _records(loaded["live_trades"])
    latency = _records(loaded["latency_live"])
    risk_events = _records(loaded["risk_events"])
    equity = _records(loaded["live_equity"])
    drawdown = _records(loaded["drawdown_live"])
    health = _records(loaded["health_live"])

    real_fills = [e for e in executions if _is_real_fill(e)]
    real_trades = [t for t in trades if _is_real_fill(t) or t.get("ticket")]
    # Prefer execution_log fills; fall back to live_trades with tickets
    if not real_fills and real_trades:
        real_fills = real_trades

    return {
        "phase": "20C",
        "source": "phase20a_broker_reports",
        "reports_dir": str(root),
        "files_present": {k: files[k].is_file() for k in files},
        "all_executions": executions,
        "real_fills": real_fills,
        "live_trades": trades,
        "latency": latency,
        "risk_events": risk_events,
        "equity": equity,
        "drawdown": drawdown,
        "health": health,
        "session_summary": loaded.get("session_summary") or {},
        "final_report": loaded.get("final_report") or {},
        "real_fill_count": len(real_fills),
        "has_sufficient_trades": len(real_fills) >= MIN_REAL_TRADES,
        "min_required": MIN_REAL_TRADES,
    }
