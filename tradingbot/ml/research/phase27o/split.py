"""Phase 27O — chronological train/validation split (70/30)."""

from __future__ import annotations

from typing import Any

TRAIN_FRACTION = 0.70


def _sort_key(trade: dict[str, Any]) -> str:
    return str(trade.get("timestamp") or trade.get("exit_timestamp") or "")


def split_trades_chronological(
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    *,
    train_fraction: float = TRAIN_FRACTION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (train_trades, val_trades, train_sim, val_sim) preserving chronological order."""
    if not trades:
        return [], [], [], []
    pairs = list(zip(trades, sim_results))
    pairs.sort(key=lambda p: _sort_key(p[0]))
    n = len(pairs)
    cut = max(1, min(n - 1, int(n * train_fraction)))
    train_pairs = pairs[:cut]
    val_pairs = pairs[cut:]
    train_t, train_s = zip(*train_pairs) if train_pairs else ([], [])
    val_t, val_s = zip(*val_pairs) if val_pairs else ([], [])
    return list(train_t), list(val_t), list(train_s), list(val_s)
