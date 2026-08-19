#!/usr/bin/env python3
"""Verify MT5 execution path via order_check only — no real trades."""

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
    import MetaTrader5 as mt5

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_health import check_autotrading_ready
    from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5
    from tradingbot.services.demo_account_guard import verify_demo_account_or_abort

    cfg = load_legacy_config()
    cfg["BASE_DIR"] = str(ROOT)

    print("=== EXECUTION CHECK (order_check only — no real trade) ===")

    demo_ok, demo_msg = verify_demo_account_or_abort(config=cfg)
    print(f"demo_guard: {demo_msg}")
    if not demo_ok:
        return 1

    if not attach_mt5_session(cfg, symbols=["XAUUSD"], strict_account=False, use_lock=False):
        print(f"ABORT — MT5 not connected: {mt5.last_error()}")
        return 1

    try:
        ti = mt5.terminal_info()
        print(
            f"terminal.trade_allowed={getattr(ti, 'trade_allowed', None)} "
            f"connected={getattr(ti, 'connected', None)}"
        )

        auto_ok, auto_reason = check_autotrading_ready("XAUUSD", config=cfg)
        print(f"autotrading: {auto_reason}")
        if not auto_ok:
            print("ABORT — fix AutoTrading in MT5 (Ctrl+E + Expert Advisors option)")
            return 1

        ai = mt5.account_info()
        if ai:
            print(f"Balance={ai.balance:.2f} Equity={ai.equity:.2f}")
        print("\nEXECUTION CHECK: PASS (no order placed)")
        return 0
    finally:
        safe_release_mt5()


if __name__ == "__main__":
    raise SystemExit(main())
