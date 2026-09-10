"""Phase 27H stress simulation engine (research-only, read-only)."""

from __future__ import annotations

import copy
import random
from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.research.phase26a.exit_simulator import simulate_trade_exit

MC_SEED = 42


def compute_atr(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    frame = candles.copy()
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    tr = pd.concat(
        [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def recompute_pnl(
    *,
    entry_price: float,
    exit_price: float,
    direction: str,
    lot: float,
    symbol: str,
) -> float:
    mult = 1 if direction == "BUY" else -1
    cs = contract_size(symbol)
    return round((exit_price - entry_price) * mult * cs * lot, 4)


def apply_spread_stress(trades: list[dict[str, Any]], pct_increase: float) -> list[dict[str, Any]]:
    """Increase round-trip spread cost by pct_increase (25 = +25%)."""
    mult = 1.0 + pct_increase / 100.0
    out: list[dict[str, Any]] = []
    for t in trades:
        spread = float(t.get("spread") or 0.30)
        lot = float(t.get("lot") or 0.01)
        sym = str(t.get("symbol") or "XAUUSD")
        extra = spread * (mult - 1.0) * contract_size(sym) * lot * 2.0
        adj = copy.deepcopy(t)
        adj["pnl"] = round(float(t["pnl"]) - extra, 4)
        adj["stress_spread_pct"] = pct_increase
        out.append(adj)
    return out


def apply_slippage_stress(
    trades: list[dict[str, Any]],
    atr_mult: float,
    candles: pd.DataFrame,
    atr: pd.Series,
) -> list[dict[str, Any]]:
    """Apply entry and exit slippage of atr_mult * ATR (worse fill)."""
    if atr_mult <= 0:
        return copy.deepcopy(trades)
    out: list[dict[str, Any]] = []
    for t in trades:
        adj = copy.deepcopy(t)
        bar_idx = int(t.get("bar_index") or 0)
        bar_idx = min(max(bar_idx, 0), len(candles) - 1)
        slip = float(atr.iloc[bar_idx]) * atr_mult
        entry = float(t["entry_price"])
        exit_p = float(t["exit_price"])
        direction = str(t["direction"])
        lot = float(t.get("lot") or 0.01)
        sym = str(t.get("symbol") or "XAUUSD")
        if direction == "BUY":
            entry += slip
            exit_p -= slip
        else:
            entry -= slip
            exit_p += slip
        adj["entry_price"] = entry
        adj["exit_price"] = exit_p
        adj["pnl"] = recompute_pnl(
            entry_price=entry,
            exit_price=exit_p,
            direction=direction,
            lot=lot,
            symbol=sym,
        )
        adj["stress_slippage_atr"] = atr_mult
        out.append(adj)
    return out


def apply_execution_delay(
    trades: list[dict[str, Any]],
    delay_bars: int,
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
) -> list[dict[str, Any]]:
    """Re-simulate exits after delaying entry by N candles."""
    if delay_bars <= 0:
        return copy.deepcopy(trades)
    frame = candles.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
    out: list[dict[str, Any]] = []
    for t in trades:
        adj = copy.deepcopy(t)
        bar_idx = int(t.get("bar_index") or 0) + delay_bars
        if bar_idx >= len(frame):
            bar_idx = len(frame) - 1
        entry_ts = pd.to_datetime(frame.index[bar_idx], utc=True).isoformat()
        entry_price = float(frame.iloc[bar_idx]["close"])
        direction = str(t["direction"])
        sl = t.get("sl")
        tp = t.get("tp")
        lot = float(t.get("lot") or 0.01)
        exit_info = simulate_trade_exit(
            candles=frame,
            entry_ts=entry_ts,
            entry_price=entry_price,
            sl=float(sl) if sl is not None else None,
            tp=float(tp) if tp is not None else None,
            is_buy=direction == "BUY",
            lot=lot,
            symbol=symbol,
        )
        if exit_info.get("exit_reason") == "no_data":
            adj["pnl"] = float(t["pnl"])
            out.append(adj)
            continue
        adj["entry_price"] = entry_price
        adj["exit_price"] = float(exit_info["exit_price"])
        adj["pnl"] = float(exit_info["pnl"])
        adj["exit_reason"] = exit_info["exit_reason"]
        adj["duration_bars"] = int(exit_info["duration_bars"])
        adj["pnl_r"] = float(exit_info.get("pnl_r") or 0.0)
        adj["stress_delay_bars"] = delay_bars
        out.append(adj)
    return out


def apply_position_costs(
    trades: list[dict[str, Any]],
    *,
    commission_per_lot_round: float = 7.0,
    swap_per_lot_per_day: float = -2.5,
) -> list[dict[str, Any]]:
    """Subtract spread (already in sim), commission, and estimated swap."""
    out: list[dict[str, Any]] = []
    for t in trades:
        adj = copy.deepcopy(t)
        lot = float(t.get("lot") or 0.01)
        spread = float(t.get("spread") or 0.30)
        sym = str(t.get("symbol") or "XAUUSD")
        spread_cost = spread * contract_size(sym) * lot * 2.0
        commission = commission_per_lot_round * lot
        days_held = max(float(t.get("duration_sec") or 0) / 86400.0, 1 / 288)
        swap_cost = abs(swap_per_lot_per_day) * lot * days_held
        total_cost = spread_cost + commission + swap_cost
        adj["pnl"] = round(float(t["pnl"]) - total_cost, 4)
        adj["cost_breakdown"] = {
            "spread": round(spread_cost, 4),
            "commission": round(commission, 4),
            "swap": round(swap_cost, 4),
            "total": round(total_cost, 4),
        }
        out.append(adj)
    return out


def subsample_trades(trades: list[dict[str, Any]], keep_ratio: float, rng: random.Random) -> list[dict[str, Any]]:
    if keep_ratio >= 1.0:
        return copy.deepcopy(trades)
    n_keep = max(1, int(len(trades) * keep_ratio))
    indices = sorted(rng.sample(range(len(trades)), n_keep))
    return [copy.deepcopy(trades[i]) for i in indices]


def shuffle_trades(trades: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    shuffled = copy.deepcopy(trades)
    rng.shuffle(shuffled)
    return shuffled
