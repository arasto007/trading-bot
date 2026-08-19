"""Structured rejection logging for the adaptive live path."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = ROOT / "logs" / "rejection_events.jsonl"

_lock = Lock()
_enabled = True
_counter_mode = False
_counts: Counter[str] = Counter()


def enable_counter_mode(enabled: bool = True) -> None:
    global _counter_mode
    _counter_mode = enabled
    if enabled:
        _counts.clear()


def get_rejection_counts() -> dict[str, int]:
    return dict(_counts)


def reset_rejection_counts() -> None:
    _counts.clear()


def set_rejection_logging_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = enabled


def rejection_log_path() -> Path:
    raw = os.environ.get("TRADINGBOT_REJECTION_LOG", "")
    if raw.strip():
        return Path(raw)
    return DEFAULT_LOG_PATH


def _ensure_log_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def log_rejection_event(
    *,
    stage: str,
    reason: str,
    symbol: str = "XAUUSD",
    direction: str | None = None,
    context: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> None:
    """Append one structured rejection line. Does not affect trading decisions."""
    if not _enabled:
        return

    if _counter_mode:
        with _lock:
            _counts[stage] += 1
        return

    event = {
        "ts": (ts or datetime.now(timezone.utc)).isoformat(),
        "symbol": symbol,
        "stage": stage,
        "direction": direction,
        "reason": reason,
        "context": context or {},
    }
    path = rejection_log_path()
    with _lock:
        from tradingbot.services.jsonl_rotation import append_rotating_jsonl

        _ensure_log_dir(path)
        append_rotating_jsonl(path, event)


def row_context(row: Any) -> dict[str, Any]:
    """Extract diagnostic fields from an adaptive frame row."""
    try:
        ema20 = float(row.get("ema20", 0))
        ema50 = float(row.get("ema50", 0))
        close = float(row.get("close", 1))
        sep = abs(ema20 - ema50) / max(close, 1.0) if close else 0.0
        return {
            "atr_pct": round(float(row.get("atr_pct", 0)), 4),
            "rsi14": round(float(row.get("rsi14", 0)), 2),
            "ema_sep_pct": round(sep * 100, 4),
            "hour_utc": int(row.get("hour_utc", 0)),
            "h1_trend": int(row.get("h1_trend", 0)),
            "regime": str(row.get("_regime", "")),
        }
    except Exception:
        return {}


def map_risk_reason_to_stage(reason: str) -> str:
    """Map RiskGate denial text to a rejection stage label."""
    lower = (reason or "").lower()
    if "cooldown" in lower or "wait" in lower:
        return "COOLDOWN"
    if "daily" in lower or "loss budget" in lower or "max trades" in lower:
        return "DAILY_LIMIT"
    return "RISKGATE"
