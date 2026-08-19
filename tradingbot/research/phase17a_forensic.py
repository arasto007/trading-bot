"""PHASE 17A — PA live forensic telemetry (observability only).

Does not affect routing, execution, or strategy decisions.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "logs" / "phase17a"
DECISIONS_PATH = OUT_DIR / "pa_live_decisions.jsonl"
NEAR_MISS_PATH = OUT_DIR / "pa_near_miss.jsonl"
QUALITY_NEAR_MISS = 55

_lock = threading.Lock()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, default=str)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def is_near_miss(
    *,
    sweep_ok: bool,
    reclaim_ok: bool,
    bos_ok: bool,
    fvg_ok: bool,
    quality_score: float,
) -> bool:
    if not (sweep_ok and reclaim_ok and bos_ok):
        return False
    return (not fvg_ok) or float(quality_score or 0.0) < QUALITY_NEAR_MISS


def record_pa_forensic_decision(
    *,
    timestamp: Any,
    symbol: str,
    timeframe: str,
    session_ok: bool,
    asian_range_ready: bool,
    sweep_detected: bool,
    reclaim_ok: bool,
    bos_ok: bool,
    fvg_ok: bool,
    confidence: float,
    quality_score: float,
    reject_reason: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write one HOLD/decision forensic row. Never raises into the trading path."""
    try:
        ts = timestamp
        if hasattr(ts, "isoformat"):
            ts_s = ts.isoformat()
        else:
            ts_s = str(ts)
        row = {
            "timestamp": ts_s,
            "logged_at": _now_utc(),
            "symbol": symbol,
            "timeframe": timeframe,
            "session_ok": bool(session_ok),
            "asian_range_ready": bool(asian_range_ready),
            "sweep_detected": bool(sweep_detected),
            "reclaim_ok": bool(reclaim_ok),
            "bos_ok": bool(bos_ok),
            "fvg_ok": bool(fvg_ok),
            "confidence": float(confidence or 0.0),
            "quality_score": float(quality_score or 0.0),
            "reject_reason": str(reject_reason or "unknown"),
        }
        if extra:
            row.update(extra)
        tf = str(timeframe or "").upper().replace("5M", "M5")
        if tf == "M5":
            try:
                from tradingbot.config.price_action import get_price_action_config
                from tradingbot.domain.gold_strategies.m5_london_sweep import m5_hour15_telemetry

                row.update(m5_hour15_telemetry(get_price_action_config(symbol, "M5")))
            except Exception:
                row.setdefault("hour15_mode", True)
                row.setdefault("asian_end_utc", 8)
        _append_jsonl(DECISIONS_PATH, row)
        try:
            engines = ROOT / "logs" / "engines" / "pa_live_decisions.jsonl"
            _append_jsonl(engines, row)
        except Exception:
            pass
        if is_near_miss(
            sweep_ok=bool(sweep_detected),
            reclaim_ok=bool(reclaim_ok),
            bos_ok=bool(bos_ok),
            fvg_ok=bool(fvg_ok),
            quality_score=float(quality_score or 0.0),
        ):
            _append_jsonl(NEAR_MISS_PATH, {**row, "event": "pa_near_miss"})
    except Exception:
        pass
