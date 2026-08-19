"""Block live execution on real MT5 accounts unless explicitly allowed."""

from __future__ import annotations

import os
from typing import Any


def allow_real_account_trading() -> bool:
    return os.getenv("TRADINGBOT_ALLOW_REAL", "").strip().lower() in ("1", "true", "yes")


def verify_demo_account_or_abort(*, config: dict[str, Any] | None = None) -> tuple[bool, str]:
    """
    Return (ok, message). Live kernel requires demo account unless TRADINGBOT_ALLOW_REAL=1.
    """
    if allow_real_account_trading():
        return True, "real_account_allowed_by_env"

    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session, is_mt5_lock_held_by_other

        cfg = config or {}
        if is_mt5_lock_held_by_other():
            login = cfg.get("MT5_LOGIN")
            server = str(cfg.get("MT5_SERVER") or "")
            if "demo" in server.lower():
                return True, f"demo_ok login={login} server={server} (live bot IPC)"
            return False, "demo_guard_deferred_live_bot_ipc"

        if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
            return False, "mt5_not_connected"

        acc = mt5.account_info()
        if acc is None:
            return False, "account_info_unavailable"

        trade_mode = int(getattr(acc, "trade_mode", -1))
        # 0=demo, 1=contest, 2=real
        if trade_mode == 0:
            return True, f"demo_ok login={acc.login} server={acc.server}"
        if trade_mode == 1:
            return True, f"contest_ok login={acc.login}"

        return False, (
            f"real_account_blocked login={acc.login} server={acc.server} "
            f"trade_mode={trade_mode} — set TRADINGBOT_ALLOW_REAL=1 to override"
        )
    except Exception as exc:
        return False, f"demo_guard_error: {exc}"
