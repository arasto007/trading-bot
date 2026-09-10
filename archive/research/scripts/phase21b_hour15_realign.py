#!/usr/bin/env python3
"""PHASE 21B — Hour-15 vs baseline 10-17, 180d PA replay (no Meta/RiskGate changes)."""
from __future__ import annotations

import os
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = ROOT / "logs" / "phase21b_hour15_realign_result.txt"
FWD = 96
MIN_RR = 1.5
SL_ATR = 0.35
MIN_RANGE = 0.2
SWEEP_LB = 12
SWEEP_ATR = 0.12
COOLDOWN, MAX_DAY = 18, 3
ATR_MIN, ATR_MAX = 12.0, 94.0
MAX_SPREAD = 15.0
BASE_SPREAD = 4.0


def load_df() -> pd.DataFrame:
    path = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    if "atr" not in df.columns:
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df


def simulate_path(high, low, close, i, direction, entry, sl, tp, n, max_bars=FWD) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    end = min(n, i + 1 + max_bars)
    for j in range(i + 1, end):
        hi = float(high[j])
        lo = float(low[j])
        if direction > 0:
            if lo <= sl:
                return round((sl - entry) / risk, 4)
            if hi >= tp:
                return round((tp - entry) / risk, 4)
        else:
            if hi >= sl:
                return round((entry - sl) / risk, 4)
            if lo <= tp:
                return round((entry - tp) / risk, 4)
    c = float(close[end - 1])
    return round(((c - entry) if direction > 0 else (entry - c)) / risk, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_dd_R": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(rs),
        "profit_factor": round(min(pf, 99.0), 3),
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_dd_R": round(mdd, 3),
    }


def apply_cd(cands, cd=COOLDOWN, max_day=MAX_DAY):
    out = []
    last = -10000
    open_until = -1
    day_counts: Counter[str] = Counter()
    for c in cands:
        i = c["i"]
        if i <= open_until or i - last < cd:
            continue
        if day_counts[c["day"]] >= max_day:
            continue
        out.append(c)
        last = i
        open_until = i + 12
        day_counts[c["day"]] += 1
    return out


def precompute_asian(dates, hours, high, low, n, end_hour):
    buckets = {}
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


def collect(df, cfg) -> list[dict[str, Any]]:
    from tradingbot.domain.gold_strategies.m5_london_sweep import m5_hour15_telemetry
    from tradingbot.domain.session_logic import variable_spread_pips

    n = len(df)
    hours = np.array([int(ts.hour) for ts in df.index])
    dates = np.array([ts.date().isoformat() for ts in df.index])
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    atr_pct = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct = np.where(np.isnan(atr_pct), 50.0, atr_pct)
    ny_s = int(cfg.get("NY_ENTRY_START_UTC", cfg.get("NY_ENTRY_START_HOUR", 10)))
    ny_e = int(cfg.get("NY_ENTRY_END_UTC", cfg.get("NY_ENTRY_END_HOUR", 17)))
    asian_end = int(cfg.get("ASIAN_SESSION_END_UTC", cfg.get("ASIAN_END_HOUR", 7)))
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", SWEEP_LB))
    sweep_atr = float(cfg.get("SWEEP_BUFFER_ATR", SWEEP_ATR))
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    roll_hi = df["high"].rolling(lookback + 1, min_periods=1).max().to_numpy(dtype=float)
    roll_lo = df["low"].rolling(lookback + 1, min_periods=1).min().to_numpy(dtype=float)
    asian = precompute_asian(dates, hours, high, low, n, asian_end)
    tel = m5_hour15_telemetry(cfg)
    cands = []
    for i in range(40, n - 2):
        if not (ny_s <= int(hours[i]) < ny_e):
            continue
        bounds = asian.get(dates[i])
        if bounds is None:
            continue
        asian_hi, asian_lo = bounds
        a = float(atr[i])
        if a <= 0 or (asian_hi - asian_lo) < a * MIN_RANGE:
            continue
        buf = a * sweep_atr
        wh = float(roll_hi[i])
        wl = float(roll_lo[i])
        price = float(close[i])
        direction = None
        if wh > asian_hi + buf and asian_lo < price < asian_hi:
            direction = -1
        elif wl < asian_lo - buf and asian_lo < price < asian_hi:
            direction = 1
        if direction is None:
            continue
        sl_pad = a * SL_ATR
        if direction < 0:
            sl = wh + sl_pad
            risk = sl - price
            tp = price - max(price - asian_lo, risk * MIN_RR)
        else:
            sl = wl - sl_pad
            risk = price - sl
            tp = price + max(asian_hi - price, risk * MIN_RR)
        if risk <= 0:
            continue
        rr = abs(tp - price) / risk
        if rr < MIN_RR * 0.95:
            continue
        conf = min(0.92, 0.55 + min(rr, 3.0) * 0.08)
        if conf < min_conf:
            continue
        sp = variable_spread_pips(BASE_SPREAD, int(hours[i]))
        if sp > MAX_SPREAD:
            continue
        if not (ATR_MIN <= float(atr_pct[i]) <= ATR_MAX):
            continue
        cands.append(
            {
                "i": i,
                "day": dates[i],
                "hour": int(hours[i]),
                "r": simulate_path(high, low, close, i, direction, price, sl, tp, n),
                "hour15_mode": tel["hour15_mode"],
                "asian_end_utc": tel["asian_end_utc"],
            }
        )
    return cands


