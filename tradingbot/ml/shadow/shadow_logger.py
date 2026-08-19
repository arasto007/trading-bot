"""Phase D — ML shadow event log (predictions only, no execution)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_LOG = Path(__file__).resolve().parents[3] / "logs" / "ml_shadow_events.jsonl"


def shadow_log_path() -> Path:
    raw = os.environ.get("ML_SHADOW_LOG", "")
    return Path(raw) if raw else _DEFAULT_LOG


def append_shadow_event(event: dict[str, Any]) -> None:
    path = shadow_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if "logged_at" not in event:
        event["logged_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, default=str) + "\n")


def record_shadow_cycle(payload: dict[str, Any]) -> None:
    append_shadow_event({"event": "shadow_cycle", **payload})


def record_shadow_outcome(
    *,
    timestamp: str,
    ticket: int | None,
    direction: str,
    pnl_r: float,
    pnl: float,
    exit_reason: str,
    engine: str = "",
) -> None:
    append_shadow_event({
        "event": "shadow_outcome",
        "timestamp": timestamp,
        "ticket": ticket,
        "direction": direction,
        "final_trade_result": {
            "pnl_r": round(float(pnl_r), 4),
            "pnl": round(float(pnl), 2),
            "exit_reason": exit_reason,
            "engine": engine,
        },
    })


def record_shadow_entry(
    *,
    ticket: int,
    symbol: str,
    timeframe: str,
    live_engine_direction: str,
    ml_prediction_direction: str,
    ml_probability: float | None,
    live_engine: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Cache ML vs live at trade entry — joined on close into shadow_trade_record."""
    append_shadow_event({
        "event": "shadow_entry",
        "ticket": int(ticket),
        "symbol": symbol,
        "timeframe": timeframe,
        "live_engine_direction": live_engine_direction,
        "ml_prediction_direction": ml_prediction_direction,
        "ml_probability": round(float(ml_probability), 4) if ml_probability is not None else None,
        "live_engine": live_engine,
        **(extra or {}),
    })


def record_shadow_trade_record(
    *,
    timestamp: str,
    ticket: int | None,
    live_engine_direction: str,
    ml_prediction_direction: str,
    ml_probability: float | None,
    pnl: float,
    pnl_r: float,
    exit_reason: str,
    live_engine: str = "",
) -> None:
    """Phase 49A — one row per closed live trade with ML shadow comparison."""
    live_dir = str(live_engine_direction).upper()
    ml_dir = str(ml_prediction_direction).upper()
    agrees = ml_dir in ("BUY", "SELL") and ml_dir == live_dir
    append_shadow_event({
        "event": "shadow_trade_record",
        "timestamp": timestamp,
        "ticket": ticket,
        "live_engine_direction": live_dir,
        "ml_prediction_direction": ml_dir,
        "ml_probability": round(float(ml_probability), 4) if ml_probability is not None else None,
        "ml_agrees_with_live": agrees,
        "live_engine": live_engine,
        "final_trade_result": {
            "pnl": round(float(pnl), 2),
            "exit_reason": exit_reason,
        },
        "final_trade_R": round(float(pnl_r), 4),
    })
