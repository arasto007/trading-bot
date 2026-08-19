"""Phase 27J per-trade edge decomposition (research-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.research.phase27h.stress_engine import compute_atr
from tradingbot.ml.research.phase27i.slippage_decompose import slippage_for_trade

COMMISSION_PER_LOT = 7.0
SWAP_PER_LOT_DAY = 2.5
POST_EXIT_BARS = 72


def _risk_unit(entry: float, sl: float | None) -> float:
    if sl is None:
        return 0.0
    return abs(entry - float(sl))


def _post_exit_favorable_r(
    candles: pd.DataFrame,
    trade: dict[str, Any],
    *,
    max_bars: int = POST_EXIT_BARS,
) -> float:
    frame = candles.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
    exit_ts = pd.to_datetime(trade["exit_timestamp"], utc=True)
    exit_idx = int(frame.index.searchsorted(exit_ts))
    if exit_idx >= len(frame) - 1:
        return 0.0
    entry = float(trade["entry_price"])
    exit_price = float(trade["exit_price"])
    sl = trade.get("sl")
    risk = _risk_unit(entry, float(sl) if sl is not None else None)
    if risk <= 0:
        return 0.0
    direction = str(trade["direction"])
    is_buy = direction == "BUY"
    best = 0.0
    end = min(exit_idx + max_bars, len(frame) - 1)
    for j in range(exit_idx + 1, end + 1):
        bar = frame.iloc[j]
        high = float(bar["high"])
        low = float(bar["low"])
        if is_buy:
            fav = max(0.0, (high - exit_price) / risk)
        else:
            fav = max(0.0, (exit_price - low) / risk)
        best = max(best, fav)
    return round(best, 4)


def enrich_trade_edge(
    trade: dict[str, Any],
    candles: pd.DataFrame,
    atr: pd.Series,
) -> dict[str, Any]:
    entry = float(trade["entry_price"])
    exit_p = float(trade["exit_price"])
    direction = str(trade["direction"])
    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")
    mult = 1 if direction == "BUY" else -1
    cs = contract_size(sym)
    sl = trade.get("sl")
    tp = trade.get("tp")
    risk = _risk_unit(entry, float(sl) if sl is not None else None)

    gross_edge = round((exit_p - entry) * mult * cs * lot, 4)
    spread_cost = round(float(trade.get("spread") or 0.30) * cs * lot * 2.0, 4)
    commission = round(COMMISSION_PER_LOT * lot, 4)
    days_held = max(float(trade.get("duration_sec") or 0) / 86400.0, 1 / 288)
    swap_cost = round(abs(SWAP_PER_LOT_DAY) * lot * days_held, 4)
    slip_info = slippage_for_trade(trade, atr)
    slippage_cost = float(slip_info["total_slippage_loss"])

    net_edge = round(gross_edge - spread_cost - commission - swap_cost, 4)
    net_after_slippage = round(net_edge - slippage_cost, 4)

    mfe_r = float(trade.get("mfe") or 0.0)
    mae_r = float(trade.get("mae") or 0.0)
    pnl_r = float(trade.get("pnl_r") or 0.0)
    mfe_price = round(mfe_r * risk, 4) if risk > 0 else 0.0
    captured_price = round(abs(exit_p - entry), 4)
    captured_r = pnl_r
    capture_efficiency = round(captured_r / mfe_r, 4) if mfe_r > 0 else None
    missed_r = round(max(0.0, mfe_r - max(0.0, captured_r)), 4)

    tp_dist = abs(float(tp) - entry) if tp is not None else None
    sl_dist = risk
    post_exit_r = _post_exit_favorable_r(candles, trade)

    planned_rr = float(trade.get("rr") or 0.0) if trade.get("rr") is not None else None
    initial_risk_dollars = round(risk * cs * lot, 4) if risk > 0 else None

    exit_timing_loss = round(missed_r * initial_risk_dollars, 4) if initial_risk_dollars else 0.0

    return {
        "timestamp": trade.get("timestamp"),
        "direction": direction,
        "regime": trade.get("regime"),
        "engine": trade.get("engine"),
        "confidence": float(trade.get("confidence") or 0.0),
        "risk_percent": trade.get("risk_percent"),
        "lot": lot,
        "exit_reason": str(trade.get("exit_reason") or "").lower(),
        "duration_bars": int(trade.get("duration_bars") or 0),
        "gross_edge": gross_edge,
        "spread_cost": spread_cost,
        "commission": commission,
        "swap": swap_cost,
        "slippage_cost": slippage_cost,
        "net_edge": net_edge,
        "net_after_slippage": net_after_slippage,
        "baseline_pnl": float(trade["pnl"]),
        "initial_risk_dollars": initial_risk_dollars,
        "initial_risk_price": round(risk, 4) if risk > 0 else None,
        "planned_rr": planned_rr,
        "final_r": pnl_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "mfe_price": mfe_price,
        "captured_move_price": captured_price,
        "captured_r": captured_r,
        "capture_efficiency": capture_efficiency,
        "missed_opportunity_r": missed_r,
        "tp_distance": round(tp_dist, 4) if tp_dist is not None else None,
        "sl_distance": round(sl_dist, 4) if sl_dist else None,
        "sl_buffer_remaining_r": round(max(0.0, 1.0 - mae_r), 4) if mae_r else None,
        "post_exit_favorable_r": post_exit_r,
        "post_exit_opportunity_r": post_exit_r,
        "exit_timing_loss_dollars": exit_timing_loss,
        "atr_at_entry": slip_info.get("atr_at_entry"),
    }


def enrich_all_edges(trades: list[dict[str, Any]], candles: pd.DataFrame) -> list[dict[str, Any]]:
    atr = compute_atr(candles)
    return [enrich_trade_edge(t, candles, atr) for t in trades]
