#!/usr/bin/env python3
"""Quick MT5 attach test — prints connection status, does NOT shutdown if connected."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.adapters.mt5_utils import (
    is_mt5_session_connected,
    mt5_session_context,
    read_terminal_session_hint,
)


def main() -> int:
    config = load_legacy_config()
    session = read_terminal_session_hint()
    result: dict[str, object] = {
        "session_hint": session,
        "connected": False,
        "experts_algo_disabled": session.get("experts_algo_enabled") is False,
    }

    with mt5_session_context(config, read_only=True, symbols=[PRIMARY_SYMBOL]) as connected:
        result["connected"] = connected
        result["session_connected_after_attach"] = is_mt5_session_connected()

        if connected:
            import MetaTrader5 as mt5

            terminal = mt5.terminal_info()
            account = mt5.account_info()
            result["terminal"] = terminal._asdict() if terminal else None
            result["account"] = account._asdict() if account else None
            result["last_error"] = mt5.last_error()
        else:
            import MetaTrader5 as mt5

            result["last_error"] = mt5.last_error()

    print(json.dumps(result, indent=2, default=str))
    status_path = ROOT / "logs" / "mt5_connection_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if result.get("experts_algo_disabled"):
        status_path.write_text(
            json.dumps(
                {
                    **result,
                    "blocker": "experts_algo_disabled",
                    "hints": [
                        "Click Algo Trading (green) on MT5 toolbar",
                        "Tools → Options → Expert Advisors → Allow automated trading",
                    ],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    return 0 if result.get("connected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
