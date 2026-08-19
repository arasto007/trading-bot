"""بررسی سلامت اتصال MT5."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class Mt5HealthStatus:
    connected: bool
    terminal_ok: bool
    tick_age_sec: float | None
    reason: str = "ok"


def check_autotrading_ready(
    symbol: str,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Real trade permission probe — terminal flags + order_check.

    order_check alone can return 0 while order_send still hits 10027 on some builds.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return False, "MetaTrader5 not installed"

    from tradingbot.adapters.mt5_utils import verify_attached_account
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.domain import order_logic

    cfg = config or {}
    ok_acc, acc_msg = verify_attached_account(cfg, strict=True)
    if not ok_acc:
        return False, acc_msg

    ti = mt5.terminal_info()
    if ti is None or not getattr(ti, "connected", False):
        return False, "terminal not connected"

    tradeapi_disabled = bool(getattr(ti, "tradeapi_disabled", False))
    trade_allowed = bool(getattr(ti, "trade_allowed", False))

    ai = mt5.account_info()
    if ai is not None and not bool(getattr(ai, "trade_allowed", True)):
        return False, "account trade_allowed=False — check broker/account restrictions"

    broker = resolve_broker_symbol(symbol, cfg)
    if not mt5.symbol_select(broker, True):
        return False, f"symbol {broker} not selectable"

    info = mt5.symbol_info(broker)
    tick = mt5.symbol_info_tick(broker)
    if info is None or tick is None:
        return False, f"no quote for {broker}"

    if not bool(getattr(info, "trade_mode", 0)):
        return False, f"symbol {broker} trade disabled"

    type_filling = {
        "FOK": mt5.ORDER_FILLING_FOK,
        "IOC": mt5.ORDER_FILLING_IOC,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }[order_logic.filling_mode_name(int(info.filling_mode))]

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": broker,
        "volume": max(float(info.volume_min or 0.01), 0.01),
        "type": mt5.ORDER_TYPE_BUY,
        "price": float(tick.ask),
        "deviation": 20,
        "magic": 234000,
        "comment": "autotrading_probe",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": type_filling,
    }
    result = mt5.order_check(request)
    if result is None:
        err = mt5.last_error()
        return False, f"order_check failed: {err}"

    retcode = int(getattr(result, "retcode", -1))
    comment = str(getattr(result, "comment", "") or "")
    if retcode == 0:
        if tradeapi_disabled:
            return False, (
                "Python API trading blocked (tradeapi_disabled=True) — "
                "MT5: Tools -> Options -> Expert Advisors -> "
                "UNCHECK 'Disable automatic trading through external Python API'"
            )
        if not trade_allowed:
            return False, (
                "AutoTrading toolbar OFF (trade_allowed=False) — press Ctrl+E until GREEN"
            )
        return True, "order_check OK — AutoTrading ready"

    if retcode == 10027:
        trade_allowed = bool(getattr(ti, "trade_allowed", False))
        return False, (
            f"AutoTrading OFF (10027) trade_allowed={trade_allowed} — "
            "enable Algo Trading Ctrl+E on the LiteFinance terminal"
        )

    return False, f"order_check {retcode}: {comment}"


def check_mt5_health(symbol: str, *, max_tick_age_sec: float = 120.0) -> Mt5HealthStatus:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return Mt5HealthStatus(False, False, None, "MetaTrader5 not installed")

    ti = mt5.terminal_info()
    if ti is None or not getattr(ti, "connected", False):
        return Mt5HealthStatus(False, False, None, "terminal not connected")

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return Mt5HealthStatus(True, True, None, "no tick for symbol")

    tick_time = int(getattr(tick, "time", 0) or 0)
    if tick_time <= 0:
        return Mt5HealthStatus(True, True, None, "tick time missing")

    age = max(0.0, time.time() - tick_time)
    if age > max_tick_age_sec:
        return Mt5HealthStatus(True, True, age, f"stale tick ({age:.0f}s)")
    return Mt5HealthStatus(True, True, age, "ok")
