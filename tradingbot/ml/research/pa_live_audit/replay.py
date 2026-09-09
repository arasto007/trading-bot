"""Causal replay of the LIVE M5 gold_ny_sweep rules on research XAUUSD candles.

Not a broker backtest. Uncosted. One-position first-touch SL/TP.
Does not optimize parameters. OOS cut is pre-declared (2025-01-01 UTC).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.gold_strategies import evaluate_gold_setup
from tradingbot.domain.price_action import _atr, enrich_price_action
from tradingbot.ml.data.paths import candle_path

# Pre-declared holdout — not chosen after seeing results.
OOS_START = pd.Timestamp("2025-01-01T00:00:00+00:00")
MIN_TRADES = 30
WINDOW_BARS = 400
WARMUP = 80


def load_research_m5() -> pd.DataFrame:
    path = candle_path("XAUUSD", "M5")
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], utc=True))
        elif "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"], utc=True))
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index()


def _session_label(ts: pd.Timestamp) -> str:
    h = int(ts.hour)
    if 0 <= h < 7:
        return "ASIAN"
    if 7 <= h < 12:
        return "LONDON"
    if 12 <= h < 17:
        return "NY"
    if 17 <= h < 21:
        return "NY_LATE"
    return "OFF"


def _first_touch_r(
    highs: np.ndarray,
    lows: np.ndarray,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
) -> tuple[float | None, int]:
    """Walk subsequent bars. Same-bar both sides → SL (conservative). Returns (R, hold_bars)."""
    risk = abs(entry - sl)
    if risk <= 0:
        return None, 0
    for k in range(len(highs)):
        hi = float(highs[k])
        lo = float(lows[k])
        if direction > 0:
            hit_sl = lo <= sl
            hit_tp = hi >= tp
        else:
            hit_sl = hi >= sl
            hit_tp = lo <= tp
        if hit_sl and hit_tp:
            return -1.0, k + 1
        if hit_sl:
            return -1.0, k + 1
        if hit_tp:
            return abs(tp - entry) / risk, k + 1
    return None, len(highs)


def summarize_r(rs: list[float]) -> dict[str, Any]:
    arr = np.asarray(rs, dtype=float)
    n = int(arr.size)
    if n == 0:
        return {"trades": 0, "status": "EMPTY"}
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    gp = float(wins.sum()) if wins.size else 0.0
    gl = float(-losses.sum()) if losses.size else 0.0
    eq = np.cumsum(arr)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    streak = longest = 0
    for x in arr:
        if x < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    return {
        "trades": n,
        "win_rate": round(float((arr > 0).mean()), 4),
        "average_r": round(float(arr.mean()), 6),
        "expectancy": round(float(arr.mean()), 6),
        "profit_factor": round(gp / gl, 4) if gl > 0 else None,
        "max_dd_r": round(float(dd.min()), 4) if n else 0.0,
        "sharpe": round(float(arr.mean() / std), 4) if std > 1e-12 else None,
        "longest_losing_streak": longest,
        "total_r": round(float(arr.sum()), 4),
        "meaningful": n >= MIN_TRADES,
    }


def _slice_table(trades: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = {}
    for t in trades:
        r = t.get("r_multiple")
        if r is None:
            continue
        groups.setdefault(str(key_fn(t)), []).append(float(r))
    out = []
    for name, rs in sorted(groups.items()):
        row = summarize_r(rs)
        row["bucket"] = name
        out.append(row)
    return out


def replay_live_pa_rules(
    df: pd.DataFrame | None = None,
    *,
    max_bars: int | None = None,
) -> dict[str, Any]:
    """Walk research XAUUSD M5 with frozen live M5 preset. No parameter search."""
    cfg = get_price_action_config("XAUUSD", "M5")
    cooldown = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg.get("NY_ENTRY_START_UTC", 15))
    ny_e = int(cfg.get("NY_ENTRY_END_UTC", 16))

    if df is None:
        df = load_research_m5()
    if max_bars is not None:
        df = df.iloc[: max_bars].copy()

    work = df.copy()
    if "atr" not in work.columns:
        work["atr"] = _atr(work, int(cfg.get("ATR_PERIOD", 14)))
    n = len(work)
    highs = work["high"].to_numpy(dtype=float)
    lows = work["low"].to_numpy(dtype=float)
    closes = work["close"].to_numpy(dtype=float)
    atrs = work["atr"].to_numpy(dtype=float)
    index = work.index
    hours = index.hour.to_numpy()
    dates = index.date

    asian_end = int(cfg.get("ASIAN_SESSION_END_UTC", cfg.get("ASIAN_END_HOUR", 8)))
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12)) + 1
    buf_m = float(cfg.get("SWEEP_BUFFER_ATR", 0.12))
    min_range_m = float(cfg.get("MIN_RANGE_ATR", 0.2))
    asian = work.iloc[(hours >= 0) & (hours < asian_end)]
    if asian.empty:
        agg = {}
    else:
        g = asian.groupby(asian.index.date)
        agg = {
            "hi": g["high"].max().to_dict(),
            "lo": g["low"].min().to_dict(),
            "n": g["high"].count().to_dict(),
        }
    roll_hi = work["high"].rolling(lookback, min_periods=4).max().to_numpy()
    roll_lo = work["low"].rolling(lookback, min_periods=4).min().to_numpy()

    ny_idx = [
        i
        for i in range(WARMUP, n - 1)
        if ny_s <= int(hours[i]) < ny_e
    ]

    trades: list[dict[str, Any]] = []
    last_entry_i = -10**9
    day_count: dict[Any, int] = {}
    in_trade_until = -1

    for i in ny_idx:
        if i <= in_trade_until:
            continue
        if i - last_entry_i < cooldown:
            continue
        ts = index[i]
        day = dates[i]
        if day_count.get(day, 0) >= max_day:
            continue
        atr = float(atrs[i])
        if not np.isfinite(atr) or atr <= 0:
            continue
        a_hi = agg.get("hi", {}).get(day)
        a_lo = agg.get("lo", {}).get(day)
        a_n = int(agg.get("n", {}).get(day) or 0)
        if a_hi is None or a_lo is None or a_n < 4:
            continue
        if (float(a_hi) - float(a_lo)) < atr * min_range_m:
            continue
        price = float(closes[i])
        buf = atr * buf_m
        inside = float(a_lo) < price < float(a_hi)
        swept = (float(roll_hi[i]) > float(a_hi) + buf) or (float(roll_lo[i]) < float(a_lo) - buf)
        if not (inside and swept):
            continue

        start = max(0, i + 1 - WINDOW_BARS)
        window = work.iloc[start : i + 1]
        local_i = len(window) - 1
        enriched = enrich_price_action(window, cfg, at_index=local_i)
        setup = evaluate_gold_setup(enriched, local_i, cfg, timeframe="M5")
        if setup is None:
            continue
        if float(setup.confidence) < float(cfg.get("MIN_CONFIDENCE", 0.52)):
            continue

        r, hold = _first_touch_r(
            highs[i + 1 :],
            lows[i + 1 :],
            int(setup.direction),
            float(setup.entry),
            float(setup.stop_loss),
            float(setup.take_profit),
        )
        if r is None:
            continue
        last_entry_i = i
        in_trade_until = i + hold
        day_count[day] = day_count.get(day, 0) + 1
        hold_bucket = "1-3" if hold <= 3 else ("4-12" if hold <= 12 else ("13-36" if hold <= 36 else "37+"))
        trades.append(
            {
                "timestamp": str(ts),
                "direction": "BUY" if setup.direction > 0 else "SELL",
                "r_multiple": float(r),
                "hold_bars": hold,
                "hold_bucket": hold_bucket,
                "session": _session_label(ts),
                "oos": bool(pd.Timestamp(ts) >= OOS_START),
                "confidence": float(setup.confidence),
                "quality": (setup.metadata or {}).get("quality_score"),
            }
        )

    closed = [t for t in trades if t.get("r_multiple") is not None]
    oos = [t for t in closed if t["oos"]]
    ins = [t for t in closed if not t["oos"]]
    return {
        "kind": "RESEARCH_REPLAY_OF_LIVE_RULES",
        "not_broker_backtest": True,
        "uncosted": True,
        "symbol_used": "XAUUSD",
        "live_symbol": "XAUUSD_i",
        "preset": cfg.get("PRESET"),
        "oos_start_declared": str(OOS_START),
        "n_candles": n,
        "n_closed": len(closed),
        "assumptions": [
            "fill = signal-bar close (no spread/slip/commission)",
            "same-bar SL+TP → SL",
            "one position at a time (live allows 2/symbol)",
            "no RiskGate news/spread/meta/equity",
            "no EOD/trailing/partial",
            "research XAUUSD candles, not XAUUSD_i",
            "NY-hour + same-day Asian groupby is a causal prefilter; accept/reject is evaluate_gold_setup",
        ],
        "full": summarize_r([t["r_multiple"] for t in closed]),
        "in_sample": summarize_r([t["r_multiple"] for t in ins]),
        "out_of_sample": summarize_r([t["r_multiple"] for t in oos]),
        "year": _slice_table(closed, lambda t: str(t["timestamp"])[:4]),
        "month": _slice_table(closed, lambda t: str(t["timestamp"])[:7]),
        "direction": _slice_table(closed, lambda t: t["direction"]),
        "session": _slice_table(closed, lambda t: t["session"]),
        "holding_time": _slice_table(closed, lambda t: t["hold_bucket"]),
        "oos_quality": (
            "calendar holdout from 2025-01-01 declared before metrics; "
            "NOT a walk-forward of frozen research protocol; costs absent"
        ),
    }
