"""Persistent emergency stop — survives process restart until explicit reset."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "emergency_stop.json"


def activate_emergency_stop(reason: str, *, source: str = "kill_switch") -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": True,
        "reason": reason,
        "source": source,
        "activated_utc": datetime.now(timezone.utc).isoformat(),
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def is_emergency_stop_active() -> bool:
    if not STATE_PATH.is_file():
        return False
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return bool(data.get("active"))
    except Exception:
        return False


def read_emergency_stop() -> dict[str, Any] | None:
    if not STATE_PATH.is_file():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if data.get("active"):
            return data
    except Exception:
        pass
    return None


def clear_emergency_stop() -> None:
    """Explicit operator reset — required before trading resumes after emergency stop."""
    if not STATE_PATH.is_file():
        return
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        data["active"] = False
        data["cleared_utc"] = datetime.now(timezone.utc).isoformat()
        STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        try:
            STATE_PATH.unlink()
        except FileNotFoundError:
            pass
