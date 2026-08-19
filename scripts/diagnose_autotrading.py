#!/usr/bin/env python3
"""Diagnose MT5 terminals, account match, and AutoTrading (order_check only)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--attach-only",
        action="store_true",
        help="Attach to running MT5 without shutdown/reinitialize (for post-restart checks)",
    )
    args = parser.parse_args()

    from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other

    if args.attach_only and is_mt5_lock_held_by_other():
        print("=== MT5 Deep Diagnostic ===")
        print("SKIP attach — live bot holds IPC lock (AutoTrading verified at startup)")
        print("\nRESULT: SKIPPED (live bot active)")
        return 0

    import MetaTrader5 as mt5

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_health import check_autotrading_ready
    from tradingbot.adapters.mt5_utils import (
        discover_terminal_path,
        list_terminal_installations,
        safe_attach,
        safe_release_mt5,
        verify_attached_account,
    )
    cfg = load_legacy_config()
    login = cfg.get("MT5_LOGIN")
    server = cfg.get("MT5_SERVER")
    print("=== MT5 Deep Diagnostic ===")
    print(f"config login={login} server={server}")
    print(f"discover_terminal_path -> {discover_terminal_path(cfg)}")
    print("\n-- All MT5 installations --")
    for i, row in enumerate(list_terminal_installations(cfg), 1):
        mark = " <-- MATCH" if row.get("matches_config") else ""
        print(
            f"  [{i}] login={row.get('saved_login')} server={row.get('saved_server')} "
            f"exe={row.get('terminal_exe')}{mark}"
        )

    # Attach to login-matched terminal
    if args.attach_only:
        if not safe_attach(cfg, allow_start=False):
            path = discover_terminal_path(cfg)
            print(f"\nattach FAIL path={path} err={mt5.last_error()}")
            return 1
    else:
        safe_release_mt5(force_shutdown=True)
        path = discover_terminal_path(cfg)
        if not path or not mt5.initialize(path=path, timeout=60_000):
            print(f"\ninitialize FAIL path={path} err={mt5.last_error()}")
            return 1

    try:
        ok, msg = verify_attached_account(cfg, strict=True)
        print(f"\naccount: {'OK' if ok else 'FAIL'} — {msg}")
        if not ok:
            print("\nFIX: add to .env the LiteFinance terminal64.exe path:")
            for row in list_terminal_installations(cfg):
                if row.get("matches_config") and row.get("terminal_exe"):
                    print(f"  MT5_TERMINAL_PATH={row['terminal_exe']}")
            return 1

        ti = mt5.terminal_info()
        ai = mt5.account_info()
        if ti:
            print(
                f"terminal.trade_allowed={ti.trade_allowed} "
                f"tradeapi_disabled={getattr(ti, 'tradeapi_disabled', '?')} "
                f"path={getattr(ti, 'path', '?')}"
            )
        if ai:
            print(f"account.trade_allowed={getattr(ai, 'trade_allowed', '?')}")

        auto_ok, auto_reason = check_autotrading_ready("XAUUSD", config=cfg)
        print(f"autotrading check: {'PASS' if auto_ok else 'FAIL'} — {auto_reason}")

        if auto_ok:
            print("\nRESULT: EXECUTION READY (order_check only — no real trade placed)")
            return 0

        ti = mt5.terminal_info()
        if ti and getattr(ti, "tradeapi_disabled", False):
            print(
                "FIX Python API: Tools -> Options -> Expert Advisors -> "
                "UNCHECK 'Disable automatic trading through external Python API'"
            )
        if ti and not getattr(ti, "trade_allowed", True):
            print("FIX toolbar: Ctrl+E until Algo Trading button is GREEN")
        print(f"\nRESULT: {auto_reason}")
        return 1
    finally:
        safe_release_mt5()


if __name__ == "__main__":
    raise SystemExit(main())
