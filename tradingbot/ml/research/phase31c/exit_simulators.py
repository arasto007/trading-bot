"""Phase 31C realistic exit simulators — causal bar-walk only."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.paper_trading.paper_broker import PaperBroker
from tradingbot.ml.research.phase27l.exit_trace import MAX_HOLD_BARS, _entry_idx, _risk_unit, prepare_indicator_frame
from tradingbot.ml.research.phase27l.exit_simulators import simulate_exit
from tradingbot.ml.research.phase27n.hybrid_simulators import simulate_strategy

SimulatorFn = Callable[[dict[str, Any], pd.DataFrame], dict[str, Any]]


def _bar_loop_base(trade: dict, frame: pd.DataFrame) -> dict[str, Any] | None:
    start = _entry_idx(frame, trade)
    entry = float(trade["entry_price"])
    sl_f = float(trade["sl"]) if trade.get("sl") else None
    if sl_f is None:
        return None
    direction = str(trade["direction"])
    is_buy = direction == "BUY"
    mult = 1 if is_buy else -1
    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")
    risk = _risk_unit(entry, sl_f)
    if risk <= 0:
        return None
    end = min(start + MAX_HOLD_BARS, len(frame) - 1)
    return {
        "start": start,
        "end": end,
        "entry": entry,
        "sl_f": sl_f,
        "direction": direction,
        "is_buy": is_buy,
        "mult": mult,
        "lot": lot,
        "sym": sym,
        "risk": risk,
        "broker": PaperBroker(),
    }


def _finalize(ctx: dict, *, exit_price: float, exit_reason: str, exit_ts: str, duration: int,
              partial_pnl: float = 0.0, remaining_lot: float | None = None, mfe_r: float = 0.0) -> dict[str, Any]:
    lot = ctx["lot"]
    rem = remaining_lot if remaining_lot is not None else lot
    entry = ctx["entry"]
    mult = ctx["mult"]
    sym = ctx["sym"]
    risk = ctx["risk"]
    cs = contract_size(sym)
    main = round((exit_price - entry) * mult * cs * rem, 4)
    total = round(main + partial_pnl, 4)
    pnl_r = round(total / (risk * cs * lot), 4) if risk > 0 else 0.0
    capture = round(pnl_r / mfe_r, 4) if mfe_r > 0 else 0.0
    return {
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 6),
        "exit_timestamp": exit_ts,
        "pnl": total,
        "pnl_r": pnl_r,
        "duration_bars": duration,
        "mfe_r_at_exit": round(mfe_r, 4),
        "capture_efficiency": capture,
        "partial_close_applied": partial_pnl != 0.0,
    }


def sim_baseline_current(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    """Production Hybrid B outcome (from replay records)."""
    return {
        "strategy": "baseline_current",
        "exit_reason": trade.get("exit_reason"),
        "exit_price": float(trade["exit_price"]),
        "exit_timestamp": trade.get("exit_timestamp"),
        "pnl": float(trade["pnl"]),
        "pnl_r": float(trade.get("pnl_r") or 0),
        "duration_bars": int(trade.get("duration_bars") or 0),
        "mfe_r_at_exit": float(trade.get("mfe") or 0),
        "capture_efficiency": float(trade.get("capture_efficiency") or 0) if trade.get("capture_efficiency") else None,
        "partial_close_applied": bool(trade.get("partial_close_applied")),
    }


def sim_breakeven_05r(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_exit(trade, frame, "breakeven_0.5r") | {"strategy": "breakeven_0_5r"}


def sim_breakeven_1r(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_exit(trade, frame, "breakeven_1r") | {"strategy": "breakeven_1r"}


def sim_partial_50_1r(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_exit(trade, frame, "partial_close_50") | {"strategy": "partial_50_at_1r"}


def sim_trailing_atr(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_exit(trade, frame, "trailing_atr") | {"strategy": "trailing_atr_1x"}


def sim_atr_exhaustion(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_exit(trade, frame, "atr_exit") | {"strategy": "atr_exhaustion_exit"}


def sim_structure_ema(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_exit(trade, frame, "structure_exit") | {"strategy": "structure_ema_break"}


def sim_hybrid_b_proxy(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    return simulate_strategy(trade, frame, "hybrid_b") | {"strategy": "hybrid_b_proxy"}


def sim_adaptive_time_fast(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    """Shorter timeout when early momentum weak — causal check at bar 3."""
    ctx = _bar_loop_base(trade, frame)
    if not ctx:
        return sim_baseline_current(trade, frame) | {"strategy": "adaptive_time_fast"}
    max_hold = MAX_HOLD_BARS
    mfe_r = 0.0
    for j in range(ctx["start"] + 1, ctx["end"] + 1):
        bar = frame.iloc[j]
        duration = j - ctx["start"]
        close = float(bar["close"])
        high, low = float(bar["high"]), float(bar["low"])
        if ctx["is_buy"]:
            mfe_r = max(0.0, (high - ctx["entry"]) / ctx["risk"])
        else:
            mfe_r = max(0.0, (ctx["entry"] - low) / ctx["risk"])
        if duration == 3 and mfe_r < 0.25:
            max_hold = ctx["start"] + 6
        if j >= max_hold:
            return _finalize(ctx, exit_price=close, exit_reason="adaptive_time",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "adaptive_time_fast"}
        hit = ctx["broker"].resolve_bar(bar, direction=ctx["mult"], stop_loss=ctx["sl_f"],
                                        take_profit=ctx["entry"] + ctx["mult"] * 1e9)
        if hit and hit[0].upper() == "SL":
            return _finalize(ctx, exit_price=float(hit[1]), exit_reason="sl",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "adaptive_time_fast"}
    bar = frame.iloc[ctx["end"]]
    return _finalize(ctx, exit_price=float(bar["close"]), exit_reason="timeout",
                     exit_ts=pd.to_datetime(frame.index[ctx["end"]], utc=True).isoformat(),
                     duration=ctx["end"] - ctx["start"], mfe_r=mfe_r) | {"strategy": "adaptive_time_fast"}


def sim_momentum_decay(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    """Exit after 3 consecutive closes against position once mfe>=0.25R."""
    ctx = _bar_loop_base(trade, frame)
    if not ctx:
        return sim_baseline_current(trade, frame) | {"strategy": "momentum_decay_exit"}
    against = 0
    mfe_r = 0.0
    for j in range(ctx["start"] + 1, ctx["end"] + 1):
        bar = frame.iloc[j]
        duration = j - ctx["start"]
        close = float(bar["close"])
        high, low = float(bar["high"]), float(bar["low"])
        if ctx["is_buy"]:
            mfe_r = max(mfe_r, (high - ctx["entry"]) / ctx["risk"])
            against = against + 1 if close < float(frame.iloc[j - 1]["close"]) else 0
        else:
            mfe_r = max(mfe_r, (ctx["entry"] - low) / ctx["risk"])
            against = against + 1 if close > float(frame.iloc[j - 1]["close"]) else 0
        if mfe_r >= 0.25 and against >= 3:
            return _finalize(ctx, exit_price=close, exit_reason="momentum_decay",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "momentum_decay_exit"}
        hit = ctx["broker"].resolve_bar(bar, direction=ctx["mult"], stop_loss=ctx["sl_f"],
                                        take_profit=ctx["entry"] + ctx["mult"] * 1e9)
        if hit and hit[0].upper() == "SL":
            return _finalize(ctx, exit_price=float(hit[1]), exit_reason="sl",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "momentum_decay_exit"}
    bar = frame.iloc[ctx["end"]]
    return _finalize(ctx, exit_price=float(bar["close"]), exit_reason="timeout",
                     exit_ts=pd.to_datetime(frame.index[ctx["end"]], utc=True).isoformat(),
                     duration=ctx["end"] - ctx["start"], mfe_r=mfe_r) | {"strategy": "momentum_decay_exit"}


def sim_adx_deterioration(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    ctx = _bar_loop_base(trade, frame)
    if not ctx:
        return sim_baseline_current(trade, frame) | {"strategy": "adx_deterioration_exit"}
    entry_adx = float(frame.iloc[ctx["start"]].get("adx") or 20.0)
    mfe_r = 0.0
    for j in range(ctx["start"] + 1, ctx["end"] + 1):
        bar = frame.iloc[j]
        duration = j - ctx["start"]
        close = float(bar["close"])
        adx = float(bar.get("adx") or entry_adx)
        high, low = float(bar["high"]), float(bar["low"])
        if ctx["is_buy"]:
            mfe_r = max(mfe_r, (high - ctx["entry"]) / ctx["risk"])
        else:
            mfe_r = max(mfe_r, (ctx["entry"] - low) / ctx["risk"])
        if mfe_r >= 0.3 and adx < entry_adx * 0.85 and adx < 20:
            return _finalize(ctx, exit_price=close, exit_reason="adx_weak",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "adx_deterioration_exit"}
        hit = ctx["broker"].resolve_bar(bar, direction=ctx["mult"], stop_loss=ctx["sl_f"],
                                        take_profit=ctx["entry"] + ctx["mult"] * 1e9)
        if hit and hit[0].upper() == "SL":
            return _finalize(ctx, exit_price=float(hit[1]), exit_reason="sl",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "adx_deterioration_exit"}
    bar = frame.iloc[ctx["end"]]
    return _finalize(ctx, exit_price=float(bar["close"]), exit_reason="timeout",
                     exit_ts=pd.to_datetime(frame.index[ctx["end"]], utc=True).isoformat(),
                     duration=ctx["end"] - ctx["start"], mfe_r=mfe_r) | {"strategy": "adx_deterioration_exit"}


def sim_trailing_arm_075r(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    ctx = _bar_loop_base(trade, frame)
    if not ctx:
        return sim_baseline_current(trade, frame) | {"strategy": "trailing_arm_0_75r"}
    trail_sl = ctx["sl_f"]
    armed = False
    peak = ctx["entry"]
    mfe_r = 0.0
    for j in range(ctx["start"] + 1, ctx["end"] + 1):
        bar = frame.iloc[j]
        duration = j - ctx["start"]
        atr = float(bar.get("atr") or ctx["risk"])
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if ctx["is_buy"]:
            mfe_r = max(mfe_r, (high - ctx["entry"]) / ctx["risk"])
            peak = max(peak, high)
        else:
            mfe_r = max(mfe_r, (ctx["entry"] - low) / ctx["risk"])
            peak = min(peak, low)
        if mfe_r >= 0.75:
            armed = True
            if ctx["is_buy"]:
                trail_sl = max(trail_sl, peak - atr)
            else:
                trail_sl = min(trail_sl, peak + atr)
        eff_sl = trail_sl if armed else ctx["sl_f"]
        hit = ctx["broker"].resolve_bar(bar, direction=ctx["mult"], stop_loss=eff_sl,
                                        take_profit=ctx["entry"] + ctx["mult"] * 1e9)
        if hit and hit[0].upper() == "SL":
            return _finalize(ctx, exit_price=float(hit[1]), exit_reason="trail_sl" if armed else "sl",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "trailing_arm_0_75r"}
    bar = frame.iloc[ctx["end"]]
    return _finalize(ctx, exit_price=float(bar["close"]), exit_reason="timeout",
                     exit_ts=pd.to_datetime(frame.index[ctx["end"]], utc=True).isoformat(),
                     duration=ctx["end"] - ctx["start"], mfe_r=mfe_r) | {"strategy": "trailing_arm_0_75r"}


def sim_volatility_short_timeout(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    """High ATR percentile → shorter 8-bar max hold (causal at entry)."""
    ctx = _bar_loop_base(trade, frame)
    if not ctx:
        return sim_baseline_current(trade, frame) | {"strategy": "volatility_short_timeout"}
    atr_series = frame["atr"].astype(float)
    idx = ctx["start"]
    window = atr_series.iloc[max(0, idx - 200): idx + 1]
    pct = 100.0 * (window <= atr_series.iloc[idx]).sum() / max(len(window), 1)
    max_bar = ctx["start"] + (8 if pct >= 60 else MAX_HOLD_BARS)
    mfe_r = 0.0
    for j in range(ctx["start"] + 1, min(ctx["end"], max_bar) + 1):
        bar = frame.iloc[j]
        duration = j - ctx["start"]
        close = float(bar["close"])
        high, low = float(bar["high"]), float(bar["low"])
        if ctx["is_buy"]:
            mfe_r = max(mfe_r, (high - ctx["entry"]) / ctx["risk"])
        else:
            mfe_r = max(mfe_r, (ctx["entry"] - low) / ctx["risk"])
        if j == max_bar:
            return _finalize(ctx, exit_price=close, exit_reason="vol_timeout",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "volatility_short_timeout"}
        hit = ctx["broker"].resolve_bar(bar, direction=ctx["mult"], stop_loss=ctx["sl_f"],
                                        take_profit=ctx["entry"] + ctx["mult"] * 1e9)
        if hit and hit[0].upper() == "SL":
            return _finalize(ctx, exit_price=float(hit[1]), exit_reason="sl",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, mfe_r=mfe_r) | {"strategy": "volatility_short_timeout"}
    bar = frame.iloc[min(ctx["end"], max_bar)]
    return _finalize(ctx, exit_price=float(bar["close"]), exit_reason="vol_timeout",
                     exit_ts=pd.to_datetime(frame.index[min(ctx["end"], max_bar)], utc=True).isoformat(),
                     duration=min(ctx["end"], max_bar) - ctx["start"], mfe_r=mfe_r) | {"strategy": "volatility_short_timeout"}


def sim_multi_stage_partial_trail(trade: dict, frame: pd.DataFrame) -> dict[str, Any]:
    """Partial 50% at 0.75R, trail remainder at 1.0 ATR after 1.0R."""
    ctx = _bar_loop_base(trade, frame)
    if not ctx:
        return sim_baseline_current(trade, frame) | {"strategy": "multi_stage_partial_trail"}
    partial_pnl = 0.0
    rem_lot = ctx["lot"]
    trail_sl = ctx["sl_f"]
    peak = ctx["entry"]
    mfe_r = 0.0
    for j in range(ctx["start"] + 1, ctx["end"] + 1):
        bar = frame.iloc[j]
        duration = j - ctx["start"]
        atr = float(bar.get("atr") or ctx["risk"])
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if ctx["is_buy"]:
            mfe_r = max(mfe_r, (high - ctx["entry"]) / ctx["risk"])
            peak = max(peak, high)
        else:
            mfe_r = max(mfe_r, (ctx["entry"] - low) / ctx["risk"])
            peak = min(peak, low)
        if rem_lot == ctx["lot"] and mfe_r >= 0.75:
            pp = ctx["entry"] + ctx["mult"] * 0.75 * ctx["risk"]
            partial_pnl = round((pp - ctx["entry"]) * ctx["mult"] * contract_size(ctx["sym"]) * ctx["lot"] * 0.5, 4)
            rem_lot = ctx["lot"] * 0.5
        if rem_lot < ctx["lot"] and mfe_r >= 1.0:
            if ctx["is_buy"]:
                trail_sl = max(trail_sl, peak - atr)
            else:
                trail_sl = min(trail_sl, peak + atr)
        eff_sl = trail_sl
        hit = ctx["broker"].resolve_bar(bar, direction=ctx["mult"], stop_loss=eff_sl,
                                        take_profit=ctx["entry"] + ctx["mult"] * 1e9)
        if hit and hit[0].upper() == "SL":
            return _finalize(ctx, exit_price=float(hit[1]), exit_reason="sl",
                             exit_ts=pd.to_datetime(frame.index[j], utc=True).isoformat(),
                             duration=duration, partial_pnl=partial_pnl, remaining_lot=rem_lot,
                             mfe_r=mfe_r) | {"strategy": "multi_stage_partial_trail"}
    bar = frame.iloc[ctx["end"]]
    return _finalize(ctx, exit_price=float(bar["close"]), exit_reason="timeout",
                     exit_ts=pd.to_datetime(frame.index[ctx["end"]], utc=True).isoformat(),
                     duration=ctx["end"] - ctx["start"], partial_pnl=partial_pnl, remaining_lot=rem_lot,
                     mfe_r=mfe_r) | {"strategy": "multi_stage_partial_trail"}


EXIT_CANDIDATES: list[tuple[str, str, SimulatorFn, dict[str, Any]]] = [
    ("01", "baseline_current", sim_baseline_current, {"live": True, "simplicity": 10, "safety": 10}),
    ("02", "breakeven_0_5r", sim_breakeven_05r, {"live": True, "simplicity": 9, "safety": 9}),
    ("03", "breakeven_1r", sim_breakeven_1r, {"live": True, "simplicity": 9, "safety": 8}),
    ("04", "partial_50_at_1r", sim_partial_50_1r, {"live": True, "simplicity": 7, "safety": 8}),
    ("05", "trailing_atr_1x", sim_trailing_atr, {"live": True, "simplicity": 6, "safety": 7}),
    ("06", "atr_exhaustion_exit", sim_atr_exhaustion, {"live": True, "simplicity": 6, "safety": 7}),
    ("07", "structure_ema_break", sim_structure_ema, {"live": True, "simplicity": 7, "safety": 8}),
    ("08", "adaptive_time_fast", sim_adaptive_time_fast, {"live": True, "simplicity": 8, "safety": 8}),
    ("09", "momentum_decay_exit", sim_momentum_decay, {"live": True, "simplicity": 7, "safety": 7}),
    ("10", "adx_deterioration_exit", sim_adx_deterioration, {"live": True, "simplicity": 6, "safety": 7}),
    ("11", "trailing_arm_0_75r", sim_trailing_arm_075r, {"live": True, "simplicity": 7, "safety": 8}),
    ("12", "volatility_short_timeout", sim_volatility_short_timeout, {"live": True, "simplicity": 8, "safety": 8}),
    ("13", "multi_stage_partial_trail", sim_multi_stage_partial_trail, {"live": True, "simplicity": 4, "safety": 6}),
    ("14", "hybrid_b_proxy", sim_hybrid_b_proxy, {"live": True, "simplicity": 5, "safety": 9}),
]


def _synthetic_candles(trades: list[dict[str, Any]] | None = None) -> pd.DataFrame:
    """Deterministic research fallback when MT5/CandleStore unavailable."""
    import numpy as np

    rng = np.random.RandomState(31)
    if trades:
        ts_min = min(pd.to_datetime(t["timestamp"], utc=True) for t in trades)
        ts_max = max(pd.to_datetime(t.get("exit_timestamp") or t["timestamp"], utc=True) for t in trades)
    else:
        ts_min = pd.Timestamp("2026-05-01", tz="UTC")
        ts_max = pd.Timestamp("2026-07-01", tz="UTC")
    idx = pd.date_range(ts_min - pd.Timedelta(days=14), ts_max + pd.Timedelta(days=7), freq="5min", tz="UTC")
    base = 4485.0
    rets = rng.normal(0, 0.00025, len(idx))
    close = base * np.exp(np.cumsum(rets))
    spread = rng.uniform(0.5, 2.0, len(idx))
    high = close + spread
    low = close - spread
    open_ = np.roll(close, 1)
    open_[0] = base
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 100}, index=idx)


def _trade_window_candles(raw: pd.DataFrame, trades: list[dict[str, Any]] | None, *, warmup_bars: int = 300) -> pd.DataFrame:
    """Full M5 resolution over the replay window — no research subsampling."""
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    c = normalize_candles_for_builder(raw)
    if not trades:
        return c.tail(4000)
    ts_min = min(pd.to_datetime(t["timestamp"], utc=True) for t in trades)
    ts_max = max(pd.to_datetime(t.get("exit_timestamp") or t["timestamp"], utc=True) for t in trades)
    start = ts_min - pd.Timedelta(minutes=5 * warmup_bars)
    end = ts_max + pd.Timedelta(hours=6)
    window = c.loc[(c.index >= start) & (c.index <= end)].sort_index()
    return window if not window.empty else c.tail(4000)


def load_candles(cache_path, trades: list[dict[str, Any]] | None = None) -> pd.DataFrame:
    from pathlib import Path

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.mt5_fetch import credentials_configured, fetch_candles
    from tradingbot.ml.data.stores.candle_store import CandleStore

    cache = Path(cache_path)
    project_root = Path(__file__).resolve().parents[4]

    def _materialize(raw: pd.DataFrame) -> pd.DataFrame:
        window = _trade_window_candles(raw, trades)
        cache.parent.mkdir(parents=True, exist_ok=True)
        window.to_parquet(cache)
        return prepare_indicator_frame(window)

    store_df = CandleStore(project_root).load("XAUUSD", "M5")
    if store_df is not None and not store_df.empty:
        return _materialize(store_df)

    if cache.is_file():
        return prepare_indicator_frame(pd.read_parquet(cache))

    cfg = load_legacy_config()
    if credentials_configured(cfg):
        raw = fetch_candles(cfg, "XAUUSD", "M5", bars=8000)
        if raw is not None and not raw.empty:
            return _materialize(raw)

    return prepare_indicator_frame(_synthetic_candles(trades))
