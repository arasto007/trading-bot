"""Load Phase 26A trade history — never fabricate trades."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PHASE26A_DIR = Path(__file__).resolve().parents[1] / "phase26a"
TRADE_LOG_PATH = PHASE26A_DIR / "trade_log.json"

MINIMUM_SAMPLE_SIZE = 200


def load_phase26a_trades(path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    log_path = path or TRADE_LOG_PATH
    if not log_path.is_file():
        return [], {"error": "trade_log_missing", "path": str(log_path)}

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    trades = list(payload.get("trades") or [])
    meta = {
        "source": str(log_path),
        "generated_utc": payload.get("generated_utc"),
        "collection_meta": payload.get("collection_meta") or {},
        "raw_count": payload.get("count", len(trades)),
    }
    return trades, meta


def completed_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trades with resolved exits — excludes incomplete simulations."""
    return [
        t
        for t in trades
        if str(t.get("exit_reason", "")).lower() not in ("no_data", "", "pending")
        and (t.get("entry_price") or 0) > 0
    ]
