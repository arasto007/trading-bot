"""Phase 27K losing trade enrichment (research-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain import indicators
from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.research.phase27a.metrics import _engine_norm, _regime_norm

SWING_LOOKBACK = 10


def _atr_percentile(atr_series: pd.Series, idx: int) -> float | None:
    if idx < 0 or idx >= len(atr_series):
        return None
    window = atr_series.iloc[max(0, idx - 500) : idx + 1]
    if window.empty:
        return None
    val = float(atr_series.iloc[idx])
    return round(100.0 * (window <= val).sum() / len(window), 2)


def _ema_alignment(close: float, ema20: float, ema50: float, direction: str) -> str:
    if direction == "BUY":
        if close > ema20 > ema50:
            return "bullish_aligned"
        if close < ema20 < ema50:
            return "bearish_misaligned"
        return "mixed"
    if close < ema20 < ema50:
        return "bearish_aligned"
    if close > ema20 > ema50:
        return "bullish_misaligned"
    return "mixed"


def _market_structure(frame: pd.DataFrame, idx: int, direction: str) -> str:
    start = max(0, idx - SWING_LOOKBACK)
    sub = frame.iloc[start : idx + 1]
    if len(sub) < 3:
        return "unknown"
    highs = sub["high"].astype(float)
    lows = sub["low"].astype(float)
    rising = highs.iloc[-1] > highs.iloc[0] and lows.iloc[-1] > lows.iloc[0]
    falling = highs.iloc[-1] < highs.iloc[0] and lows.iloc[-1] < lows.iloc[0]
    if direction == "BUY":
        if rising:
            return "with_structure"
        if falling:
            return "against_structure"
    else:
        if falling:
            return "with_structure"
        if rising:
            return "against_structure"
    return "range_structure"


def _swing_distance(frame: pd.DataFrame, idx: int, entry: float, direction: str) -> float | None:
    start = max(0, idx - SWING_LOOKBACK)
    sub = frame.iloc[start:idx]
    if sub.empty:
        return None
    if direction == "BUY":
        swing = float(sub["low"].min())
        return round(entry - swing, 4)
    swing = float(sub["high"].max())
    return round(swing - entry, 4)


def _first_bars_pnl(
    frame: pd.DataFrame,
    entry_idx: int,
    entry_price: float,
    direction: str,
    lot: float,
    symbol: str,
    bars: tuple[int, ...] = (1, 2, 3, 5, 10),
) -> dict[str, Any]:
    mult = 1 if direction == "BUY" else -1
    cs = contract_size(symbol)
    out: dict[str, Any] = {}
    for n in bars:
        j = min(entry_idx + n, len(frame) - 1)
        close = float(frame.iloc[j]["close"])
        pnl = round((close - entry_price) * mult * cs * lot, 4)
        out[f"bar_{n}_pnl"] = pnl
        out[f"bar_{n}_in_profit"] = pnl > 0
    return out


def classify_false_signal(
    trade: dict[str, Any],
    entry_ctx: dict[str, Any],
    first_bars: dict[str, Any],
) -> str:
    mfe = float(trade.get("mfe") or 0.0)
    mae = float(trade.get("mae") or 0.0)
    duration = int(trade.get("duration_bars") or 0)
    regime = _regime_norm(trade.get("regime", ""))
    atrp_pct = entry_ctx.get("atr_percentile")
    adx = float(entry_ctx.get("adx") or 0.0)
    structure = entry_ctx.get("market_structure", "")

    if mfe >= 0.5 and str(trade.get("exit_reason")).lower() == "sl":
        return "momentum_failure"
    if mfe >= 0.25:
        return "trend_reversal"
    if duration <= 3 and mae >= 0.75:
        return "noise"
    if atrp_pct is not None and atrp_pct <= 25:
        return "low_volatility"
    if atrp_pct is not None and atrp_pct >= 75:
        return "high_volatility"
    if regime == "RANGE":
        if first_bars.get("bar_1_in_profit") is False and first_bars.get("bar_3_in_profit") is False:
            return "range_fakeout"
        return "false_breakout"
    if adx >= 35 and structure == "against_structure":
        return "trend_exhaustion"
    if structure == "against_structure":
        return "poor_entry_timing"
    return "other"


def enrich_losing_trade(
    trade: dict[str, Any],
    record: dict[str, Any],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    entry_idx = int(trade.get("bar_index") or frame.index.searchsorted(pd.to_datetime(trade["timestamp"], utc=True)))
    entry_idx = min(max(entry_idx, 0), len(frame) - 1)
    row = frame.iloc[entry_idx]
    direction = str(trade["direction"])
    entry = float(trade["entry_price"])
    sl = trade.get("sl")
    sl_f = float(sl) if sl is not None else None
    atr = float(row.get("atr") or 0.0)
    sl_dist = abs(entry - sl_f) if sl_f is not None else None

    entry_ctx = {
        "rsi": round(float(row.get("rsi") or 0.0), 4),
        "adx": round(float(row.get("adx") or 0.0), 4),
        "atr": round(atr, 4),
        "atrp": round(float(row.get("atrp") or 0.0), 4),
        "atr_percentile": _atr_percentile(frame["atr"].astype(float), entry_idx),
        "ema_20": round(float(row.get("ema_20") or 0.0), 4),
        "ema_50": round(float(row.get("ema_50") or 0.0), 4),
        "ema_alignment": _ema_alignment(float(row["close"]), float(row.get("ema_20") or 0), float(row.get("ema_50") or 0), direction),
        "market_structure": _market_structure(frame, entry_idx, direction),
        "plus_di": round(float(row.get("plus_di") or 0.0), 4),
        "minus_di": round(float(row.get("minus_di") or 0.0), 4),
    }

    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")
    first_bars = _first_bars_pnl(frame, entry_idx, entry, direction, lot, sym)
    swing_dist = _swing_distance(frame, entry_idx, entry, direction)
    sl_atr_ratio = round(sl_dist / atr, 4) if sl_dist and atr > 0 else None
    sl_vs_swing = round(sl_dist / swing_dist, 4) if sl_dist and swing_dist and swing_dist > 0 else None

    false_class = classify_false_signal(trade, entry_ctx, first_bars)

    return {
        "entry_timestamp": trade.get("timestamp"),
        "exit_timestamp": trade.get("exit_timestamp"),
        "direction": direction,
        "engine": _engine_norm(trade.get("engine", "")),
        "regime": _regime_norm(trade.get("regime", "")),
        "confidence": float(trade.get("confidence") or record.get("confidence") or 0.0),
        "probability": float(trade.get("probability") or trade.get("confidence") or 0.0),
        "atr": entry_ctx["atr"],
        "adx": entry_ctx["adx"],
        "rsi": entry_ctx["rsi"],
        "spread": float(trade.get("spread") or 0.30),
        "lot": lot,
        "sl": sl_f,
        "tp": float(trade["tp"]) if trade.get("tp") is not None else None,
        "duration_bars": int(trade.get("duration_bars") or 0),
        "mae_r": float(trade.get("mae") or 0.0),
        "mfe_r": float(trade.get("mfe") or 0.0),
        "exit_reason": str(trade.get("exit_reason") or "").lower(),
        "pnl": float(trade["pnl"]),
        "pnl_r": float(trade.get("pnl_r") or 0.0),
        "pre_entry": entry_ctx,
        "first_bars": first_bars,
        "sl_distance": round(sl_dist, 4) if sl_dist else None,
        "sl_atr_ratio": sl_atr_ratio,
        "swing_distance": swing_dist,
        "sl_vs_swing_ratio": sl_vs_swing,
        "stop_too_tight": sl_atr_ratio is not None and sl_atr_ratio < 1.0,
        "ever_profitable": float(trade.get("mfe") or 0.0) > 0.05,
        "false_signal_class": false_class,
        "filter_diagnostics": trade.get("filter_diagnostics") or record.get("filter_diagnostics") or {},
    }


def build_loser_log(
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
    candles: pd.DataFrame,
) -> list[dict[str, Any]]:
    frame = candles.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
    if "atr" not in frame.columns:
        frame = indicators.compute_indicators(frame, symbol="XAUUSD", timeframe="M5")

    rec_by_ts = {str(r.get("timestamp")): r for r in records if r.get("timestamp")}
    losers = [t for t in trades if float(t["pnl"]) < 0]
    return [
        enrich_losing_trade(t, rec_by_ts.get(str(t.get("timestamp")), {}), frame)
        for t in losers
    ]
