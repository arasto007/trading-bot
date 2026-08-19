#!/usr/bin/env python3
"""PHASE 21C — live telemetry health snapshot (read-only)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _count_today_jsonl(path: Path, *, hold_only: bool = False) -> int:
    if not path.is_file():
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    n = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                blob = str(row.get("timestamp") or row.get("ts") or row.get("logged_at") or "")
                if today not in blob:
                    continue
                if hold_only and str(row.get("event", "pa_hold")).lower() not in ("pa_hold", "hold"):
                    continue
                n += 1
    except OSError:
        return 0
    return n


def _last_non_hold_utc() -> str:
    paths = [
        ROOT / "logs" / "engines" / "pa_live_decisions.jsonl",
        ROOT / "logs" / "phase17a" / "pa_live_decisions.jsonl",
        ROOT / "logs" / "engines" / "pa_events.jsonl",
        ROOT / "logs" / "router_decisions.jsonl",
    ]
    latest: datetime | None = None
    for path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-400:]
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            reason = str(row.get("reject_reason") or row.get("event") or "").lower()
            if reason in ("pa_hold", "hold") or reason.startswith("outside_") or "hold" in reason:
                if reason != "signal_emitted":
                    continue
            if reason == "signal_emitted" or row.get("event") in ("trade_open", "pa_signal") or row.get("selected_engine"):
                ts = _parse_ts(row.get("timestamp") or row.get("ts") or row.get("logged_at"))
                if ts is not None and (latest is None or ts > latest):
                    latest = ts
                    break
    return latest.isoformat() if latest else ""


def _watchdog_alive() -> str:
    from tradingbot.services.live_loop_health import WATCHDOG_HEARTBEAT_PATH

    if WATCHDOG_HEARTBEAT_PATH.is_file():
        try:
            row = json.loads(WATCHDOG_HEARTBEAT_PATH.read_text(encoding="utf-8"))
            ts = _parse_ts(row.get("timestamp_utc"))
            if ts is not None:
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                return "YES" if age <= 90 else "NO"
        except (OSError, json.JSONDecodeError):
            pass
    log = ROOT / "logs" / "watchdog.log"
    if log.is_file():
        age = datetime.now(timezone.utc).timestamp() - log.stat().st_mtime
        return "YES" if age <= 3600 else "NO"
    return "NO"


def _live_symbol() -> str:
    from tradingbot.config.live import PRIMARY_SYMBOL, get_live_config

    cfg = get_live_config()
    symbols = cfg.get("SYMBOLS") or cfg.get("symbols") or [PRIMARY_SYMBOL]
    return str(symbols[0] if symbols else PRIMARY_SYMBOL)


def snapshot() -> dict[str, str]:
    from tradingbot.services.live_loop_health import HEARTBEAT_PATH, ROUTER_ACTIVITY_PATH, read_heartbeat
    from tradingbot.services.rejection_events import rejection_log_path

    now = datetime.now(timezone.utc)
    hb = read_heartbeat()
    hb_age = ""
    if hb:
        ts = _parse_ts(hb.get("timestamp_utc"))
        if ts is not None:
            hb_age = str(int(round((now - ts).total_seconds())))
    elif HEARTBEAT_PATH.is_file():
        hb_age = str(int(round(now.timestamp() - HEARTBEAT_PATH.stat().st_mtime)))

    router_calls = 0
    pa_hold_counter = 0
    if ROUTER_ACTIVITY_PATH.is_file():
        try:
            act = json.loads(ROUTER_ACTIVITY_PATH.read_text(encoding="utf-8"))
            if str(act.get("date")) == now.date().isoformat():
                router_calls = int(act.get("router_calls", 0) or 0)
                pa_hold_counter = int(act.get("pa_hold", 0) or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    hold_file = _count_today_jsonl(ROOT / "logs" / "engines" / "pa_hold_reasons.jsonl", hold_only=True)
    pa_hold_today = max(pa_hold_counter, hold_file)

    rej = rejection_log_path()
    size_mb = round(rej.stat().st_size / (1024 * 1024), 3) if rej.is_file() else 0.0

    return {
        "heartbeat_age_sec": hb_age if hb_age != "" else "NA",
        "router_calls_today": str(router_calls),
        "pa_hold_today": str(pa_hold_today),
        "last_non_hold_utc": _last_non_hold_utc() or "NA",
        "rejection_log_size_mb": f"{size_mb:.3f}",
        "watchdog_alive": _watchdog_alive(),
        "live_symbol": _live_symbol(),
    }


def format_snapshot(data: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in data.items()) + "\n"


def main() -> int:
    text = format_snapshot(snapshot())
    print(text, end="", flush=True)
    out = ROOT / "logs" / "phase21c_health_snapshot.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())