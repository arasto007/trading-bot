"""Phase 33D — production-faithful rejected signal replay (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.signal_helpers import compute_sl_tp
from tradingbot.domain.session_logic import variable_spread_pips, variable_slippage_pips
from tradingbot.domain.position_logic import pip_size


def replay_with_production_sl_tp(
    ohlcv: pd.DataFrame,
    bar_index: int,
    *,
    direction: str,
    symbol: str = "XAUUSD",
    confidence: float = 0.55,
    spread_pips: float = 3.0,
    commission_per_lot: float = 0.0,
    max_bars: int = 500,
) -> dict[str, Any]:
    """Bar-forward replay using compute_sl_tp SL/TP — no look-ahead, SL priority."""
    if bar_index >= len(ohlcv) - 1 or direction not in ("BUY", "SELL"):
        return {"r_multiple": 0.0, "exit_reason": "no_data", "would_tp": False, "would_sl": False}

    window = ohlcv.iloc[: bar_index + 1]
    signal_int = 1 if direction == "BUY" else -1
    sl, tp, _ = compute_sl_tp(
        window,
        signal_int,
        confidence,
        symbol=symbol,
        strategy_name="ml_kernel_15b",
        timeframe="M5",
    )
    if sl is None or tp is None:
        return {"r_multiple": 0.0, "exit_reason": "no_sl_tp", "would_tp": False, "would_sl": False}

    bar = ohlcv.iloc[bar_index]
    close = float(bar["close"])
    hour = 12
    ts = ohlcv.index[bar_index]
    if hasattr(ts, "hour"):
        hour = int(ts.hour)
    pip = pip_size(symbol)
    half_spread = (variable_spread_pips(spread_pips, hour) / 2.0) * pip
    slip = variable_slippage_pips(0.5, hour) * pip
    is_buy = direction == "BUY"
    entry = close + half_spread + slip if is_buy else close - half_spread - slip
    sl_v, tp_v = float(sl), float(tp)
    r_unit = abs(entry - sl_v)
    if r_unit <= 0:
        return {"r_multiple": 0.0, "exit_reason": "zero_risk", "would_tp": False, "would_sl": False}

    would_tp = False
    would_sl = False
    bars_to_tp = None
    bars_to_sl = None
    exit_reason = "timeout"
    exit_r = 0.0

    end = min(bar_index + max_bars, len(ohlcv) - 1)
    for j in range(bar_index + 1, end + 1):
        hi = float(ohlcv.iloc[j]["high"])
        lo = float(ohlcv.iloc[j]["low"])
        elapsed = j - bar_index
        if is_buy:
            if lo <= sl_v:
                would_sl = True
                bars_to_sl = elapsed
                exit_r = -1.0
                exit_reason = "sl"
                break
            if hi >= tp_v:
                would_tp = True
                bars_to_tp = elapsed
                exit_r = abs(tp_v - entry) / r_unit
                exit_reason = "tp"
                break
        else:
            if hi >= sl_v:
                would_sl = True
                bars_to_sl = elapsed
                exit_r = -1.0
                exit_reason = "sl"
                break
            if lo <= tp_v:
                would_tp = True
                bars_to_tp = elapsed
                exit_r = abs(entry - tp_v) / r_unit
                exit_reason = "tp"
                break
    else:
        close_end = float(ohlcv.iloc[end]["close"])
        if is_buy:
            exit_r = (close_end - entry) / r_unit
        else:
            exit_r = (entry - close_end) / r_unit
        exit_reason = "timeout"

    return {
        "entry_price": round(entry, 5),
        "sl": round(sl_v, 5),
        "tp": round(tp_v, 5),
        "would_tp": would_tp,
        "would_sl": would_sl,
        "bars_to_tp": bars_to_tp,
        "bars_to_sl": bars_to_sl,
        "r_multiple": round(exit_r, 4),
        "exit_reason": exit_reason,
        "would_win": exit_r > 0,
        "would_lose": exit_r < 0,
        "commission_per_lot": commission_per_lot,
    }
