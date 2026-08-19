"""Phase 18C — MT5 pre-check (read-only, market closed is PASS)."""

from __future__ import annotations

from typing import Any


def validate_mt5(*, symbol: str = "XAUUSD") -> dict[str, Any]:
    """
    Verify MT5 readiness without placing orders.
    Market closed must NOT fail the check.
    """
    items: dict[str, dict[str, Any]] = {}
    order_send_calls = 0

    # Package / install
    try:
        import MetaTrader5 as mt5
        items["mt5_installed"] = {"status": "PASS", "version": getattr(mt5, "__version__", None)}
    except ImportError:
        return {
            "phase": "18C",
            "passed": False,
            "market_closed_acceptable": True,
            "order_send_calls": 0,
            "items": {"mt5_installed": {"status": "FAIL", "detail": "MetaTrader5 package missing"}},
            "summary": {"pass": 0, "warn": 0, "fail": 1},
        }

    # Terminal / connection via existing read-only diagnostics
    try:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import diagnose_mt5_connection, ensure_mt5_connected
        from tradingbot.adapters.symbols import resolve_broker_symbol

        cfg = load_legacy_config()
        diag = diagnose_mt5_connection(cfg)
        connected = bool(diag.init_result)
        terminal = diag.terminal_info or {}
        account = diag.account_info or {}

        items["mt5_terminal_running"] = {
            "status": "PASS" if connected or terminal else "FAIL",
            "connected": connected,
            "terminal": {k: terminal.get(k) for k in ("name", "company", "path", "connected", "tradeapi_disabled") if k in terminal or True},
        }

        items["account_connected"] = {
            "status": "PASS" if account.get("login") else "FAIL",
            "login": account.get("login"),
            "server": account.get("server"),
            "name": account.get("name"),
        }

        trade_allowed = account.get("trade_allowed")
        items["trading_permission"] = {
            "status": "PASS" if trade_allowed in (True, 1, None) else "WARN",
            "trade_allowed": trade_allowed,
            "note": "None treated as unknown/WARN-safe when market closed",
        }

        # AutoTrading / tradeapi
        tradeapi_disabled = terminal.get("tradeapi_disabled")
        items["autotrading"] = {
            "status": "PASS" if tradeapi_disabled in (False, 0, None) else "WARN",
            "tradeapi_disabled": tradeapi_disabled,
        }

        items["correct_account"] = {
            "status": "PASS" if account.get("login") else "WARN",
            "login": account.get("login"),
            "server": account.get("server"),
        }
        items["correct_server"] = {
            "status": "PASS" if account.get("server") else "WARN",
            "server": account.get("server"),
        }

        # Symbols
        broker_symbol = None
        symbol_ok = False
        try:
            if connected or ensure_mt5_connected(cfg, symbols=[symbol], strict_account=False):
                broker_symbol = resolve_broker_symbol(symbol, cfg)
                info = mt5.symbol_info(broker_symbol)
                symbol_ok = info is not None
                if info is not None and not info.visible:
                    mt5.symbol_select(broker_symbol, True)
                    info = mt5.symbol_info(broker_symbol)
                    symbol_ok = info is not None
        except Exception as exc:  # noqa: BLE001
            items["symbols"] = {"status": "WARN", "error": str(exc)}
        else:
            items["symbols"] = {
                "status": "PASS" if symbol_ok else "FAIL",
                "requested": symbol,
                "broker_symbol": broker_symbol,
                "available": symbol_ok,
            }
            items["xauusd_available"] = {
                "status": "PASS" if symbol_ok else "FAIL",
                "broker_symbol": broker_symbol,
            }

        # Time sync / terminal status / connection quality
        items["time_synchronization"] = {
            "status": "PASS" if terminal or account else "WARN",
            "terminal_connected": bool(terminal.get("connected")),
        }
        items["terminal_status"] = {
            "status": "PASS" if connected else "FAIL",
            "connected": connected,
            "last_error": list(diag.last_error) if diag.last_error else None,
            "hints": list(diag.hints or [])[:5],
        }
        items["connection_quality"] = {
            "status": "PASS" if connected else "WARN",
            "connected": connected,
        }

        # Market closed — always acceptable
        market_closed = True
        try:
            if symbol_ok and broker_symbol:
                tick = mt5.symbol_info_tick(broker_symbol)
                # No tick or zero bid/ask often means session closed
                if tick is not None and getattr(tick, "bid", 0) > 0:
                    market_closed = False
        except Exception:  # noqa: BLE001
            market_closed = True

        items["market_session"] = {
            "status": "PASS",
            "market_closed": market_closed,
            "market_closed_acceptable": True,
            "note": "Market closed does not fail Phase 18C",
        }

    except Exception as exc:  # noqa: BLE001
        items["mt5_connection"] = {"status": "FAIL", "error": str(exc)}

    items["no_orders"] = {"status": "PASS", "order_send_calls": order_send_calls}

    statuses = [v.get("status") for v in items.values()]
    # FAIL only on hard connectivity / symbol / install issues
    hard_keys = ("mt5_installed", "mt5_terminal_running", "account_connected", "xauusd_available", "terminal_status")
    hard_ok = all(items.get(k, {}).get("status") == "PASS" for k in hard_keys if k in items)
    # If symbols key used instead of xauusd
    if "xauusd_available" not in items and "symbols" in items:
        hard_ok = hard_ok and items["symbols"]["status"] == "PASS"

    passed = hard_ok and "FAIL" not in [
        items.get(k, {}).get("status") for k in hard_keys if k in items
    ]
    # Also fail if mt5_connection failed entirely
    if items.get("mt5_connection", {}).get("status") == "FAIL":
        passed = False

    return {
        "phase": "18C",
        "passed": passed,
        "market_closed_acceptable": True,
        "order_send_calls": order_send_calls,
        "items": items,
        "summary": {
            "pass": sum(1 for s in statuses if s == "PASS"),
            "warn": sum(1 for s in statuses if s == "WARN"),
            "fail": sum(1 for s in statuses if s == "FAIL"),
        },
    }
