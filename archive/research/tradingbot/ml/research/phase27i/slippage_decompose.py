"""Phase 27I slippage decomposition utilities (research-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.research.phase27h.stress_engine import compute_atr, recompute_pnl

SLIPPAGE_ATR_MULT = 0.25


def _slip_dollars(slip_price: float, lot: float, symbol: str) -> float:
    return round(slip_price * contract_size(symbol) * lot, 4)


def slippage_for_trade(
    trade: dict[str, Any],
    atr: pd.Series,
    *,
    atr_mult: float = SLIPPAGE_ATR_MULT,
) -> dict[str, Any]:
    bar_idx = int(trade.get("bar_index") or 0)
    bar_idx = min(max(bar_idx, 0), len(atr) - 1)
    atr_val = float(atr.iloc[bar_idx])
    slip = atr_val * atr_mult
    entry = float(trade["entry_price"])
    exit_p = float(trade["exit_price"])
    direction = str(trade["direction"])
    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")
    baseline_pnl = float(trade["pnl"])

    entry_adj = entry + slip if direction == "BUY" else entry - slip
    exit_adj = exit_p - slip if direction == "BUY" else exit_p + slip

    pnl_entry_only = recompute_pnl(
        entry_price=entry_adj, exit_price=exit_p, direction=direction, lot=lot, symbol=sym
    )
    pnl_exit_only = recompute_pnl(
        entry_price=entry, exit_price=exit_adj, direction=direction, lot=lot, symbol=sym
    )
    pnl_both = recompute_pnl(
        entry_price=entry_adj, exit_price=exit_adj, direction=direction, lot=lot, symbol=sym
    )

    entry_loss = baseline_pnl - pnl_entry_only
    exit_loss = baseline_pnl - pnl_exit_only
    total_loss = baseline_pnl - pnl_both

    sl = trade.get("sl")
    tp = trade.get("tp")
    risk_unit = abs(entry - float(sl)) if sl is not None else None
    tp_dist = abs(float(tp) - entry) if tp is not None else None

    rr_after = None
    if risk_unit and risk_unit > 0:
        mult = 1 if direction == "BUY" else -1
        rr_after = round(((exit_adj - entry_adj) * mult) / risk_unit, 4)

    return {
        "timestamp": trade.get("timestamp"),
        "direction": direction,
        "regime": trade.get("regime"),
        "duration_bars": int(trade.get("duration_bars") or 0),
        "baseline_pnl": baseline_pnl,
        "pnl_after_slippage": pnl_both,
        "entry_slippage_loss": round(entry_loss, 4),
        "exit_slippage_loss": round(exit_loss, 4),
        "total_slippage_loss": round(total_loss, 4),
        "slippage_pct_of_baseline_pnl": round(100.0 * total_loss / baseline_pnl, 2) if baseline_pnl else None,
        "atr_at_entry": round(atr_val, 4),
        "slip_price_one_side": round(slip, 4),
        "slip_dollars_one_side": _slip_dollars(slip, lot, sym),
        "round_trip_slip_dollars": round(_slip_dollars(slip, lot, sym) * 2, 4),
        "spread": float(trade.get("spread") or 0.30),
        "spread_atr_ratio": round(float(trade.get("spread") or 0.30) / atr_val, 4) if atr_val > 0 else None,
        "planned_rr": trade.get("rr"),
        "realized_rr": trade.get("pnl_r"),
        "rr_after_slippage": rr_after,
        "tp_distance": round(tp_dist, 4) if tp_dist is not None else None,
        "sl_distance": round(risk_unit, 4) if risk_unit is not None else None,
        "tp_atr_ratio": round(tp_dist / atr_val, 4) if tp_dist and atr_val > 0 else None,
        "lot": lot,
    }


def enrich_all_trades(
    trades: list[dict[str, Any]],
    candles: pd.DataFrame,
    *,
    atr_mult: float = SLIPPAGE_ATR_MULT,
) -> list[dict[str, Any]]:
    atr = compute_atr(candles)
    return [slippage_for_trade(t, atr, atr_mult=atr_mult) for t in trades]
