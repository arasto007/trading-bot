#!/usr/bin/env python3
"""PHASE 19A ? Live Reclaim Intelligence (replay + telemetry only).

No live trading-logic changes. PATCH_APPLIED=NO.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from collections import Counter
from datetime import timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
    "TRADINGBOT_DRY_RUN": "1",
})
warnings.filterwarnings("ignore")

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

CACHE = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
OUT = ROOT / "logs" / "phase19a"
TRACKER = OUT / "post_sweep_tracker.jsonl"
TAXONOMY = OUT / "reclaim_taxonomy.parquet"
CURVE_JSON = OUT / "time_to_reclaim_curve.json"
DIST_JSON = OUT / "distance_to_reclaim_stats.json"
SESS_JSON = OUT / "session_split.json"
RESULT = OUT / "phase19a_result.txt"

WARMUP = 500
HORIZON = 20
NEAR_PCT = 0.25
TP_BARS = 24
CURVE_BARS = (1, 2, 3, 4, 5, 10, 15, 20)


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5() -> pd.DataFrame:
    df = pd.read_parquet(CACHE)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "atr" not in df.columns:
        tr = (df["high"] - df["low"]).abs()
        df = df.copy()
        df["atr"] = tr.rolling(14, min_periods=1).mean()
    return df.sort_index()


def asian_by_day(df: pd.DataFrame, start_h: int, end_h: int) -> dict[Any, tuple[float, float]]:
    dates = df.index.date
    hours = df.index.hour
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    buckets: dict[Any, list[int]] = {}
    for i, (d, h) in enumerate(zip(dates, hours)):
        if start_h <= int(h) < end_h:
            buckets.setdefault(d, []).append(i)
    out: dict[Any, tuple[float, float]] = {}
    for d, idxs in buckets.items():
        if len(idxs) < 4:
            continue
        hi = float(np.max(highs[idxs]))
        lo = float(np.min(lows[idxs]))
        if hi > lo:
            out[d] = (hi, lo)
    return out


def session_bucket(hour: int) -> str:
    if 7 <= hour < 10:
        return "LONDON_OPEN"
    if 10 <= hour < 14:
        return "NY_OPEN"
    if 14 <= hour < 17:
        return "NY_CONTINUATION"
    return "OTHER"


def last_swings(swings, i: int):
    last_high = last_low = None
    for sp in reversed(swings):
        if sp.index >= i:
            continue
        if sp.kind == "high" and last_high is None:
            last_high = sp
        elif sp.kind == "low" and last_low is None:
            last_low = sp
        if last_high is not None and last_low is not None:
            break
    return last_high, last_low


def bos_after(df: pd.DataFrame, start_i: int, end_i: int, direction: int) -> tuple[bool, int | None]:
    from tradingbot.domain.price_action import find_swings

    if start_i >= end_i or start_i >= len(df):
        return False, None
    w0 = max(0, start_i - 80)
    w1 = min(len(df), end_i + 1)
    window = df.iloc[w0:w1]
    swings = find_swings(window, 3, 3)
    local_start = start_i - w0
    for j in range(local_start, len(window)):
        c = float(window["close"].iloc[j])
        last_high, last_low = last_swings(swings, j)
        if direction > 0 and last_high is not None and c > last_high.price:
            return True, w0 + j
        if direction < 0 and last_low is not None and c < last_low.price:
            return True, w0 + j
    return False, None


def simulate_tp_sl(
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
    max_bars: int,
) -> tuple[bool, float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return False, 0.0
    end = min(len(highs), i + 1 + max_bars)
    mfe = 0.0
    for j in range(i + 1, end):
        hi = float(highs[j])
        lo = float(lows[j])
        if direction > 0:
            mfe = max(mfe, max(0.0, (hi - entry) / risk))
            if lo <= sl:
                return False, mfe
            if hi >= tp:
                return True, mfe
        else:
            mfe = max(mfe, max(0.0, (entry - lo) / risk))
            if hi >= sl:
                return False, mfe
            if lo <= tp:
                return True, mfe
    return False, mfe


def outside_distance_pct(close: float, asian_hi: float, asian_lo: float, side: str) -> float:
    rng = max(asian_hi - asian_lo, 1e-9)
    if side == "high":
        return round(max(0.0, (close - asian_hi) / rng * 100.0), 4)
    return round(max(0.0, (asian_lo - close) / rng * 100.0), 4)


def wick_touched_range(high: float, low: float, asian_hi: float, asian_lo: float, side: str) -> bool:
    if side == "high":
        return low < asian_hi
    return high > asian_lo


def main() -> int:
    from copy import deepcopy

    from tradingbot.config.price_action import get_price_action_config

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    asian_s = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_e = int(cfg.get("ASIAN_END_HOUR", 7))
    lookback_sw = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf_mult = float(cfg.get("SWEEP_BUFFER_ATR", 0.12))
    min_range_atr = float(cfg.get("MIN_RANGE_ATR", 0.2))
    min_rr = float(cfg.get("MIN_RR", 1.5))
    sl_atr_mult = float(cfg.get("SL_ATR_MULT", 0.35))

    df = load_m5()
    emit(f"PHASE 19A replay bars={len(df)} {df.index[0]} -> {df.index[-1]}")
    asian = asian_by_day(df, asian_s, asian_e)

    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    atr_arr = df["atr"].to_numpy(dtype=np.float64)
    hours = df.index.hour.to_numpy()
    dates = df.index.date
    roll_hi = pd.Series(highs).rolling(lookback_sw, min_periods=1).max().to_numpy()
    roll_lo = pd.Series(lows).rolling(lookback_sw, min_periods=1).min().to_numpy()

    events: list[dict[str, Any]] = []
    prev_hi = prev_lo = False
    prev_day = None
    n = len(df)

    for i in range(WARMUP, n - HORIZON - 1):
        h = int(hours[i])
        day = dates[i]
        if day != prev_day:
            prev_hi = prev_lo = False
            prev_day = day
        if not (7 <= h < 17):
            prev_hi = prev_lo = False
            continue
        bounds = asian.get(day)
        if bounds is None:
            prev_hi = prev_lo = False
            continue
        asian_hi, asian_lo = bounds
        atr = float(atr_arr[i]) if np.isfinite(atr_arr[i]) and atr_arr[i] > 0 else float(closes[i]) * 0.001
        if atr <= 0 or (asian_hi - asian_lo) < atr * min_range_atr:
            continue
        buf = atr * buf_mult
        swept_hi = float(roll_hi[i]) > asian_hi + buf
        swept_lo = float(roll_lo[i]) < asian_lo - buf

        onsets: list[str] = []
        if swept_hi and not prev_hi:
            onsets.append("high")
        if swept_lo and not prev_lo:
            onsets.append("low")
        prev_hi, prev_lo = swept_hi, swept_lo
        if not onsets:
            continue

        ts = df.index[i]
        ts_py = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else pd.Timestamp(ts).to_pydatetime()
        if ts_py.tzinfo is None:
            ts_py = ts_py.replace(tzinfo=timezone.utc)
        sweep_time = ts_py.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for side in onsets:
            direction = -1 if side == "high" else 1
            direction_str = "SELL" if direction < 0 else "BUY"
            bars_after: list[dict[str, Any]] = []
            inside_bars: list[int] = []
            near_bars: list[int] = []
            wick_near = False
            distances: list[float] = []
            for k in range(1, HORIZON + 1):
                j = i + k
                cl = float(closes[j])
                hi = float(highs[j])
                lo = float(lows[j])
                inside = asian_lo < cl < asian_hi
                dist = outside_distance_pct(cl, asian_hi, asian_lo, side)
                distances.append(dist)
                if inside:
                    inside_bars.append(k)
                    dist = 0.0
                rng = max(asian_hi - asian_lo, 1e-9)
                near = (not inside) and (dist / 100.0 <= NEAR_PCT)
                if wick_touched_range(hi, lo, asian_hi, asian_lo, side) and not inside:
                    wick_near = True
                    near = True
                if near:
                    near_bars.append(k)
                bars_after.append(
                    {
                        "bar": k,
                        "close": round(cl, 5),
                        "inside_asian": bool(inside),
                        "distance_from_range_pct": round(dist, 4),
                    }
                )

            closed_inside = bool(inside_bars)
            partial = (not closed_inside) and (bool(near_bars) or wick_near)
            no_return = (not closed_inside) and (not partial)

            first_inside = inside_bars[0] if inside_bars else None
            bos_ok = False
            bos_bar = None
            tp_hit = False
            mfe_r = 0.0
            if first_inside is not None:
                reclaim_i = i + first_inside
                bos_ok, bos_bar = bos_after(df, reclaim_i, min(n - 1, i + HORIZON), direction)
                entry = float(closes[reclaim_i])
                sl_pad = atr * sl_atr_mult
                win_high = float(np.max(highs[max(0, i - lookback_sw) : reclaim_i + 1]))
                win_low = float(np.min(lows[max(0, i - lookback_sw) : reclaim_i + 1]))
                if direction < 0:
                    sl = win_high + sl_pad
                    risk = sl - entry
                    tp = entry - max(max(entry - asian_lo, 0.0), risk * min_rr) if risk > 0 else entry
                else:
                    sl = win_low - sl_pad
                    risk = entry - sl
                    tp = entry + max(max(asian_hi - entry, 0.0), risk * min_rr) if risk > 0 else entry
                if risk > 0:
                    tp_hit, mfe_r = simulate_tp_sl(highs, lows, reclaim_i, direction, entry, sl, tp, TP_BARS)

            continuation_ok = bool(tp_hit or mfe_r >= 1.0)
            if no_return:
                label = "NO_RETURN"
            elif partial:
                label = "PARTIAL_RETURN"
            elif closed_inside and not bos_ok:
                label = "INSIDE_NO_BOS"
            elif closed_inside and bos_ok and not continuation_ok:
                label = "INSIDE_BOS_FAIL"
            else:
                label = "FULL_VALID"

            min_dist = float(min(distances)) if distances else 0.0
            max_pen = float(max(distances)) if distances else 0.0
            first_near = near_bars[0] if near_bars else (first_inside if first_inside else None)

            events.append(
                {
                    "sweep_time": sweep_time,
                    "bar_index": int(i),
                    "hour": h,
                    "session": session_bucket(h),
                    "direction": direction_str,
                    "direction_int": int(direction),
                    "sweep_side": side,
                    "asian_high": round(asian_hi, 5),
                    "asian_low": round(asian_lo, 5),
                    "label": label,
                    "reclaim": bool(closed_inside),
                    "bos_after_reclaim": bool(bos_ok),
                    "tp_after_reclaim": bool(tp_hit),
                    "mfe_r": round(float(mfe_r), 4),
                    "continuation_ok": bool(continuation_ok),
                    "bars_to_reclaim": first_inside,
                    "bars_to_nearest_return": first_near,
                    "min_distance_pct": round(min_dist if not closed_inside else 0.0, 4),
                    "max_penetration_pct": round(max_pen, 4),
                    "distance_bar1_pct": round(distances[0], 4) if distances else None,
                    "bos_bar_abs": bos_bar,
                    "bars_after_sweep": bars_after,
                }
            )

    emit(f"sweep onsets={len(events)}")
    with TRACKER.open("w", encoding="utf-8") as fh:
        for ev in events:
            rec = {
                "sweep_time": ev["sweep_time"],
                "direction": ev["direction"],
                "asian_high": ev["asian_high"],
                "asian_low": ev["asian_low"],
                "bars_after_sweep": ev["bars_after_sweep"],
            }
            fh.write(json.dumps(rec, ensure_ascii=True) + "\n")

    tax = pd.DataFrame([{k: v for k, v in ev.items() if k != "bars_after_sweep"} for ev in events])
    tax.to_parquet(TAXONOMY, index=False)

    n_sw = len(events)
    labels = Counter(ev["label"] for ev in events)
    reclaim_n = sum(1 for ev in events if ev["reclaim"])
    bos_n = sum(1 for ev in events if ev["reclaim"] and ev["bos_after_reclaim"])
    tp_n = sum(1 for ev in events if ev["reclaim"] and ev["tp_after_reclaim"])

    dists_all = [float(ev["min_distance_pct"]) for ev in events]
    dists_bar1 = [float(ev["distance_bar1_pct"]) for ev in events if ev["distance_bar1_pct"] is not None]
    pens = [float(ev["max_penetration_pct"]) for ev in events]
    bars_reclaim = [int(ev["bars_to_reclaim"]) for ev in events if ev["bars_to_reclaim"] is not None]
    bars_near = [int(ev["bars_to_nearest_return"]) for ev in events if ev["bars_to_nearest_return"] is not None]

    def pctile(xs: list[float], q: float) -> float:
        if not xs:
            return 0.0
        return float(np.percentile(np.asarray(xs, dtype=float), q))

    dist_stats = {
        "mean_min_distance_pct": round(float(np.mean(dists_all)) if dists_all else 0.0, 4),
        "mean_distance_bar1_pct": round(float(np.mean(dists_bar1)) if dists_bar1 else 0.0, 4),
        "p25_min_distance_pct": round(pctile(dists_all, 25), 4),
        "p50_min_distance_pct": round(pctile(dists_all, 50), 4),
        "p75_min_distance_pct": round(pctile(dists_all, 75), 4),
        "max_penetration_mean_pct": round(float(np.mean(pens)) if pens else 0.0, 4),
        "max_penetration_p50_pct": round(pctile(pens, 50), 4),
        "max_penetration_max_pct": round(float(max(pens)) if pens else 0.0, 4),
        "median_bars_to_reclaim": round(pctile([float(x) for x in bars_reclaim], 50), 4) if bars_reclaim else None,
        "median_bars_to_nearest_return": round(pctile([float(x) for x in bars_near], 50), 4) if bars_near else None,
        "n": n_sw,
    }
    DIST_JSON.write_text(json.dumps(dist_stats, indent=2), encoding="utf-8")

    curve = {}
    for b in CURVE_BARS:
        hit = sum(1 for ev in events if ev["bars_to_reclaim"] is not None and ev["bars_to_reclaim"] <= b)
        curve[str(b)] = round(100.0 * hit / n_sw, 2) if n_sw else 0.0
    CURVE_JSON.write_text(json.dumps({"bars_after_sweep": curve, "n": n_sw}, indent=2), encoding="utf-8")

    sessions = ("LONDON_OPEN", "NY_OPEN", "NY_CONTINUATION")
    sess_rows = {}
    for name in sessions:
        sub = [ev for ev in events if ev["session"] == name]
        ns = len(sub)
        rec = sum(1 for ev in sub if ev["reclaim"])
        bos = sum(1 for ev in sub if ev["reclaim"] and ev["bos_after_reclaim"])
        tp = sum(1 for ev in sub if ev["reclaim"] and ev["tp_after_reclaim"])
        sess_rows[name] = {
            "sweeps": ns,
            "reclaim_rate": round(100.0 * rec / ns, 2) if ns else 0.0,
            "bos_rate": round(100.0 * bos / rec, 2) if rec else 0.0,
            "tp_rate": round(100.0 * tp / rec, 2) if rec else 0.0,
            "reclaim_n": rec,
            "bos_n": bos,
            "tp_n": tp,
        }
    SESS_JSON.write_text(json.dumps(sess_rows, indent=2), encoding="utf-8")

    ranked = sorted(
        ((k, v["reclaim_rate"], v["sweeps"]) for k, v in sess_rows.items() if v["sweeps"] > 0),
        key=lambda x: (x[1], x[2]),
        reverse=True,
    )
    best_s = ranked[0][0] if ranked else "NONE"
    worst_s = ranked[-1][0] if ranked else "NONE"

    fail_modes = {k: labels.get(k, 0) for k in ("NO_RETURN", "PARTIAL_RETURN", "INSIDE_NO_BOS", "INSIDE_BOS_FAIL")}
    primary = max(fail_modes, key=fail_modes.get) if n_sw else "NONE"
    partial_share = labels.get("PARTIAL_RETURN", 0) / n_sw if n_sw else 0.0
    can_dd = bool(partial_share >= 0.20 or (primary == "PARTIAL_RETURN" and n_sw >= 50))

    reclaim_rate = 100.0 * reclaim_n / n_sw if n_sw else 0.0
    bos_rate = 100.0 * bos_n / reclaim_n if reclaim_n else 0.0
    tp_rate = 100.0 * tp_n / reclaim_n if reclaim_n else 0.0

    lines = [
        "PHASE_19A_RESULT",
        "",
        f"TOTAL_SWEEPS={n_sw}",
        f"FULL_VALID={labels.get('FULL_VALID', 0)}",
        f"NO_RETURN={labels.get('NO_RETURN', 0)}",
        f"PARTIAL_RETURN={labels.get('PARTIAL_RETURN', 0)}",
        f"INSIDE_NO_BOS={labels.get('INSIDE_NO_BOS', 0)}",
        f"INSIDE_BOS_FAIL={labels.get('INSIDE_BOS_FAIL', 0)}",
        "",
        f"RECLAIM_SUCCESS_RATE={reclaim_rate:.2f}",
        f"BOS_AFTER_RECLAIM_RATE={bos_rate:.2f}",
        f"TP_AFTER_RECLAIM_RATE={tp_rate:.2f}",
        "",
        f"MEDIAN_RECLAIM_DISTANCE_PCT={pctile(dists_bar1, 50):.4f}",
        f"P75_RECLAIM_DISTANCE_PCT={pctile(dists_bar1, 75):.4f}",
        f"MEDIAN_BARS_TO_RECLAIM={dist_stats['median_bars_to_reclaim'] if dist_stats['median_bars_to_reclaim'] is not None else 'NA'}",
        "",
        f"BEST_SESSION={best_s}",
        f"WORST_SESSION={worst_s}",
        "",
        f"PRIMARY_RECLAIM_FAILURE_MODE={primary}",
        f"CAN_DEFINE_DATA_DRIVEN_RECLAIM={'YES' if can_dd else 'NO'}",
        "PATCH_APPLIED=NO",
        "",
        "TIME_TO_RECLAIM_CURVE_PCT=",
    ]
    for b in CURVE_BARS:
        lines.append(f"  bars={b} reclaim_pct={curve[str(b)]}")
    lines.append("")
    lines.append("SESSION_SPLIT=")
    for name in sessions:
        s = sess_rows[name]
        lines.append(
            f"  {name}: sweeps={s['sweeps']} reclaim={s['reclaim_rate']}% "
            f"bos={s['bos_rate']}% tp={s['tp_rate']}%"
        )
    lines += [
        "",
        f"PARTIAL_SHARE={round(100.0 * partial_share, 2)}",
        f"MEAN_DISTANCE_BAR1_PCT={dist_stats['mean_distance_bar1_pct']}",
        f"MAX_PENETRATION_P50_PCT={dist_stats['max_penetration_p50_pct']}",
        f"MEDIAN_BARS_TO_NEAREST_RETURN={dist_stats['median_bars_to_nearest_return']}",
        "MODE=RESEARCH_REPLAY_ONLY",
        "LIVE_LOGIC_CHANGED=NO",
    ]
    text = "\n".join(lines) + "\n"
    RESULT.write_text(text, encoding="utf-8")
    emit(text)
    emit(f"WROTE {TRACKER}")
    emit(f"WROTE {TAXONOMY}")
    emit(f"WROTE {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
