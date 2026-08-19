"""Paper trade exit resolution on historical or live candle data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.services.exit_mode import ExitMode, resolve_exit_mode
from tradingbot.services.exit_policy import resolve_exit


def resolve_paper_trade_exit(
    *,
    candles: pd.DataFrame,
    entry_ts: str,
    entry_price: float,
    sl: float | None,
    tp: float | None,
    is_buy: bool,
    lot: float,
    symbol: str,
    max_hold_bars: int = 72,
    spread: float = 0.30,
    exit_mode: ExitMode | str | None = None,
    config: dict | None = None,
) -> dict[str, Any]:
    """Walk forward from entry bar to resolve exit per configured exit policy."""
    if isinstance(exit_mode, ExitMode):
        mode = exit_mode
    elif exit_mode is not None:
        mode = resolve_exit_mode(str(exit_mode))
    else:
        mode = resolve_exit_mode(config=config)

    return resolve_exit(
        exit_mode=mode,
        candles=candles,
        entry_ts=entry_ts,
        entry_price=entry_price,
        sl=sl,
        tp=tp,
        is_buy=is_buy,
        lot=lot,
        symbol=symbol,
        max_hold_bars=max_hold_bars,
        spread=spread,
    )
