"""لاگ تصمیمات meta-labeler در لایو — برای ارزیابی واقعی عملکرد."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "data" / "meta_decisions.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


OBSERVER_LOG_PATH = ROOT / "logs" / "engines" / "meta_observer_events.jsonl"
FALSE_NEGATIVE_PATH = ROOT / "logs" / "engines" / "meta_false_negative_candidates.jsonl"


def log_meta_observer_event(
    *,
    symbol: str,
    timeframe: str,
    meta_score: float,
    meta_threshold: float,
    meta_would_reject: bool,
    meta_observer_mode: bool,
    signal_direction: str = "",
    gating: bool | None = None,
    rejected: bool = False,
    reason: str = "",
) -> None:
    """Truth-monitor Meta without using it as a live gate."""
    OBSERVER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now_iso(),
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": signal_direction,
        "meta_score": round(float(meta_score), 4),
        "meta_threshold": round(float(meta_threshold), 4),
        "meta_would_reject": bool(meta_would_reject),
        "meta_observer_mode": bool(meta_observer_mode),
        "gating": gating,
        "rejected": bool(rejected),
        "reason": reason,
    }
    with OBSERVER_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def setup_snapshot_id(
    *,
    timestamp: str,
    symbol: str,
    direction: str,
    entry: float | None,
    stop_loss: float | None,
) -> str:
    import hashlib

    raw = "|".join(
        [
            str(timestamp or ""),
            str(symbol or ""),
            str(direction or ""),
            f"{float(entry or 0.0):.5f}",
            f"{float(stop_loss or 0.0):.5f}",
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def log_meta_false_negative_candidate(
    *,
    timestamp: str,
    symbol: str,
    direction: str,
    meta_score: float,
    threshold: float,
    features: dict[str, Any] | None = None,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    timeframe: str = "M5",
    extra: dict[str, Any] | None = None,
) -> None:
    """Telemetry only — does not change Meta gating."""
    FALSE_NEGATIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    snap_id = setup_snapshot_id(
        timestamp=timestamp,
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
    )
    row = {
        "timestamp": timestamp,
        "symbol": symbol,
        "direction": direction,
        "meta_score": round(float(meta_score), 4),
        "threshold": round(float(threshold), 4),
        "setup_snapshot_id": snap_id,
        "features": features or {},
        "timeframe": timeframe,
        "entry": None if entry is None else round(float(entry), 5),
        "stop_loss": None if stop_loss is None else round(float(stop_loss), 5),
        "take_profit": None if take_profit is None else round(float(take_profit), 5),
        "logged_at": _now_iso(),
    }
    if extra:
        row.update(extra)
    try:
        from tradingbot.services.jsonl_rotation import append_rotating_jsonl

        append_rotating_jsonl(FALSE_NEGATIVE_PATH, row)
    except Exception:
        with FALSE_NEGATIVE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def log_meta_decision(
    *,
    symbol: str,
    timeframe: str,
    allowed: bool,
    meta_prob: float,
    threshold: float,
    reason: str = "",
    features: dict[str, float] | None = None,
    signal_direction: str = "",
) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now_iso(),
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": signal_direction,
        "allowed": allowed,
        "meta_prob": round(meta_prob, 4),
        "threshold": round(threshold, 4),
        "reason": reason,
        "features": features or {},
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_trade_outcome(
    *,
    symbol: str,
    timeframe: str,
    ticket: int | None,
    pnl: float,
    r_multiple: float,
    entry_features: dict[str, float] | None = None,
    meta_prob: float | None = None,
) -> None:
    """پس از بسته شدن معامله در لایو — برای مقایسه با پیش‌بینی meta."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now_iso(),
        "event": "trade_closed",
        "symbol": symbol,
        "timeframe": timeframe,
        "ticket": ticket,
        "pnl": round(pnl, 2),
        "r_multiple": round(r_multiple, 4),
        "meta_prob_at_entry": meta_prob,
        "features": entry_features or {},
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def recent_stats(max_lines: int = 500) -> dict[str, Any]:
    """خلاصه آخرین تصمیمات برای مانیتورینگ."""
    if not LOG_PATH.is_file():
        return {"decisions": 0, "accepted": 0, "rejected": 0, "closed_trades": 0}

    decisions = accepted = rejected = closed = 0
    wins = 0
    lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    for line in lines[-max_lines:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "trade_closed":
            closed += 1
            if float(row.get("pnl", 0)) > 0:
                wins += 1
        elif "allowed" in row:
            decisions += 1
            if row.get("allowed"):
                accepted += 1
            else:
                rejected += 1

    return {
        "decisions": decisions,
        "accepted": accepted,
        "rejected": rejected,
        "closed_trades": closed,
        "live_win_rate_pct": round(wins / closed * 100, 2) if closed else None,
        "log_path": str(LOG_PATH),
    }
