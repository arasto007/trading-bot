"""Build trade log from unified AccountingEngine output — no duplicate PnL math."""

from __future__ import annotations

from typing import Any


def trades_from_accounting(
    accounting_export: dict[str, Any] | None,
    *,
    fallback_trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return closed trades from accounting engine export."""
    if accounting_export and accounting_export.get("trades"):
        trades = list(accounting_export["trades"])
        for t in trades:
            if t.get("rr") is None and t.get("sizing"):
                pass
        return trades
    if fallback_trades:
        return list(fallback_trades)
    return []


def trades_from_replay_meta(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract trades from replay meta accounting section."""
    if meta.get("closed_trades"):
        return list(meta["closed_trades"])
    accounting = meta.get("accounting") or {}
    return trades_from_accounting(accounting)


# Backward-compatible alias — now reads from accounting, never re-resolves exits.
def build_hybrid_trades(
    records: list[dict[str, Any]],
    candles=None,
    *,
    symbol: str = "XAUUSD",
    meta: dict[str, Any] | None = None,
    accounting_export: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    del records, candles, symbol
    if meta is not None:
        trades = trades_from_replay_meta(meta)
        if trades:
            return trades
    return trades_from_accounting(accounting_export)
