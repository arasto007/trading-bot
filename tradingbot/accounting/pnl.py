"""Canonical PnL calculations — delegates to production exit_policy formula."""

from __future__ import annotations

from tradingbot.domain.position_logic import contract_size
from tradingbot.services.exit_policy import _pnl as _exit_policy_pnl


def calculate_pnl(
    entry: float,
    exit_price: float,
    *,
    is_buy: bool,
    lot: float,
    symbol: str,
) -> float:
    """Single dollar-PnL entry point used by all accounting consumers."""
    return _exit_policy_pnl(entry, exit_price, is_buy=is_buy, lot=lot, symbol=symbol)


def calculate_pnl_r(
    pnl: float,
    entry: float,
    sl: float | None,
    *,
    lot: float,
    symbol: str,
) -> float:
    if sl is None or entry <= 0 or lot <= 0:
        return 0.0
    risk = abs(entry - float(sl))
    if risk <= 0:
        return 0.0
    risk_money = risk * contract_size(symbol) * lot
    if risk_money <= 0:
        return 0.0
    return round(pnl / risk_money, 4)
