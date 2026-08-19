#!/usr/bin/env python3
"""Write data/live_account.json from MT5 (safe when bot IPC lock is free)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import attach_mt5_session, is_mt5_lock_held_by_other
    from tradingbot.services.runtime_truth import refresh_live_equity_from_mt5, write_live_account_cache

    if is_mt5_lock_held_by_other():
        print("SKIP|bot holds MT5 lock — restart bot once for live balance updates")
        return 1
    cfg = load_legacy_config()
    if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
        print("FAIL|MT5 attach failed")
        return 1
    if not refresh_live_equity_from_mt5(log_freeze=False):
        print("FAIL|account_info unavailable")
        return 1
    write_live_account_cache()
    print("OK|data/live_account.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
