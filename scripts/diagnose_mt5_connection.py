#!/usr/bin/env python3
"""MT5 connection diagnostic — read-only, attach-only (no initialize/shutdown storms)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import MetaTrader5 as mt5

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.mt5_utils import (
    attach_mt5_session,
    diagnose_mt5_connection,
    discover_terminal_path,
    is_mt5_session_connected,
    read_terminal_session_hint,
)
from tradingbot.adapters.symbols import resolve_broker_symbol


def main() -> int:
    print("=== MT5 Python package ===")
    print("version:", mt5.__version__)

    print("\n=== Terminal discovery ===")
    path = discover_terminal_path()
    print("terminal_path:", path)
    session = read_terminal_session_hint()
    print("session_hint:", session)

    print("\n=== Attach-only probe (no shutdown/login) ===")
    cfg = load_legacy_config()
    attached = attach_mt5_session(cfg, symbols=["XAUUSD"])
    print("attach result:", attached)
    print("session_connected:", is_mt5_session_connected())
    print("last_error:", mt5.last_error())
    print("terminal_info:", mt5.terminal_info())
    print("account_info:", mt5.account_info())

    print("\n=== Full diagnostic (attach-only) ===")
    diag = diagnose_mt5_connection(cfg)
    print(json.dumps(diag.to_dict(), indent=2, default=str))

    if diag.init_result:
        broker = resolve_broker_symbol("XAUUSD", cfg)
        info = mt5.symbol_info(broker)
        tick = mt5.symbol_info_tick(broker)
        print("\n=== Symbol check ===")
        print(f"XAUUSD resolved -> {broker}")
        print("symbol visible:", info.visible if info else None)
        print("tick bid/ask:", (tick.bid, tick.ask) if tick else None)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
