#!/usr/bin/env python3
"""Quick test: attach to MT5 without disconnecting the GUI session."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.mt5_utils import (
    attach_mt5_session,
    is_mt5_already_connected,
    mt5_ipc_lock,
    safe_release_mt5,
)
from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def _terminal_snapshot() -> dict:
    try:
        import MetaTrader5 as mt5

        terminal = mt5.terminal_info()
        account = mt5.account_info()
        return {
            "connected": bool(terminal and terminal.connected),
            "terminal": terminal._asdict() if terminal else None,
            "account_login": getattr(account, "login", None) if account else None,
            "last_error": mt5.last_error(),
        }
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    config = load_legacy_config()
    before = _terminal_snapshot()
    print("BEFORE:", json.dumps(before, indent=2, default=str))

    with mt5_ipc_lock(config, purpose="test_attach"):
        already = is_mt5_already_connected()
        print(f"is_mt5_already_connected={already}")

        ok = attach_mt5_session(config, use_lock=False)
        after = _terminal_snapshot()
        print("AFTER attach:", json.dumps(after, indent=2, default=str))

        if not ok:
            print("FAIL: attach_mt5_session returned False")
            return 2

        if before.get("connected") and not after.get("connected"):
            print("FAIL: GUI session was disconnected!")
            return 3

        print("PASS: attach succeeded without disconnecting GUI")
        return 0
    # lock released; still no shutdown
    safe_release_mt5()


if __name__ == "__main__":
    raise SystemExit(main())
