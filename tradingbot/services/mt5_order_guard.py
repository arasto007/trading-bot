"""Guard MT5 order_send in dry-run and paper modes — single simulation path."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from tradingbot.services.execution_mode import is_dry_run, is_paper, mode_label

logger = logging.getLogger(__name__)


def blocks_broker_orders() -> bool:
    """True when no real broker order_send may execute."""
    return is_dry_run() or is_paper()


def simulated_order_result(mt5: Any, request: dict[str, Any]) -> Any:
    """Return a TRADE_RETCODE_DONE-like result matching paper simulation semantics."""
    price = float(request.get("price", 0.0) or 0.0)
    return SimpleNamespace(
        retcode=mt5.TRADE_RETCODE_DONE,
        comment=f"{mode_label()} — simulated",
        price=price,
        volume=float(request.get("volume", 0.0) or 0.0),
        order=0,
        deal=0,
    )


def guarded_order_send(
    mt5: Any,
    request: dict[str, Any],
    *,
    label: str,
) -> Any:
    """
    Invoke mt5.order_send unless dry-run/paper — then return simulated fill.

    All production order paths must use this helper (except Mt5ExecutionAdapter
    entry path which has its own journal integration).
    """
    if blocks_broker_orders():
        sym = request.get("symbol", "?")
        vol = request.get("volume", "?")
        logger.info(
            "%s: simulated order_send | mode=%s symbol=%s volume=%s action=%s",
            label,
            mode_label(),
            sym,
            vol,
            request.get("action"),
        )
        return simulated_order_result(mt5, request)
    return mt5.order_send(request)
