#!/usr/bin/env python3
"""PHASE 21A — PA setup formation root-cause lab (READ-ONLY, no live patches)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT_DIR = ROOT / "logs" / "phase21a"
LOOKBACKS = (8, 12, 16, 20)
ASIAN_ENDS = (6, 7, 8)
RECLAIM_BARS = (1, 2, 3, 5)
SWEEP_ATRS = (0.05, 0.10, 0.15, 0.20)
SWING_RIGHTS = (2, 3, 4)
FWD = 96
NY_S, NY_E = 10, 17
LIVE_LOOKBACK = 12
LIVE_ASIAN_END = 7
LIVE_RECLAIM = 1
LIVE_SWEEP_ATR = 0.12
MIN_RANGE_ATR = 0.2
MIN_RR = 1.5
SL_ATR = 0.35
MIN_QUALITY = 55
ATR_PCT_MIN, ATR_PCT_MAX = 12.0, 94.0
MAX_SPREAD_PIPS = 15.0
BASE_SPREAD = 4.0
COOLDOWN, MAX_DAY = 18, 3
REGIME_MAP = {
    "STRONG_TREND_UP": 1.0,
    "STRONG_TREND_DOWN": -1.0,
    "RANGING": 0.0,
    "VOLATILE": 0.5,
    "CRISIS": -0.5,
}


def emit(msg: str) -> None:
    print(msg, flush=True)


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
        return {"trades": 0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_dd_R": 0.0, "win_rate": 0.0}
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
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(min(pf, 99.0), 3),
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_dd_R": round(mdd, 3),
    }


def apply_cd(cands: list[dict[str, Any]], cd: int = COOLDOWN, max_day: int = MAX_DAY) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    last = -10000
    open_until = -1
    day_counts: Counter[str] = Counter()
    blocked = []
    for c in cands:
        i = c["i"]
        if i <= open_until or i - last < cd:
            c = dict(c)
            c["cd_block"] = "cooldown_block"
            blocked.append(c)
            continue
        if day_counts[c["day"]] >= max_day:
            c = dict(c)
            c["cd_block"] = "daily_limit_block"
            blocked.append(c)
            continue
        out.append(c)
        last = i
        open_until = i + 12
        day_counts[c["day"]] += 1
    return out


def session_quality(hour: int) -> float:
    if 12 <= hour < 15:
        return 90.0
    if 15 <= hour < 17:
        return 70.0
    if 10 <= hour < 12:
        return 65.0
    return 40.0


def precompute_asian(dates, hours, high, low, n: int, end_hour: int) -> dict[Any, tuple[float, float] | None]:
    buckets: dict[Any, list[int]] = defaultdict(list)
    for i in range(n):
        if 0 <= int(hours[i]) < end_hour:
            buckets[dates[i]].append(i)
    out: dict[Any, tuple[float, float] | None] = {}
    for day, idxs in buckets.items():
        if len(idxs) < 4:
            out[day] = None
            continue
        hi = float(np.max(high[idxs]))
        lo = float(np.min(low[idxs]))
        out[day] = (hi, lo) if hi > lo else None
    return out


def quality_score(*, bos: bool, confluence: float = 3.2) -> int:
    score = 40.0 + min(20.0, confluence * 4.0)
    if bos:
        score += 12.0
    score += 10.0  # liquidity sweep
    score += 5.0  # LIQUIDITY_SWEEP type
    return int(max(0, min(100, round(score))))


def build_setup(i, direction, price, atr, asian_hi, asian_lo, win_high, win_low):
    sl_pad = atr * SL_ATR
    if direction < 0:
        sl = win_high + sl_pad
        risk = sl - price
        tp = price - max(price - asian_lo, risk * MIN_RR)
    else:
        sl = win_low - sl_pad
        risk = price - sl
        tp = price + max(asian_hi - price, risk * MIN_RR)
    if risk <= 0:
        return None
    rr = abs(tp - price) / risk
    if rr < MIN_RR * 0.95:
        return None
    conf = min(0.92, 0.55 + min(rr, 3.0) * 0.08)
    return {
        "i": i,
        "direction": direction,
        "entry": price,
        "sl": float(sl),
        "tp": float(tp),
        "rr": round(rr, 2),
        "confidence": round(conf, 3),
    }


def bos_at(breaks, i: int, direction: int) -> tuple[bool, str]:
    last = None
    for br in reversed(breaks):
        if br.index > i or br.index < i - 12:
            continue
        last = br
        break
    if last is None:
        return False, "no_bos"
    if last.kind == "bos" and int(last.direction) == int(direction):
        return True, "bos_ok"
    if int(last.direction) != int(direction):
        return False, "bos_wrong_direction"
    return False, "no_bos"


def false_breakout(high, low, close, i, direction, level, n, bars=8) -> bool:
    end = min(n, i + 1 + bars)
    for j in range(i + 1, end):
        c = float(close[j])
        if direction > 0 and c < level:
            return True
        if direction < 0 and c > level:
            return True
    return False


def main() -> int:
    from tradingbot.domain.pa_hardening import detect_bos_continuation
    from tradingbot.domain.price_action import detect_fvgs, detect_structure_breaks, find_swings
    from tradingbot.domain.session_logic import variable_spread_pips
    from tradingbot.ml.features.unified_feature_store import FEATURES, to_vector
    from tradingbot.services.meta_labeler import reload_meta_labeler

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_df()
    n = len(df)
    emit(f"DF bars={n} {df.index.min()} -> {df.index.max()}")

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    adx = df["adx"].to_numpy(dtype=float) if "adx" in df.columns else np.zeros(n)
    hours = np.array([int(ts.hour) for ts in df.index], dtype=int)
    weekdays = np.array([int(ts.weekday()) for ts in df.index], dtype=int)
    dates = np.array([ts.date().isoformat() for ts in df.index])
    ny_mask = (hours >= NY_S) & (hours < NY_E)
    ny_idx = np.flatnonzero(ny_mask)
    emit(f"NY bars={len(ny_idx)}")

    atr_pct = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct = np.where(np.isnan(atr_pct), 50.0, atr_pct)
    spread = np.array([variable_spread_pips(BASE_SPREAD, int(h)) for h in hours], dtype=float)

    sma20 = df["sma_20"].to_numpy(dtype=float) if "sma_20" in df.columns else df["close"].rolling(20).mean().to_numpy()
    sma50 = df["sma_50"].to_numpy(dtype=float) if "sma_50" in df.columns else df["close"].rolling(50).mean().to_numpy()
    atr_mean = pd.Series(atr).rolling(20, min_periods=5).mean().to_numpy()
    ratio = np.divide(atr, atr_mean, out=np.ones(n), where=atr_mean > 0)
    regime = np.full(n, "RANGING", dtype=object)
    regime[ratio >= 2.0] = "CRISIS"
    regime[(ratio >= 1.5) & (ratio < 2.0)] = "VOLATILE"
    regime[(ratio < 1.5) & (close > sma20) & (sma20 > sma50)] = "STRONG_TREND_UP"
    regime[(ratio < 1.5) & (close < sma20) & (sma20 < sma50)] = "STRONG_TREND_DOWN"

    asian = {end: precompute_asian(dates, hours, high, low, n, end) for end in ASIAN_ENDS}
    asian[LIVE_ASIAN_END] = asian.get(LIVE_ASIAN_END) or precompute_asian(dates, hours, high, low, n, LIVE_ASIAN_END)

    roll_hi = {}
    roll_lo = {}
    for lb in set(LOOKBACKS + (LIVE_LOOKBACK,)):
        roll_hi[lb] = df["high"].rolling(lb + 1, min_periods=1).max().to_numpy(dtype=float)
        roll_lo[lb] = df["low"].rolling(lb + 1, min_periods=1).min().to_numpy(dtype=float)

    emit("computing swings / structure ...")
    swings_by_r = {r: find_swings(df, 3, r) for r in SWING_RIGHTS}
    fvgs = detect_fvgs(df, 80)

    _breaks_cache: dict[tuple[int, int], list] = {}

    def breaks_at(i: int, right: int = 3):
        key = (int(i), int(right))
        hit = _breaks_cache.get(key)
        if hit is not None:
            return hit
        brs = detect_structure_breaks(df, swings_by_r[right], at_index=i)
        _breaks_cache[key] = brs
        return brs

    meta = reload_meta_labeler()
    model = meta._models.get("M5")
    if model is None:
        raise RuntimeError("meta_labeler_m5.pkl missing")

    _meta_cache: dict[tuple[Any, ...], float] = {}

    def meta_prob(row: dict[str, Any]) -> float:
        i = row["i"]
        key = (int(i), int(row["direction"]), round(float(row["rr"]), 2), round(float(row["confidence"]), 3))
        hit = _meta_cache.get(key)
        if hit is not None:
            return hit
        feats = {
            "confidence": row["confidence"],
            "confluence": 3.2,
            "rr": row["rr"],
            "adx": float(adx[i]) if not np.isnan(adx[i]) else 0.0,
            "atr_pct": float(atr_pct[i]),
            "htf_bias": 0.0,
            "hour_utc": float(hours[i]),
            "weekday": float(weekdays[i]),
            "direction": 1.0 if row["direction"] > 0 else -1.0,
            "regime_code": REGIME_MAP.get(str(regime[i]), 0.0),
            "spread_pips": float(spread[i]),
            "sl_atr_mult": SL_ATR,
            "setup_code": 1.0,
        }
        vec = to_vector(feats)
        try:
            proba = model.predict_proba([vec])[0]
            p = float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception:
            p = 1.0
        _meta_cache[key] = p
        return p

    def effective_th(i: int) -> float:
        return float(meta.effective_threshold("M5", str(regime[i]), 0.38))

    def collect(lookback: int, asian_end: int, reclaim_n: int, sweep_atr: float, right: int = 3):
        raw = []
        reclaim_n_int = int(reclaim_n)
        for i in ny_idx:
            if i < 40:
                continue
            bounds = asian[asian_end].get(dates[i])
            if bounds is None:
                continue
            asian_hi, asian_lo = bounds
            a = float(atr[i])
            if a <= 0:
                continue
            if (asian_hi - asian_lo) < a * MIN_RANGE_ATR:
                continue
            buf = a * sweep_atr
            wh = float(roll_hi[lookback][i])
            wl = float(roll_lo[lookback][i])
            swept_hi = wh > asian_hi + buf
            swept_lo = wl < asian_lo - buf
            if not (swept_hi or swept_lo):
                continue
            rec_dir = None
            rec_j = None
            start = max(0, i - reclaim_n_int + 1)
            for j in range(start, i + 1):
                cj = float(close[j])
                if swept_hi and asian_lo < cj < asian_hi:
                    rec_j = j
                    rec_dir = -1
                elif swept_lo and asian_lo < cj < asian_hi:
                    rec_j = j
                    rec_dir = 1
            if rec_dir is None:
                continue
            setup = build_setup(int(i), rec_dir, float(close[i]), a, asian_hi, asian_lo, wh, wl)
            if setup is None:
                continue
            setup["day"] = dates[i]
            setup["hour"] = int(hours[i])
            setup["reclaim_j"] = int(rec_j)
            setup["current_inside"] = bool(asian_lo < float(close[i]) < asian_hi)
            raw.append(setup)
        return raw

    def annotate(raw: list[dict[str, Any]], right: int = 3) -> list[dict[str, Any]]:
        out = []
        for s in raw:
            i = s["i"]
            brs = breaks_at(i, right)
            bos_ok, bos_tag = bos_at(brs, i, s["direction"])
            if not bos_ok:
                bos_ok = detect_bos_continuation(brs, i, s["direction"])
                bos_tag = "bos_ok" if bos_ok else bos_tag
            q = quality_score(bos=bos_ok)
            s = dict(s)
            s["bos"] = bos_ok
            s["bos_tag"] = bos_tag
            s["quality"] = q
            s["atr_pct"] = float(atr_pct[i])
            s["spread"] = float(spread[i])
            s["session_quality"] = session_quality(int(hours[i]))
            s["atr_ok"] = ATR_PCT_MIN <= s["atr_pct"] <= ATR_PCT_MAX
            s["spread_ok"] = s["spread"] <= MAX_SPREAD_PIPS
            s["quality_ok"] = q >= MIN_QUALITY
            s["meta_score"] = meta_prob(s)
            s["meta_th"] = effective_th(i)
            s["meta_pass"] = s["meta_score"] >= s["meta_th"]
            s["r"] = simulate_path(high, low, close, i, s["direction"], s["entry"], s["sl"], s["tp"], n)
            out.append(s)
        return out

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        passed = [r for r in rows if r["quality_ok"] and r["atr_ok"] and r["spread_ok"]]
        meta_pass = [r for r in passed if r["meta_pass"]]
        trades = apply_cd(passed)
        m = metrics_from_rs([t["r"] for t in trades])
        return {
            "raw_setups": len(rows),
            "reclaim_count": sum(1 for r in rows if r.get("reclaim_j") is not None),
            "bos_count": sum(1 for r in rows if r.get("bos")),
            "meta_pass_count": len(meta_pass),
            "trades_after_cooldown": m["trades"],
            "PF": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "max_dd_R": m["max_dd_R"],
            "win_rate": m["win_rate"],
        }

    emit("baseline live config ...")
    base_raw = collect(LIVE_LOOKBACK, LIVE_ASIAN_END, LIVE_RECLAIM, LIVE_SWEEP_ATR, 3)
    base_ann = annotate(base_raw, 3)
    base_sum = summarize(base_ann)
    emit(f"BASELINE raw={base_sum['raw_setups']} trades={base_sum['trades_after_cooldown']} PF={base_sum['PF']}")

    matrix_rows = []
    total = len(LOOKBACKS) * len(ASIAN_ENDS) * len(RECLAIM_BARS) * len(SWEEP_ATRS)
    done = 0
    emit(f"parameter sweep combos={total}")
    for lb in LOOKBACKS:
        for ae in ASIAN_ENDS:
            for rb in RECLAIM_BARS:
                for sa in SWEEP_ATRS:
                    done += 1
                    raw = collect(lb, ae, rb, sa, 3)
                    ann = annotate(raw, 3)
                    sm = summarize(ann)
                    sm.update({
                        "SWEEP_LOOKBACK": lb,
                        "ASIAN_SESSION_END": ae,
                        "RECLAIM_BARS": rb,
                        "MIN_SWEEP_DISTANCE_ATR": sa,
                    })
                    matrix_rows.append(sm)
                    if done % 16 == 0:
                        emit(f"  combo {done}/{total} raw={sm['raw_setups']} PF={sm['PF']}")

    # live baseline extra row
    live_row = dict(base_sum)
    live_row.update({
        "SWEEP_LOOKBACK": LIVE_LOOKBACK,
        "ASIAN_SESSION_END": LIVE_ASIAN_END,
        "RECLAIM_BARS": LIVE_RECLAIM,
        "MIN_SWEEP_DISTANCE_ATR": LIVE_SWEEP_ATR,
        "is_live_baseline": True,
    })
    matrix_rows.append(live_row)
    matrix = pd.DataFrame(matrix_rows)
    matrix.to_parquet(OUT_DIR / "parameter_matrix.parquet", index=False)

    # TASK 2 heatmap on live successful reclaims
    heat_src = [r for r in base_ann if r.get("reclaim_j") is not None]
    heat_rows = []
    for h in range(24):
        grp = [r for r in heat_src if r["hour"] == h]
        m = metrics_from_rs([r["r"] for r in grp])
        heat_rows.append({
            "hour_utc": h,
            "n": len(grp),
            "session_quality": session_quality(h),
            "mean_spread": round(float(np.mean([r["spread"] for r in grp])), 3) if grp else 0.0,
            "mean_atr_pct": round(float(np.mean([r["atr_pct"] for r in grp])), 3) if grp else 0.0,
            "win_rate": m["win_rate"],
            "PF": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "max_dd_R": m["max_dd_R"],
        })
    heat = pd.DataFrame(heat_rows)
    heat.to_csv(OUT_DIR / "hourly_heatmap.csv", index=False)

    best_pair = None
    best_pair_score = -999.0
    for h0 in range(NY_S, NY_E - 1):
        grp = [r for r in heat_src if h0 <= r["hour"] < h0 + 2]
        m = metrics_from_rs([r["r"] for r in grp])
        score = m["expectancy_R"] if m["trades"] >= 8 else -999.0
        if score > best_pair_score:
            best_pair_score = score
            best_pair = {"start": h0, "end": h0 + 2, **m}

    # TASK 3 BOS lag on live reclaims
    lag = {}
    for right in SWING_RIGHTS:
        rows = []
        fb = 0
        bos_n = 0
        for s in base_raw:
            i = s["i"]
            brs = breaks_at(i, right)
            bos_ok, _ = bos_at(brs, i, s["direction"])
            if not bos_ok:
                bos_ok = detect_bos_continuation(brs, i, s["direction"])
            level = None
            for br in reversed(brs):
                if br.index <= i:
                    level = float(br.level)
                    break
            r = simulate_path(high, low, close, i, s["direction"], s["entry"], s["sl"], s["tp"], n)
            if bos_ok:
                bos_n += 1
                if level is not None and false_breakout(high, low, close, i, s["direction"], level, n):
                    fb += 1
            rows.append(r)
        m = metrics_from_rs(rows)
        lag[str(right)] = {
            "swing_right": right,
            "reclaim_n": len(base_raw),
            "bos_detection_rate": round(bos_n / max(len(base_raw), 1), 4),
            "false_breakout_rate": round(fb / max(bos_n, 1), 4),
            "PF": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "trades": m["trades"],
        }
    (OUT_DIR / "bos_lag_analysis.json").write_text(json.dumps(lag, indent=2), encoding="utf-8")

    # TASK 4 scarcity on live path (in-session + asian)
    reasons = Counter()
    scanned = 0
    live_passed_i = {r["i"] for r in base_ann}
    cd_kept = {t["i"] for t in apply_cd([r for r in base_ann if r["quality_ok"] and r["atr_ok"] and r["spread_ok"]])}
    for i in ny_idx:
        if i < 40:
            continue
        scanned += 1
        bounds = asian[LIVE_ASIAN_END].get(dates[i])
        if bounds is None:
            reasons["no_sweep"] += 1
            continue
        asian_hi, asian_lo = bounds
        a = float(atr[i])
        if a <= 0 or (asian_hi - asian_lo) < a * MIN_RANGE_ATR:
            reasons["no_sweep"] += 1
            continue
        buf = a * LIVE_SWEEP_ATR
        wh = float(roll_hi[LIVE_LOOKBACK][i])
        wl = float(roll_lo[LIVE_LOOKBACK][i])
        swept_hi = wh > asian_hi + buf
        swept_lo = wl < asian_lo - buf
        if not (swept_hi or swept_lo):
            reasons["no_sweep"] += 1
            continue
        inside_now = asian_lo < float(close[i]) < asian_hi
        rec_dir = rec_j = None
        start5 = max(0, i - 4)
        for j in range(start5, i + 1):
            cj = float(close[j])
            if swept_hi and asian_lo < cj < asian_hi:
                rec_j, rec_dir = j, -1
            elif swept_lo and asian_lo < cj < asian_hi:
                rec_j, rec_dir = j, 1
        if rec_dir is None:
            reasons["no_reclaim"] += 1
            continue
        if not inside_now:
            reasons["reclaim_too_late"] += 1
            continue
        setup = build_setup(int(i), rec_dir, float(close[i]), a, asian_hi, asian_lo, wh, wl)
        if setup is None:
            reasons["no_reclaim"] += 1
            continue
        brs = breaks_at(int(i), 3)
        bos_ok, bos_tag = bos_at(brs, int(i), rec_dir)
        if not bos_ok:
            bos_ok = detect_bos_continuation(brs, int(i), rec_dir)
            bos_tag = "bos_ok" if bos_ok else bos_tag
        # BOS is not a live hard gate; only record if later filters pass and we still want structure stats
        q = quality_score(bos=bos_ok)
        apct = float(atr_pct[i])
        sp = float(spread[i])
        if sp > MAX_SPREAD_PIPS:
            reasons["spread_bad"] += 1
            continue
        if not (ATR_PCT_MIN <= apct <= ATR_PCT_MAX):
            reasons["atr_bad"] += 1
            continue
        if q < MIN_QUALITY:
            reasons["quality_bad"] += 1
            continue
        row = dict(setup)
        row["confidence"] = setup["confidence"]
        row["rr"] = setup["rr"]
        row["direction"] = rec_dir
        row["i"] = int(i)
        p = meta_prob(row)
        th = effective_th(int(i))
        if p < th:
            reasons["meta_reject"] += 1
            continue
        if int(i) not in cd_kept:
            # distinguish cooldown vs daily using a second pass marker
            reasons["cooldown_block"] += 1
            continue
        # trade accepted — not a killer
        reasons["accepted"] += 1

    # refine cooldown vs daily on the quality+atr+spread passed set
    passed_pre_cd = [r for r in base_ann if r["quality_ok"] and r["atr_ok"] and r["spread_ok"] and r["meta_pass"]]
    reasons["cooldown_block"] = 0
    reasons["daily_limit_block"] = 0
    reasons["accepted"] = 0
    last = -10000
    open_until = -1
    day_counts: Counter[str] = Counter()
    for c in passed_pre_cd:
        i = c["i"]
        if i <= open_until or i - last < COOLDOWN:
            reasons["cooldown_block"] += 1
            continue
        if day_counts[c["day"]] >= MAX_DAY:
            reasons["daily_limit_block"] += 1
            continue
        reasons["accepted"] += 1
        last = i
        open_until = i + 12
        day_counts[c["day"]] += 1

    # BOS tags among live reclaims (not first-fail, but reported)
    bos_miss = sum(1 for r in base_ann if not r["bos"])
    bos_wrong = sum(1 for r in base_ann if r.get("bos_tag") == "bos_wrong_direction")
    reasons["no_bos"] = bos_miss
    reasons["bos_wrong_direction"] = bos_wrong

    total_reasons = sum(reasons[k] for k in reasons if k != "accepted")
    pct = {}
    for k in (
        "no_sweep", "no_reclaim", "reclaim_too_late", "no_bos", "bos_wrong_direction",
        "spread_bad", "atr_bad", "quality_bad", "meta_reject", "cooldown_block", "daily_limit_block",
    ):
        pct[k] = round(100.0 * reasons[k] / max(scanned, 1), 3)
    # first-fail % among in-session bars (no_bos is overlay, not exclusive)
    first_fail_keys = (
        "no_sweep", "no_reclaim", "reclaim_too_late", "spread_bad", "atr_bad",
        "quality_bad", "meta_reject", "cooldown_block", "daily_limit_block",
    )
    ff_total = sum(reasons[k] for k in first_fail_keys)
    first_fail_pct = {k: round(100.0 * reasons[k] / max(ff_total, 1), 3) for k in first_fail_keys}
    primary = max(first_fail_keys, key=lambda k: reasons[k])
    scarcity = {
        "scanned_ny_bars": scanned,
        "counts": dict(reasons),
        "pct_of_ny_bars": pct,
        "first_fail_pct": first_fail_pct,
        "primary_setup_killer": primary,
        "note": "no_bos/bos_wrong_direction are overlays; live london_sweep does not hard-gate BOS",
    }
    (OUT_DIR / "scarcity_breakdown.json").write_text(json.dumps(scarcity, indent=2), encoding="utf-8")

    # BEST config: quality-preserving vs live baseline
    grid = matrix[matrix.get("is_live_baseline").fillna(False) == False] if "is_live_baseline" in matrix.columns else matrix
    if "is_live_baseline" in matrix.columns:
        grid = matrix[matrix["is_live_baseline"].fillna(False) != True]
    else:
        grid = matrix
    b_pf = float(base_sum["PF"])
    b_ex = float(base_sum["expectancy_R"])
    b_dd = float(base_sum["max_dd_R"])
    b_raw = max(int(base_sum["raw_setups"]), 1)
    b_meta = max(int(base_sum["meta_pass_count"]), 1)
    survivors = grid[
        (grid["trades_after_cooldown"] >= max(8, int(base_sum["trades_after_cooldown"]) * 0.8))
        & (grid["PF"] + 1e-12 >= b_pf * 0.95)
        & (grid["expectancy_R"] + 1e-12 >= b_ex)
        & (grid["max_dd_R"] <= b_dd + 1.0)
    ]
    if len(survivors):
        best = survivors.sort_values(["expectancy_R", "PF", "raw_setups"], ascending=False).iloc[0]
        safe = True
    else:
        best = grid.sort_values(["expectancy_R", "PF"], ascending=False).iloc[0]
        safe = False

    raw_gain = 100.0 * (float(best["raw_setups"]) - b_raw) / b_raw
    meta_gain = 100.0 * (float(best["meta_pass_count"]) - b_meta) / b_meta
    best_right = "3"
    best_expr = -999
    for k, v in lag.items():
        if v["expectancy_R"] > best_expr:
            best_expr = v["expectancy_R"]
            best_right = k

    if primary in ("no_reclaim", "reclaim_too_late"):
        nxt = "PHASE_21B_RECLAIM_TIMING"
    elif primary == "no_sweep":
        nxt = "PHASE_21B_SWEEP_WINDOW"
    elif primary == "meta_reject":
        nxt = "PHASE_21B_KEEP_META_OBSERVER"
    elif primary in ("cooldown_block", "daily_limit_block"):
        nxt = "PHASE_21B_THROTTLE_AUDIT"
    elif primary in ("atr_bad", "spread_bad"):
        nxt = "PHASE_21B_MARKET_FILTER_TUNE"
    else:
        nxt = "PHASE_21B_TARGETED_RECLAIM"

    # do not recommend live patch if quality not preserved
    if not safe:
        nxt = nxt  # keep diagnosis

    lines = [
        "PHASE_21A_SETUP_FORMATION_LAB",
        "PATCH_APPLIED=NO",
        f"BARS={n}",
        f"NY_BARS={len(ny_idx)}",
        f"LIVE_BASELINE_RAW={base_sum['raw_setups']}",
        f"LIVE_BASELINE_TRADES={base_sum['trades_after_cooldown']}",
        f"LIVE_BASELINE_PF={base_sum['PF']}",
        f"LIVE_BASELINE_EXPR={base_sum['expectancy_R']}",
        f"BEST_2H_WINDOW={best_pair['start']:02d}-{best_pair['end']:02d}" if best_pair else "BEST_2H_WINDOW=NA",
        f"BEST_2H_EXPR={best_pair['expectancy_R'] if best_pair else 'NA'}",
        f"QUALITY_SURVIVORS={len(survivors)}",
        "",
        "PHASE_21A_RESULT",
        f"BEST_SWEEP_LOOKBACK={int(best['SWEEP_LOOKBACK'])}",
        f"BEST_RECLAIM_BARS={int(best['RECLAIM_BARS'])}",
        f"BEST_ASIAN_END_UTC={int(best['ASIAN_SESSION_END']):02d}:00",
        f"BEST_MIN_SWEEP_ATR={float(best['MIN_SWEEP_DISTANCE_ATR']):.2f}",
        f"BEST_SWING_RIGHT={best_right}",
        f"RAW_SETUP_GAIN_PCT={raw_gain:.2f}",
        f"META_PASS_GAIN_PCT={meta_gain:.2f}",
        f"PF_AT_BEST_CONFIG={float(best['PF']):.3f}",
        f"EXPECTANCY_AT_BEST_CONFIG={float(best['expectancy_R']):.4f}",
        f"MAX_DD_AT_BEST_CONFIG={float(best['max_dd_R']):.3f}",
        f"PRIMARY_SETUP_KILLER={primary}",
        f"SAFE_FOR_LIVE_PATCH={'YES' if safe else 'NO'}",
        f"RECOMMENDED_NEXT_PHASE={nxt}",
        "PATCH_APPLIED=NO",
        "",
    ]
    (OUT_DIR / "phase21a_result.txt").write_text("\n".join(lines), encoding="utf-8")
    emit((OUT_DIR / "phase21a_result.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())