def yn(ok: bool) -> str:
    return "YES" if ok else "NO"


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config

    df = load_df()
    print(f"DF bars={len(df)} {df.index.min()} -> {df.index.max()}", flush=True)

    live = deepcopy(get_price_action_config("XAUUSD", "M5"))
    live["ENABLE_CHOCH_CONTINUATION"] = False

    baseline = deepcopy(live)
    baseline["NY_ENTRY_START_HOUR"] = 10
    baseline["NY_ENTRY_END_HOUR"] = 17
    baseline["NY_ENTRY_START_UTC"] = 10
    baseline["NY_ENTRY_END_UTC"] = 17
    baseline["SESSION_START_HOUR"] = 10
    baseline["SESSION_END_HOUR"] = 17
    baseline["ASIAN_END_HOUR"] = 7
    baseline["ASIAN_SESSION_END_UTC"] = 7

    hour15 = deepcopy(live)
    hour15["NY_ENTRY_START_HOUR"] = 15
    hour15["NY_ENTRY_END_HOUR"] = 16
    hour15["NY_ENTRY_START_UTC"] = 15
    hour15["NY_ENTRY_END_UTC"] = 16
    hour15["SESSION_START_HOUR"] = 15
    hour15["SESSION_END_HOUR"] = 16
    hour15["ASIAN_END_HOUR"] = 8
    hour15["ASIAN_SESSION_END_UTC"] = 8

    print("BASELINE_10_17 ...", flush=True)
    b_raw = collect(df, baseline)
    b_tr = apply_cd(b_raw)
    b = metrics_from_rs([c["r"] for c in b_tr])
    print(f"  raw={len(b_raw)} trades={b['trades']} PF={b['profit_factor']} ExpR={b['expectancy_R']}", flush=True)

    print("HOUR15_15_16 ...", flush=True)
    h_raw = collect(df, hour15)
    h_tr = apply_cd(h_raw)
    h = metrics_from_rs([c["r"] for c in h_tr])
    print(f"  raw={len(h_raw)} trades={h['trades']} PF={h['profit_factor']} ExpR={h['expectancy_R']}", flush=True)

    edge = bool(
        float(h["profit_factor"]) >= float(b["profit_factor"])
        and float(h["expectancy_R"]) + 1e-12 >= float(b["expectancy_R"])
    )
    safe = bool(edge and float(h["profit_factor"]) >= 1.0 and float(h["expectancy_R"]) >= 0.0)

    lines = [
        "PHASE_21B_HOUR15_REALIGN",
        f"BARS={len(df)}",
        f"BASELINE_RAW={len(b_raw)}",
        f"HOUR15_RAW={len(h_raw)}",
        f"LIVE_PRESET_NY={live.get('NY_ENTRY_START_UTC')}-{live.get('NY_ENTRY_END_UTC')}",
        f"LIVE_PRESET_ASIAN_END={live.get('ASIAN_SESSION_END_UTC')}",
        f"HOUR15_MODE_STAMPED={yn(all(c.get('hour15_mode') for c in h_raw) if h_raw else False)}",
        "",
        "PHASE_21B_RESULT",
        "",
        f"BASELINE_TRADES={b['trades']}",
        f"BASELINE_PF={b['profit_factor']}",
        f"BASELINE_EXPECTANCY_R={b['expectancy_R']}",
        "",
        f"HOUR15_TRADES={h['trades']}",
        f"HOUR15_PF={h['profit_factor']}",
        f"HOUR15_EXPECTANCY_R={h['expectancy_R']}",
        f"HOUR15_MAX_DD_R={h['max_dd_R']}",
        "",
        f"EDGE_IMPROVED={yn(edge)}",
        f"SAFE_FOR_LIVE={yn(safe)}",
        "PATCH_APPLIED=YES",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())