#!/usr/bin/env python3
"""PHASE 22A — PA strategy discovery lab (research-only, no live patches, no Meta)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.domain.pa_hardening import session_label
from tradingbot.domain.session_logic import variable_slippage_pips, variable_spread_pips

OUT = ROOT / "logs" / "phase22a"
CACHE = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
FWD = 96
COOLDOWN, MAX_DAY = 18, 3
MIN_RR = 1.5
SL_ATR = 0.35
MIN_RANGE = 0.2
SWEEP_LB = 12
SWEEP_BUF = 0.12
ATR_MIN, ATR_MAX = 12.0, 94.0
MAX_SPREAD = 15.0
BASE_SPREAD = 4.0
BASE_SLIP = 3.0
GOLD_PIP = 0.1
MSS_WINDOW = 16
FVG_WINDOW = 8
RETURN_WINDOW = 24
DISP_MIN = 0.50
FVG_MIN_ATR = 0.12
SWING_L, SWING_R = 3, 3
B_SESSION = (7, 17)
C_SESSION = (7, 17)


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_df() -> pd.DataFrame:
    df = pd.read_parquet(CACHE)
    if "time" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    if "atr" not in df.columns:
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df.sort_index()


def infer_regimes(df: pd.DataFrame) -> np.ndarray:
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    sma20 = df["sma_20"].to_numpy(dtype=float) if "sma_20" in df.columns else df["close"].rolling(20).mean().to_numpy()
    sma50 = df["sma_50"].to_numpy(dtype=float) if "sma_50" in df.columns else df["close"].rolling(50).mean().to_numpy()
    atr_mean = pd.Series(atr).rolling(20, min_periods=5).mean().to_numpy()
    ratio = np.divide(atr, atr_mean, out=np.ones(n), where=atr_mean > 0)
    regime = np.full(n, "RANGING", dtype=object)
    regime[ratio >= 2.0] = "CRISIS"
    regime[(ratio >= 1.5) & (ratio < 2.0)] = "VOLATILE"
    regime[(ratio < 1.5) & (close > sma20) & (sma20 > sma50)] = "STRONG_TREND_UP"
    regime[(ratio < 1.5) & (close < sma20) & (sma20 < sma50)] = "STRONG_TREND_DOWN"
    return regime


def simulate_trade(high, low, close, i, direction, entry, sl, tp, n, max_bars=FWD) -> dict[str, Any]:
    risk = abs(float(entry) - float(sl))
    empty = {"final_R": 0.0, "MFE_R": 0.0, "MAE_R": 0.0, "exit_reason": "invalid"}
    if risk <= 0:
        return empty
    mfe = 0.0
    mae = 0.0
    end = min(int(n), int(i) + 1 + int(max_bars))
    buy = int(direction) > 0
    for j in range(int(i) + 1, end):
        hi = float(high[j])
        lo = float(low[j])
        prev_mfe, prev_mae = mfe, mae
        if buy:
            mfe = max(mfe, (hi - entry) / risk)
            mae = min(mae, (lo - entry) / risk)
            hit_sl = lo <= sl
            hit_tp = hi >= tp
        else:
            mfe = max(mfe, (entry - lo) / risk)
            mae = min(mae, (entry - hi) / risk)
            hit_sl = hi >= sl
            hit_tp = lo <= tp
        if hit_sl:
            return {
                "final_R": round((sl - entry) / risk if buy else (entry - sl) / risk, 4),
                "MFE_R": round(prev_mfe, 4),
                "MAE_R": round(min(prev_mae, -1.0), 4),
                "exit_reason": "sl",
            }
        if hit_tp:
            return {
                "final_R": round((tp - entry) / risk if buy else (entry - tp) / risk, 4),
                "MFE_R": round(max(mfe, 1.0), 4),
                "MAE_R": round(mae, 4),
                "exit_reason": "tp",
            }
    c = float(close[end - 1])
    r = ((c - entry) if buy else (entry - c)) / risk
    return {"final_R": round(r, 4), "MFE_R": round(mfe, 4), "MAE_R": round(mae, 4), "exit_reason": "timeout"}


def apply_cd(cands: list[dict[str, Any]], cd: int = COOLDOWN, max_day: int = MAX_DAY) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    last = -10000
    open_until = -1
    day_counts: Counter[str] = Counter()
    for c in cands:
        i = int(c["i"])
        if i <= open_until or i - last < cd:
            continue
        day = str(c.get("day") or "")
        if day_counts[day] >= max_day:
            continue
        out.append(c)
        last = i
        open_until = i + 12
        day_counts[day] += 1
    return out


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_dd_R": 0.0, "longest_losing_streak": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    streak = longest = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
        if r < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return {
        "trades": len(rs),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(min(pf, 99.0), 3),
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_dd_R": round(mdd, 3),
        "longest_losing_streak": int(longest),
    }
def group_profit(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for r in rows:
        acc[str(r.get(key, "NA"))] += float(r.get("final_R") or 0.0)
    return {k: round(v, 3) for k, v in sorted(acc.items(), key=lambda x: str(x[0]))}


def clustering_rate(rows: list[dict[str, Any]], gap: int = 6) -> float:
    if len(rows) < 2:
        return 0.0
    clustered = 0
    prev = int(rows[0]["i"])
    for r in rows[1:]:
        i = int(r["i"])
        if i - prev < gap:
            clustered += 1
        prev = i
    return round(clustered / (len(rows) - 1), 4)


def precompute_asian(dates, hours, high, low, n, end_hour: int):
    buckets: dict[str, list[int]] = {}
    for i in range(n):
        if 0 <= int(hours[i]) < end_hour:
            buckets.setdefault(dates[i], []).append(i)
    out = {}
    for day, idxs in buckets.items():
        if len(idxs) < 4:
            out[day] = None
            continue
        hi = float(np.max(high[idxs]))
        lo = float(np.min(low[idxs]))
        out[day] = (hi, lo) if hi > lo else None
    return out


def last_completed_day_hl(dates, high, low, n):
    day_hi: dict[str, float] = {}
    day_lo: dict[str, float] = {}
    for i in range(n):
        d = dates[i]
        h, l = float(high[i]), float(low[i])
        day_hi[d] = h if d not in day_hi else max(day_hi[d], h)
        day_lo[d] = l if d not in day_lo else min(day_lo[d], l)
    uniq = []
    seen = set()
    for d in dates:
        if d not in seen:
            uniq.append(d)
            seen.add(d)
    prev = {uniq[0]: None}
    for a, b in zip(uniq, uniq[1:]):
        prev[b] = a
    pdh = np.zeros(n)
    pdl = np.zeros(n)
    for i in range(n):
        p = prev.get(dates[i])
        if p is None:
            pdh[i] = float(high[i])
            pdl[i] = float(low[i])
        else:
            pdh[i] = day_hi[p]
            pdl[i] = day_lo[p]
    return pdh, pdl


def last_completed_week_hl(index: pd.DatetimeIndex, high, low, n):
    weeks = np.array([f"{ts.isocalendar().year}-W{int(ts.isocalendar().week):02d}" for ts in index])
    wh: dict[str, float] = {}
    wl: dict[str, float] = {}
    for i in range(n):
        w = weeks[i]
        h, l = float(high[i]), float(low[i])
        wh[w] = h if w not in wh else max(wh[w], h)
        wl[w] = l if w not in wl else min(wl[w], l)
    uniq = []
    seen = set()
    for w in weeks:
        if w not in seen:
            uniq.append(w)
            seen.add(w)
    prev = {uniq[0]: None}
    for a, b in zip(uniq, uniq[1:]):
        prev[b] = a
    pwh = np.zeros(n)
    pwl = np.zeros(n)
    for i in range(n):
        p = prev.get(weeks[i])
        if p is None:
            pwh[i] = float(high[i])
            pwl[i] = float(low[i])
        else:
            pwh[i] = wh[p]
            pwl[i] = wl[p]
    return pwh, pwl


def causal_range(dates, hours, high, low, n, start_h: int, end_h: int):
    """High/low of [start_h, end_h) using only bars strictly before i."""
    hi_arr = np.full(n, np.nan)
    lo_arr = np.full(n, np.nan)
    cur = None
    run_hi = -1e18
    run_lo = 1e18
    count = 0
    frozen_hi = np.nan
    frozen_lo = np.nan
    frozen_n = 0
    for i in range(n):
        if dates[i] != cur:
            cur = dates[i]
            run_hi, run_lo, count = -1e18, 1e18, 0
            frozen_hi, frozen_lo, frozen_n = np.nan, np.nan, 0
        h = int(hours[i])
        if start_h <= h < end_h:
            if count >= 4:
                hi_arr[i] = run_hi
                lo_arr[i] = run_lo
            run_hi = max(run_hi, float(high[i]))
            run_lo = min(run_lo, float(low[i]))
            count += 1
        else:
            if count >= 4 and frozen_n == 0:
                frozen_hi, frozen_lo, frozen_n = run_hi, run_lo, count
            if frozen_n >= 4:
                hi_arr[i] = frozen_hi
                lo_arr[i] = frozen_lo
    return hi_arr, lo_arr


def session_hl_arrays(dates, hours, n, asian_hi, asian_lo, lon_hi, lon_lo):
    """Completed session range only: Asian after 08:00, London after 12:00."""
    shi = np.full(n, np.nan)
    slo = np.full(n, np.nan)
    prev_hi = np.nan
    prev_lo = np.nan
    for i in range(n):
        h = int(hours[i])
        if h >= 12 and not np.isnan(lon_hi[i]):
            shi[i], slo[i] = float(lon_hi[i]), float(lon_lo[i])
            prev_hi, prev_lo = shi[i], slo[i]
        elif h >= 8 and not np.isnan(asian_hi[i]):
            shi[i], slo[i] = float(asian_hi[i]), float(asian_lo[i])
            prev_hi, prev_lo = shi[i], slo[i]
        elif not np.isnan(prev_hi):
            shi[i], slo[i] = prev_hi, prev_lo
    return shi, slo


def swing_arrays(high, low, n):
    last_hi_p = np.full(n, np.nan)
    last_lo_p = np.full(n, np.nan)
    last_hi_i = np.full(n, -1, dtype=int)
    last_lo_i = np.full(n, -1, dtype=int)
    cur_hi_p = np.nan
    cur_lo_p = np.nan
    cur_hi_i = -1
    cur_lo_i = -1
    for i in range(n):
        last_hi_p[i] = cur_hi_p
        last_lo_p[i] = cur_lo_p
        last_hi_i[i] = cur_hi_i
        last_lo_i[i] = cur_lo_i
        if i < SWING_L + SWING_R:
            continue
        c = i - SWING_R
        if c < SWING_L:
            continue
        if high[c] >= np.max(high[c - SWING_L : c + SWING_R + 1]):
            cur_hi_p = float(high[c])
            cur_hi_i = int(c)
        if low[c] <= np.min(low[c - SWING_L : c + SWING_R + 1]):
            cur_lo_p = float(low[c])
            cur_lo_i = int(c)
    return last_hi_p, last_lo_p, last_hi_i, last_lo_i


def body_fvg_at(open_, close, i: int, direction: int):
    if i < 2:
        return None
    b0_hi = max(float(open_[i]), float(close[i]))
    b0_lo = min(float(open_[i]), float(close[i]))
    b2_hi = max(float(open_[i - 2]), float(close[i - 2]))
    b2_lo = min(float(open_[i - 2]), float(close[i - 2]))
    if direction > 0 and b0_lo > b2_hi:
        return b2_hi, b0_lo
    if direction < 0 and b0_hi < b2_lo:
        return b0_hi, b2_lo
    return None


def htf_bias_array(index: pd.DatetimeIndex, close, n):
    hours = np.array([ts.floor("h") for ts in index])
    h1_close_map = {}
    order = []
    for i in range(n):
        h = hours[i]
        if h not in h1_close_map:
            order.append(h)
        h1_close_map[h] = float(close[i])
    series = [h1_close_map[h] for h in order]
    sma = []
    acc = 0.0
    for k, v in enumerate(series):
        acc += v
        if k >= 20:
            acc -= series[k - 20]
            sma.append(acc / 20.0)
        else:
            sma.append(v)
    hour_to_idx = {h: k for k, h in enumerate(order)}
    bias = np.zeros(n)
    for i in range(n):
        k = hour_to_idx[hours[i]]
        if k <= 0:
            continue
        prev = k - 1
        c = series[prev]
        s = sma[prev]
        if c > s * 1.0002:
            bias[i] = 1.0
        elif c < s * 0.9998:
            bias[i] = -1.0
    return bias


def premium_discount(high, low, close, i: int, look: int = 48) -> str:
    a = max(0, i - look)
    hi = float(np.max(high[a : i + 1]))
    lo = float(np.min(low[a : i + 1]))
    if hi <= lo:
        return "equilibrium"
    pos = (float(close[i]) - lo) / (hi - lo)
    if pos < 0.45:
        return "discount"
    if pos > 0.55:
        return "premium"
    return "equilibrium"


def cost_r(spread_pips: float, slip_pips: float, risk: float) -> float:
    if risk <= 0:
        return 0.0
    return (float(spread_pips) + float(slip_pips)) * GOLD_PIP / risk

def annotate_fill(row, high, low, close, open_, n, hours):
    i = int(row["i"])
    fill_i = min(i + 1, n - 1)
    entry = float(open_[fill_i])
    sl = float(row["sl"])
    tp = float(row["tp"])
    direction = int(row["dir"])
    risk = abs(entry - sl)
    if risk <= 0:
        return row
    sp = variable_spread_pips(BASE_SPREAD, int(hours[i]))
    slip = variable_slippage_pips(BASE_SLIP, int(hours[i]))
    path = simulate_trade(high, low, close, i, direction, entry, sl, tp, n)
    row.update(path)
    row["entry"] = round(entry, 5)
    row["planned_rr"] = round(abs(tp - entry) / risk, 2)
    row["spread_pips"] = sp
    row["cost_spread_R"] = round(cost_r(sp, 0.0, risk), 4)
    row["cost_stress_R"] = round(cost_r(sp, slip, risk), 4)
    row["final_R_spread"] = round(float(row["final_R"]) - float(row["cost_spread_R"]), 4)
    row["final_R_stress"] = round(float(row["final_R"]) - float(row["cost_stress_R"]), 4)
    return row


def collect_a(ctx, ny_s: int, ny_e: int, asian_end: int):
    n = ctx["n"]
    hours, dates = ctx["hours"], ctx["dates"]
    high, low, close, open_ = ctx["high"], ctx["low"], ctx["close"], ctx["open"]
    atr, atr_pct, regime = ctx["atr"], ctx["atr_pct"], ctx["regime"]
    index = ctx["index"]
    asian = precompute_asian(dates, hours, high, low, n, asian_end)
    roll_hi = pd.Series(high).rolling(SWEEP_LB + 1, min_periods=1).max().to_numpy()
    roll_lo = pd.Series(low).rolling(SWEEP_LB + 1, min_periods=1).min().to_numpy()
    htf = ctx["htf_bias"]
    out = []
    for i in range(80, n - 3):
        if not (ny_s <= int(hours[i]) < ny_e):
            continue
        bounds = asian.get(dates[i])
        if bounds is None:
            continue
        asian_hi, asian_lo = bounds
        a = float(atr[i])
        if a <= 0 or (asian_hi - asian_lo) < a * MIN_RANGE:
            continue
        buf = a * SWEEP_BUF
        wh, wl = float(roll_hi[i]), float(roll_lo[i])
        price = float(close[i])
        direction = None
        level_type = ""
        depth = 0.0
        extreme = 0.0
        if wh > asian_hi + buf and asian_lo < price < asian_hi:
            direction = -1
            level_type = "asian_high"
            depth = (wh - asian_hi) / a
            extreme = wh
        elif wl < asian_lo - buf and asian_lo < price < asian_hi:
            direction = 1
            level_type = "asian_low"
            depth = (asian_lo - wl) / a
            extreme = wl
        if direction is None:
            continue
        sl_pad = a * SL_ATR
        if direction < 0:
            sl = extreme + sl_pad
            risk = sl - price
            tp = price - max(price - asian_lo, risk * MIN_RR)
        else:
            sl = extreme - sl_pad
            risk = price - sl
            tp = price + max(asian_hi - price, risk * MIN_RR)
        if risk <= 0:
            continue
        rr = abs(tp - price) / risk
        if rr < MIN_RR * 0.95:
            continue
        sp = variable_spread_pips(BASE_SPREAD, int(hours[i]))
        if sp > MAX_SPREAD or not (ATR_MIN <= float(atr_pct[i]) <= ATR_MAX):
            continue
        ts = index[i]
        row = {
            "i": i,
            "timestamp": ts.isoformat(),
            "day": dates[i],
            "hour": int(hours[i]),
            "direction": "BUY" if direction > 0 else "SELL",
            "dir": int(direction),
            "regime": str(regime[i]),
            "session": session_label(ts.to_pydatetime()),
            "sweep_level_type": level_type,
            "sweep_depth_atr": round(float(depth), 3),
            "mss_choch_type": "",
            "displacement_strength": 0.0,
            "fvg_size_atr": 0.0,
            "distance_to_fvg": 0.0,
            "premium_discount": premium_discount(high, low, close, i),
            "htf_bias": int(htf[i]),
            "sl": float(sl),
            "tp": float(tp),
        }
        out.append(annotate_fill(row, high, low, close, open_, n, hours))
    return out


def _find_mss(close, last_hi_p, last_lo_p, last_hi_i, last_lo_i, sweep_i, direction, n):
    end = min(n - 2, sweep_i + 1 + MSS_WINDOW)
    for j in range(sweep_i + 1, end):
        if direction > 0:
            lvl = last_hi_p[j]
            li = last_hi_i[j]
            if np.isnan(lvl) or li < 0 or li >= j:
                continue
            if float(close[j]) > float(lvl):
                return j
        else:
            lvl = last_lo_p[j]
            li = last_lo_i[j]
            if np.isnan(lvl) or li < 0 or li >= j:
                continue
            if float(close[j]) < float(lvl):
                return j
    return None


def _disp_strength(open_, close, atr, j: int, direction: int) -> float:
    a = max(float(atr[j]), 1e-9)
    body = float(close[j]) - float(open_[j])
    signed = body if direction > 0 else -body
    return float(signed / a)


def _find_fvg(open_, close, atr, mss_i, direction, n):
    end = min(n - 2, mss_i + 1 + FVG_WINDOW)
    for k in range(mss_i, end):
        gap = body_fvg_at(open_, close, k, direction)
        if gap is None:
            continue
        bot, top = gap
        size = abs(top - bot) / max(float(atr[k]), 1e-9)
        if size < FVG_MIN_ATR:
            continue
        return k, float(bot), float(top)
    return None


def _find_return_confirm(high, low, close, fvg_i, bot, top, direction, n):
    end = min(n - 2, fvg_i + 1 + RETURN_WINDOW)
    mid = 0.5 * (bot + top)
    touched = False
    for k in range(fvg_i + 1, end):
        lo, hi = float(low[k]), float(high[k])
        if lo <= top and hi >= bot:
            touched = True
        if not touched:
            continue
        c = float(close[k])
        if direction > 0 and c > mid:
            return k
        if direction < 0 and c < mid:
            return k
    return None

def collect_structural(ctx, *, session, use_htf_levels: bool, require_pd: bool):
    n = ctx["n"]
    hours, dates = ctx["hours"], ctx["dates"]
    high, low, close, open_ = ctx["high"], ctx["low"], ctx["close"], ctx["open"]
    atr, atr_pct, regime = ctx["atr"], ctx["atr_pct"], ctx["regime"]
    index = ctx["index"]
    last_hi_p, last_lo_p, last_hi_i, last_lo_i = ctx["swings"]
    htf = ctx["htf_bias"]
    asian_hi, asian_lo = ctx["asian_hi"], ctx["asian_lo"]
    pdh, pdl = ctx["pdh"], ctx["pdl"]
    pwh, pwl = ctx["pwh"], ctx["pwl"]
    shi, slo = ctx["sess_hi"], ctx["sess_lo"]
    funnel = Counter()
    sweeps = []
    s0, s1 = session
    for i in range(80, n - FWD - 3):
        if not (s0 <= int(hours[i]) < s1):
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        buf = a * SWEEP_BUF
        c = float(close[i])
        hi, lo = float(high[i]), float(low[i])
        hit = None
        if use_htf_levels:
            if hi > float(pdh[i]) + buf and c < float(pdh[i]):
                hit = ("pdh", -1, float(pdh[i]), hi, (hi - float(pdh[i])) / a)
            elif lo < float(pdl[i]) - buf and c > float(pdl[i]):
                hit = ("pdl", 1, float(pdl[i]), lo, (float(pdl[i]) - lo) / a)
            elif hi > float(pwh[i]) + buf and c < float(pwh[i]):
                hit = ("pwh", -1, float(pwh[i]), hi, (hi - float(pwh[i])) / a)
            elif lo < float(pwl[i]) - buf and c > float(pwl[i]):
                hit = ("pwl", 1, float(pwl[i]), lo, (float(pwl[i]) - lo) / a)
            elif hi > float(shi[i]) + buf and c < float(shi[i]):
                hit = ("session_high", -1, float(shi[i]), hi, (hi - float(shi[i])) / a)
            elif lo < float(slo[i]) - buf and c > float(slo[i]):
                hit = ("session_low", 1, float(slo[i]), lo, (float(slo[i]) - lo) / a)
        else:
            used = False
            a_hi, a_lo = asian_hi[i], asian_lo[i]
            if not np.isnan(a_hi) and not np.isnan(a_lo) and (a_hi - a_lo) >= a * MIN_RANGE:
                if hi > a_hi + buf and c < a_hi:
                    hit = ("asian_high", -1, float(a_hi), hi, (hi - float(a_hi)) / a)
                    used = True
                elif lo < a_lo - buf and c > a_lo:
                    hit = ("asian_low", 1, float(a_lo), lo, (float(a_lo) - lo) / a)
                    used = True
            if not used:
                sh, slv = last_hi_p[i], last_lo_p[i]
                if not np.isnan(sh) and hi > float(sh) + buf and c < float(sh):
                    hit = ("swing_high", -1, float(sh), hi, (hi - float(sh)) / a)
                elif not np.isnan(slv) and lo < float(slv) - buf and c > float(slv):
                    hit = ("swing_low", 1, float(slv), lo, (float(slv) - lo) / a)
        if hit is None:
            continue
        funnel["sweep"] += 1
        sweeps.append({"sweep_i": i, "level_type": hit[0], "dir": hit[1], "level": hit[2], "extreme": hit[3], "depth": hit[4]})

    out = []
    used_entry = set()
    for sw in sweeps:
        sweep_i = int(sw["sweep_i"])
        direction = int(sw["dir"])
        mss_i = _find_mss(close, last_hi_p, last_lo_p, last_hi_i, last_lo_i, sweep_i, direction, n)
        if mss_i is None:
            continue
        funnel["mss"] += 1
        disp = _disp_strength(open_, close, atr, mss_i, direction)
        fvg = _find_fvg(open_, close, atr, mss_i, direction, n)
        if use_htf_levels:
            if fvg is None and disp < DISP_MIN:
                continue
            funnel["confirm"] += 1
            if fvg is None:
                fvg_i, bot, top = mss_i, float(close[mss_i]), float(close[mss_i])
                fvg_size = 0.0
            else:
                fvg_i, bot, top = fvg
                fvg_size = abs(top - bot) / max(float(atr[fvg_i]), 1e-9)
            entry_i = _find_return_confirm(high, low, close, fvg_i, bot, top, direction, n)
            if entry_i is None:
                if disp >= DISP_MIN and mss_i > sweep_i:
                    entry_i = mss_i
                else:
                    continue
            funnel["return"] += 1
        else:
            if disp < DISP_MIN:
                continue
            funnel["disp"] += 1
            if fvg is None:
                continue
            funnel["fvg"] += 1
            fvg_i, bot, top = fvg
            fvg_size = abs(top - bot) / max(float(atr[fvg_i]), 1e-9)
            entry_i = _find_return_confirm(high, low, close, fvg_i, bot, top, direction, n)
            if entry_i is None or entry_i <= sweep_i:
                continue
            funnel["return"] += 1
        if entry_i in used_entry or entry_i <= sweep_i:
            continue
        if not (s0 <= int(hours[entry_i]) < s1):
            continue
        a = float(atr[entry_i])
        if a <= 0:
            continue
        sp = variable_spread_pips(BASE_SPREAD, int(hours[entry_i]))
        if sp > MAX_SPREAD or not (ATR_MIN <= float(atr_pct[entry_i]) <= ATR_MAX):
            continue
        pd_zone = premium_discount(high, low, close, entry_i)
        if require_pd:
            if direction > 0 and pd_zone != "discount":
                continue
            if direction < 0 and pd_zone != "premium":
                continue
            funnel["pd"] += 1
        price = float(close[entry_i])
        sl_pad = a * SL_ATR
        extreme = float(sw["extreme"])
        if direction > 0:
            sl = min(extreme, float(low[sweep_i])) - sl_pad
            risk = price - sl
            tp = price + risk * MIN_RR
        else:
            sl = max(extreme, float(high[sweep_i])) + sl_pad
            risk = sl - price
            tp = price - risk * MIN_RR
        if risk <= 0:
            continue
        mid = 0.5 * (bot + top)
        dist = abs(price - mid) / a
        ts = index[entry_i]
        row = {
            "i": entry_i,
            "timestamp": ts.isoformat(),
            "day": dates[entry_i],
            "hour": int(hours[entry_i]),
            "direction": "BUY" if direction > 0 else "SELL",
            "dir": int(direction),
            "regime": str(regime[entry_i]),
            "session": session_label(ts.to_pydatetime()),
            "sweep_level_type": sw["level_type"],
            "sweep_depth_atr": round(float(sw["depth"]), 3),
            "mss_choch_type": "choch",
            "displacement_strength": round(float(disp), 3),
            "fvg_size_atr": round(float(fvg_size), 3),
            "distance_to_fvg": round(float(dist), 3),
            "premium_discount": pd_zone,
            "htf_bias": int(htf[entry_i]),
            "sl": float(sl),
            "tp": float(tp),
        }
        out.append(annotate_fill(row, high, low, close, open_, n, hours))
        used_entry.add(entry_i)
    out.sort(key=lambda r: int(r["i"]))
    return out, dict(funnel)


def slice_by_days(df: pd.DataFrame, days: int):
    end = df.index.max()
    start = end - pd.Timedelta(days=days)
    return np.flatnonzero((df.index >= start) & (df.index <= end))


def filter_idx(rows, idx):
    allowed = set(int(x) for x in idx)
    return [r for r in rows if int(r["i"]) in allowed]


def summarize(name: str, raw):
    trades = apply_cd(raw)
    rs = [float(t["final_R"]) for t in trades]
    rs_sp = [float(t["final_R_spread"]) for t in trades]
    rs_st = [float(t["final_R_stress"]) for t in trades]
    base = metrics_from_rs(rs)
    sp = metrics_from_rs(rs_sp)
    st = metrics_from_rs(rs_st)
    mfe = [float(t["MFE_R"]) for t in trades]
    mae = [float(t["MAE_R"]) for t in trades]
    base["median_mfe"] = round(float(np.median(mfe)), 4) if mfe else 0.0
    base["median_mae"] = round(float(np.median(mae)), 4) if mae else 0.0
    return {
        "model": name,
        "raw_setups": len(raw),
        **base,
        "pf_after_spread": sp["profit_factor"],
        "exp_after_spread": sp["expectancy_R"],
        "pf_after_stress": st["profit_factor"],
        "exp_after_stress": st["expectancy_R"],
        "cluster_rate": clustering_rate(trades),
        "profit_by_hour": group_profit(trades, "hour"),
        "profit_by_regime": group_profit(trades, "regime"),
        "profit_by_direction": group_profit(trades, "direction"),
        "profit_by_session": group_profit(trades, "session"),
    }


def stability(trades, key: str, min_n: int = 6) -> bool:
    groups = defaultdict(list)
    for t in trades:
        groups[str(t.get(key, "NA"))].append(float(t["final_R"]))
    scored = []
    for rs in groups.values():
        if len(rs) < min_n:
            continue
        m = metrics_from_rs(rs)
        scored.append(m["expectancy_R"] >= -0.05 and m["profit_factor"] >= 0.85)
    if len(scored) < 2:
        return False
    return all(scored)


def pick_best(cands):
    best = "NONE"
    best_pf = -1.0
    for name, m in cands.items():
        if int(m.get("trades") or 0) < 8:
            continue
        pf = float(m["profit_factor"])
        if pf > best_pf:
            best_pf = pf
            best = name
    if best != "NONE":
        return best
    for name, m in cands.items():
        pf = float(m.get("profit_factor") or 0.0)
        if pf > best_pf:
            best_pf = pf
            best = name
    return best


def write_csv(path: Path, rows):
    cols = [
        "timestamp", "direction", "regime", "session", "sweep_level_type",
        "sweep_depth_atr", "mss_choch_type", "displacement_strength", "fvg_size_atr",
        "distance_to_fvg", "premium_discount", "htf_bias", "planned_rr", "MFE_R",
        "MAE_R", "final_R", "exit_reason", "final_R_spread", "final_R_stress", "hour",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(",".join(cols) + "\n", encoding="utf-8")
        return
    frame = pd.DataFrame(rows)
    for c in cols:
        if c not in frame.columns:
            frame[c] = ""
    frame[cols].to_csv(path, index=False)

def main() -> int:
    from tradingbot.config.price_action import get_price_action_config

    OUT.mkdir(parents=True, exist_ok=True)
    df = load_df()
    n = len(df)
    emit(f"DF bars={n} {df.index.min()} -> {df.index.max()}")
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    hours = np.array([int(ts.hour) for ts in df.index])
    dates = np.array([ts.date().isoformat() for ts in df.index])
    atr_pct = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct = np.where(np.isnan(atr_pct), 50.0, atr_pct)
    regime = infer_regimes(df)
    emit("precompute swings / HTF levels ...")
    swings = swing_arrays(high, low, n)
    pdh, pdl = last_completed_day_hl(dates, high, low, n)
    pwh, pwl = last_completed_week_hl(df.index, high, low, n)
    asian_hi, asian_lo = causal_range(dates, hours, high, low, n, 0, 8)
    lon_hi, lon_lo = causal_range(dates, hours, high, low, n, 7, 12)
    sess_hi, sess_lo = session_hl_arrays(dates, hours, n, asian_hi, asian_lo, lon_hi, lon_lo)
    htf_bias = htf_bias_array(df.index, close, n)
    ctx = {
        "n": n, "index": df.index, "hours": hours, "dates": dates,
        "high": high, "low": low, "close": close, "open": open_, "atr": atr,
        "atr_pct": atr_pct, "regime": regime, "swings": swings, "pdh": pdh,
        "pdl": pdl, "pwh": pwh, "pwl": pwl, "sess_hi": sess_hi, "sess_lo": sess_lo, "asian_hi": asian_hi, "asian_lo": asian_lo,
        "htf_bias": htf_bias,
    }
    live = get_price_action_config("XAUUSD", "M5")
    ny_s = int(live.get("NY_ENTRY_START_UTC", 15))
    ny_e = int(live.get("NY_ENTRY_END_UTC", 16))
    asian_end = int(live.get("ASIAN_SESSION_END_UTC", 8))
    emit(f"MODEL A window {ny_s}-{ny_e} asian_end={asian_end} (no Meta)")
    raw_a = collect_a(ctx, ny_s, ny_e, asian_end)
    emit(f"MODEL A raw={len(raw_a)}")
    emit("MODEL B sweep->MSS->FVG return ...")
    raw_b, fun_b = collect_structural(ctx, session=B_SESSION, use_htf_levels=False, require_pd=False)
    emit(f"MODEL B raw={len(raw_b)} funnel={fun_b}")
    emit("MODEL C HTF liquidity ...")
    raw_c, fun_c = collect_structural(ctx, session=C_SESSION, use_htf_levels=True, require_pd=True)
    emit(f"MODEL C raw={len(raw_c)} funnel={fun_c}")

    models_raw = {"A": raw_a, "B": raw_b, "C": raw_c}
    names = {"A": "MODEL_A_CURRENT_PA", "B": "MODEL_B_SWEEP_MSS_FVG", "C": "MODEL_C_HTF_LIQUIDITY"}
    windows = {"180d": np.arange(n), "90d": slice_by_days(df, 90), "30d": slice_by_days(df, 30)}
    folds = np.array_split(np.arange(n), 3)
    matrix = {
        "bars": n, "start": str(df.index.min()), "end": str(df.index.max()),
        "meta_used": False, "live_files_modified": False,
        "model_a_window_utc": f"{ny_s}-{ny_e}",
        "funnel_b": fun_b, "funnel_c": fun_c, "windows": {}, "walk_forward": {},
    }
    summaries = {}
    for wname, idx in windows.items():
        summaries[wname] = {}
        matrix["windows"][wname] = {}
        for key, raw in models_raw.items():
            sub = filter_idx(raw, idx)
            s = summarize(names[key], sub)
            summaries[wname][key] = s
            matrix["windows"][wname][names[key]] = s
            emit(f"  {wname} {key}: raw={s['raw_setups']} trades={s['trades']} PF={s['profit_factor']} ExpR={s['expectancy_R']}")
    for fi, idx in enumerate(folds, 1):
        matrix["walk_forward"][f"fold{fi}"] = {}
        for key, raw in models_raw.items():
            sub = filter_idx(raw, idx)
            s = summarize(names[key], sub)
            matrix["walk_forward"][f"fold{fi}"][names[key]] = {
                "trades": s["trades"], "profit_factor": s["profit_factor"], "expectancy_R": s["expectancy_R"],
            }

    a180, b180, c180 = summaries["180d"]["A"], summaries["180d"]["B"], summaries["180d"]["C"]
    best180 = pick_best(summaries["180d"])
    best30 = pick_best(summaries["30d"])
    best90 = pick_best(summaries["90d"])
    best_key = best180 if best180 != "NONE" else "A"
    wf_pfs, wf_exps = [], []
    for fi in range(1, 4):
        cell = matrix["walk_forward"][f"fold{fi}"][names[best_key]]
        wf_pfs.append(float(cell["profit_factor"]))
        wf_exps.append(float(cell["expectancy_R"]))
    wf_pf = round(float(np.mean(wf_pfs)), 3) if wf_pfs else 0.0
    wf_exp = round(float(np.mean(wf_exps)), 4) if wf_exps else 0.0
    best_sum = summaries["180d"][best_key]
    best_trades = apply_cd(models_raw[best_key])
    reg_ok = stability(best_trades, "regime")
    sess_ok = stability(best_trades, "session")
    dir_ok = stability(best_trades, "direction", min_n=8)

    def candidate(key: str) -> bool:
        m180, m90, m30 = summaries["180d"][key], summaries["90d"][key], summaries["30d"][key]
        if int(m180["trades"]) < 12:
            return False
        if float(m180["profit_factor"]) < 1.0 or float(m180["expectancy_R"]) < 0:
            return False
        ok_other = 0
        for o in (m90, m30):
            if int(o["trades"]) >= 6 and (float(o["profit_factor"]) >= 1.0 or float(o["expectancy_R"]) >= 0):
                ok_other += 1
        folds_ok = 0
        for fi in range(1, 4):
            cell = matrix["walk_forward"][f"fold{fi}"][names[key]]
            if int(cell["trades"]) >= 4 and float(cell["profit_factor"]) >= 0.9:
                folds_ok += 1
        return ok_other >= 1 and folds_ok >= 2

    cands = [names[k] for k in ("A", "B", "C") if candidate(k)]
    label = {"A": "A", "B": "B", "C": "C", "NONE": "NONE"}
    result = "\n".join([
        "PHASE_22A_RESULT",
        "",
        f"MODEL_A_PF={a180['profit_factor']}",
        f"MODEL_A_EXP_R={a180['expectancy_R']}",
        f"MODEL_A_TRADES={a180['trades']}",
        "",
        f"MODEL_B_PF={b180['profit_factor']}",
        f"MODEL_B_EXP_R={b180['expectancy_R']}",
        f"MODEL_B_TRADES={b180['trades']}",
        "",
        f"MODEL_C_PF={c180['profit_factor']}",
        f"MODEL_C_EXP_R={c180['expectancy_R']}",
        f"MODEL_C_TRADES={c180['trades']}",
        "",
        f"BEST_MODEL={label[best180]}",
        f"BEST_MODEL_30D={label[best30]}",
        f"BEST_MODEL_90D={label[best90]}",
        f"BEST_MODEL_180D={label[best180]}",
        "",
        f"BEST_MODEL_WF_PF={wf_pf}",
        f"BEST_MODEL_WF_EXP_R={wf_exp}",
        "",
        f"SPREAD_STRESS_PF={best_sum['pf_after_spread']}",
        f"SLIPPAGE_STRESS_PF={best_sum['pf_after_stress']}",
        "",
        f"REGIME_STABILITY={'YES' if reg_ok else 'NO'}",
        f"SESSION_STABILITY={'YES' if sess_ok else 'NO'}",
        f"DIRECTION_STABILITY={'YES' if dir_ok else 'NO'}",
        "",
        f"CANDIDATES_FOR_PHASE22B={','.join(cands) if cands else 'NONE'}",
        "LIVE_PATCH_APPLIED=NO",
        "",
    ])
    matrix["result_block"] = result
    (OUT / "strategy_discovery_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    write_csv(OUT / "model_a_current_pa.csv", apply_cd(raw_a))
    write_csv(OUT / "model_b_sweep_mss_fvg.csv", apply_cd(raw_b))
    write_csv(OUT / "model_c_htf_liquidity.csv", apply_cd(raw_c))
    (OUT / "phase22a_result.txt").write_text(result, encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())