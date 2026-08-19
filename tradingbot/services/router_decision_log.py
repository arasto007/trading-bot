"""Phase 46C — multi-engine router decision log."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_LOG = Path(__file__).resolve().parents[2] / "logs" / "router_decisions.jsonl"


def router_log_path() -> Path:
    raw = os.environ.get("ROUTER_DECISION_LOG", "")
    return Path(raw) if raw else _DEFAULT_LOG


def append_router_decision(event: dict[str, Any]) -> None:
    from tradingbot.services.jsonl_rotation import append_rotating_jsonl

    path = router_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if "logged_at" not in event:
        event["logged_at"] = datetime.now(timezone.utc).isoformat()
    append_rotating_jsonl(path, event)


def record_router_decision(
    *,
    timestamp: str,
    pa_signal: str,
    vol_signal: str,
    adaptive_signal: str,
    selected_engine: str,
    rejection_reason: str,
    symbol: str = "",
    timeframe: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "timestamp": timestamp,
        "symbol": symbol,
        "timeframe": timeframe,
        "pa_signal": pa_signal,
        "vol_signal": vol_signal,
        "adaptive_signal": adaptive_signal,
        "selected_engine": selected_engine,
        "rejection_reason": rejection_reason,
    }
    if extra:
        payload.update(extra)
    append_router_decision(payload)
