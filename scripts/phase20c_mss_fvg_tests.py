#!/usr/bin/env python3
"""PHASE 20C — Shadow tests of MSS / FVG / CISD / session / HTF / stale-sweep.

Research only. No live logic or config changes. PATCH_APPLIED=NO.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from collections import defaultdict
from copy import deepcopy
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
OUT = ROOT / "logs" / "phase20c"
RESULT = ROOT / "logs" / "phase20c_mss_fvg_result.txt"
DETAIL = OUT / "model_metrics.json"

WARMUP = 500
SCAN_H0, SCAN_H1 = 7, 17
RECLAIM_H = 20
MSS_H = 20
FVG_WAIT = 12
CISD_H = 20
SIM_BARS = 24
STALE_BARS = 8
LEFT = RIGHT = 3
MIN_BODY_ATR = 0.60


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
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    if "atr" not in df.columns:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        df = df.copy()
        df["atr"] = tr.rolling(14, min_periods=14).mean()
    return df.sort_index()


def asian_by_day(df: pd.DataFrame, start_h: int, end_h: int) -> dict:
    dates = df.index.date
    hours = df.index.hour
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    buckets: dict = {}
    for i, (d, h) in enumerate(zip(dates, hours)):
        if start_h <= int(h) < end_h:
            buckets.setdefault(d, []).append(i)
    out = {}
    for d, idxs in buckets.items():
        if len(idxs) < 4:
            continue
        hi = float(np.max(highs[idxs]))
        lo = float(np.min(lows[idxs]))
        if hi > lo:
            out[d] = (hi, lo)
    return out


def last_confirmed_swing(highs: np.ndarray, lows: np.ndarray, i: int, kind: str) -> tuple[int | None, float | None]:
    end = i - RIGHT
    if end <= LEFT:
        return None, None
    for k in range(end, LEFT - 1, -1):
        a, b = k - LEFT, k + RIGHT + 1
        if a < 0 or b > i + 1:
            continue
        if kind == "high" and highs[k] >= np.max(highs[a:b]) - 1e-12:
            return k, float(highs[k])
        if kind == "low" and lows[k] <= np.min(lows[a:b]) + 1e-12:
            return k, float(lows[k])
    return None, None


def fvg_at(highs, lows, j: int, direction: int) -> tuple[float, float] | None:
    if j < 2:
        return None
    h2, l2 = float(highs[j - 2]), float(lows[j - 2])
    h0, l0 = float(highs[j]), float(lows[j])
    if direction > 0 and l0 > h2:
        return h2, l0
    if direction < 0 and h0 < l2:
        return h0, l2
    return None


def cisd_level(opens, closes, i: int, direction: int) -> float | None:
    """Open of consecutive delivery candles into the sweep bar."""
    if i < 1:
        return None
    if direction < 0:
        # up-closes into the high
        k = i
        while k >= 0 and float(closes[k]) > float(opens[k]):
            k -= 1
        first = k + 1
        if first > i:
            return None
        return float(opens[first])
    k = i
    while k >= 0 and float(closes[k]) < float(opens[k]):
        k -= 1
    first = k + 1
    if first > i:
        return None
    return float(opens[first])


def simulate(highs, lows, i: int, direction: int, entry: float, sl: float, tp: float) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    end = min(len(highs), i + 1 + SIM_BARS)
    for j in range(i + 1, end):
        hi, lo = float(highs[j]), float(lows[j])
        if direction > 0:
            hit_sl = lo <= sl
            hit_tp = hi >= tp
            if hit_sl and hit_tp:
                return -1.0
            if hit_sl:
                return -1.0
            if hit_tp:
                return round((tp - entry) / risk, 4)
        else:
            hit_sl = hi >= sl
            hit_tp = lo <= tp
            if hit_sl and hit_tp:
                return -1.0
            if hit_sl:
                return -1.0
            if hit_tp:
                return round((entry - tp) / risk, 4)
    return 0.0


def levels(direction: int, entry: float, atr: float, asian_hi: float, asian_lo: float, win_hi: float, win_lo: float, min_rr: float, sl_mult: float):
    pad = atr * sl_mult
    if direction < 0:
        sl = win_hi + pad
        risk = sl - entry
        if risk <= 0:
            return None
        tp = entry - max(entry - asian_lo, risk * min_rr)
        return sl, tp, risk
    sl = win_lo - pad
    risk = entry - sl
    if risk <= 0:
        return None
    tp = entry + max(asian_hi - entry, risk * min_rr)
    return sl, tp, risk


def max_dd(rs: list[float]) -> float:
    if not rs:
        return 0.0
    eq = np.cumsum(np.asarray(rs, dtype=float))
    peak = np.maximum.accumulate(eq)
    return float((peak - eq).max()) if eq.size else 0.0


def metrics(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "wr": 0.0, "pf": 0.0, "expr": 0.0, "maxdd": 0.0, "net_r": 0.0, "wins": 0, "losses": 0}
    a = np.asarray(rs, dtype=float)
    wins = a[a > 0]
    losses = a[a < 0]
    gw, gl = float(wins.sum()) if wins.size else 0.0, float(abs(losses.sum())) if losses.size else 0.0
    pf = (gw / gl) if gl > 0 else (min(10.0, 1.0 + gw) if (gw > 0 and len(a) >= 5) else 0.0)
    return {
        "trades": int(len(a)),
        "wr": round(100.0 * float((a > 0).mean()), 2),
        "pf": round(min(float(pf), 99.0), 4),
        "expr": round(float(a.mean()), 4),
        "maxdd": round(max_dd(rs), 4),
        "net_r": round(float(a.sum()), 4),
        "wins": int((a > 0).sum()),
        "losses": int((a < 0).sum()),
    }


def htf_bias_series(df: pd.DataFrame) -> pd.Series:
    h4 = df["close"].resample("4h").last().dropna()
    ema = h4.ewm(span=20, adjust=False).mean()
    bias = pd.Series(np.where(h4 > ema, 1, -1), index=h4.index)
    return bias


def bias_at(bias: pd.Series, ts) -> int:
    prev = bias[bias.index < ts]
    if prev.empty:
        return 0
    return int(prev.iloc[-1])


def session_ok(hour: int, mode: str) -> bool:
    if mode == "any":
        return 7 <= hour < 17
    if mode == "london":
        return 7 <= hour < 10
    if mode == "ny_open":
        return 12 <= hour < 15
    if mode == "ny_live":
        return 10 <= hour < 17
    return True


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    asian_s = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_e = int(cfg.get("ASIAN_END_HOUR", 7))
    lookback_sw = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf_mult = float(cfg.get("SWEEP_BUFFER_ATR", 0.12))
    min_range_atr = float(cfg.get("MIN_RANGE_ATR", 0.2))
    min_rr = float(cfg.get("MIN_RR", 1.5))
    sl_mult = float(cfg.get("SL_ATR_MULT", 0.35))

    df = load_m5()
    emit("PHASE 20C bars=" + str(len(df)) + " " + str(df.index[0]) + " -> " + str(df.index[-1]))
    asian = asian_by_day(df, asian_s, asian_e)
    bias = htf_bias_series(df)

    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    opens = df["open"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    atr_a = df["atr"].to_numpy(dtype=np.float64)
    hours = df.index.hour.to_numpy()
    dates = df.index.date
    roll_hi = pd.Series(highs).rolling(lookback_sw, min_periods=1).max().to_numpy()
    roll_lo = pd.Series(lows).rolling(lookback_sw, min_periods=1).min().to_numpy()
    n = len(df)

    buckets: dict[str, list[float]] = defaultdict(list)
    meta_rows: list[dict[str, Any]] = []

    prev_hi = prev_lo = False
    prev_day = None
    n_sweep = 0
    n_reclaim = 0

    for i in range(WARMUP, n - SIM_BARS - FVG_WAIT - 2):
        day = dates[i]
        h = int(hours[i])
        if day != prev_day:
            prev_hi = prev_lo = False
            prev_day = day
        if not (SCAN_H0 <= h < SCAN_H1):
            prev_hi = prev_lo = False
            continue
        bounds = asian.get(day)
        if bounds is None:
            continue
        asian_hi, asian_lo = bounds
        atr = float(atr_a[i]) if np.isfinite(atr_a[i]) and atr_a[i] > 0 else float(closes[i]) * 0.001
        if atr <= 0 or (asian_hi - asian_lo) < atr * min_range_atr:
            continue
        buf = atr * buf_mult
        swept_hi = float(roll_hi[i]) > asian_hi + buf
        swept_lo = float(roll_lo[i]) < asian_lo - buf
        onsets = []
        if swept_hi and not prev_hi:
            onsets.append("high")
        if swept_lo and not prev_lo:
            onsets.append("low")
        prev_hi, prev_lo = swept_hi, swept_lo
        if not onsets:
            continue

        for side in onsets:
            n_sweep += 1
            direction = -1 if side == "high" else 1
            win_hi = float(roll_hi[i])
            win_lo = float(roll_lo[i])
            reclaim_i = None
            for k in range(1, RECLAIM_H + 1):
                j = i + k
                if j >= n:
                    break
                cl = float(closes[j])
                if asian_lo < cl < asian_hi:
                    if direction < 0 and cl < asian_hi:
                        reclaim_i = j
                        break
                    if direction > 0 and cl > asian_lo:
                        reclaim_i = j
                        break
            if reclaim_i is None:
                continue
            n_reclaim += 1

            kind = "low" if direction < 0 else "high"
            sw_i, sw_px = last_confirmed_swing(highs, lows, i, kind)
            mss_i = None
            disp_ok = False
            search_from = reclaim_i
            search_to = min(n - 1, i + MSS_H)
            if sw_px is not None:
                for j in range(search_from, search_to + 1):
                    cl = float(closes[j])
                    hit = (cl < sw_px) if direction < 0 else (cl > sw_px)
                    if not hit:
                        continue
                    mss_i = j
                    body = abs(float(closes[j]) - float(opens[j]))
                    a = float(atr_a[j]) if np.isfinite(atr_a[j]) and atr_a[j] > 0 else atr
                    disp_ok = (body / a) >= MIN_BODY_ATR
                    if direction < 0:
                        disp_ok = disp_ok and float(closes[j]) < float(opens[j])
                    else:
                        disp_ok = disp_ok and float(closes[j]) > float(opens[j])
                    break

            cisd_i = None
            lvl = cisd_level(opens, closes, i, direction)
            if lvl is not None:
                for j in range(reclaim_i, min(n - 1, i + CISD_H) + 1):
                    cl = float(closes[j])
                    hit = (cl < lvl) if direction < 0 else (cl > lvl)
                    if hit:
                        cisd_i = j
                        break

            fvg_i = None
            if mss_i is not None:
                gap = None
                for jj in range(mss_i, min(n - 1, mss_i + 3) + 1):
                    gap = fvg_at(highs, lows, jj, direction)
                    if gap is not None:
                        gap_bar = jj
                        break
                if gap is not None:
                    bot, top = (gap[0], gap[1]) if gap[0] < gap[1] else (gap[1], gap[0])
                    for j in range(gap_bar + 1, min(n - 1, gap_bar + FVG_WAIT) + 1):
                        if float(highs[j]) >= bot and float(lows[j]) <= top:
                            fvg_i = j
                            break

            ts_rec = df.index[reclaim_i]
            h_rec = int(hours[reclaim_i])
            htf = bias_at(bias, ts_rec)
            htf_ok = htf == direction
            stale_ok = mss_i is not None and (mss_i - reclaim_i) <= STALE_BARS

            def take(model: str, entry_i: int | None, extra_ok: bool = True) -> None:
                if entry_i is None or not extra_ok:
                    return
                if entry_i >= n - 2:
                    return
                entry = float(closes[entry_i])
                a = float(atr_a[entry_i]) if np.isfinite(atr_a[entry_i]) and atr_a[entry_i] > 0 else atr
                lv = levels(direction, entry, a, asian_hi, asian_lo, win_hi, win_lo, min_rr, sl_mult)
                if lv is None:
                    return
                sl, tp, risk = lv
                rr = abs(tp - entry) / risk
                if rr < min_rr * 0.95:
                    return
                r = simulate(highs, lows, entry_i, direction, entry, sl, tp)
                buckets[model].append(float(r))

            take("A_reclaim_any", reclaim_i)
            take("A_reclaim_london", reclaim_i, session_ok(h_rec, "london"))
            take("A_reclaim_ny_live", reclaim_i, session_ok(h_rec, "ny_live"))
            take("A_reclaim_ny_open", reclaim_i, session_ok(h_rec, "ny_open"))

            take("B_mss", mss_i)
            take("B_mss_disp", mss_i, disp_ok)
            take("B_mss_stale8", mss_i, stale_ok)
            take("B_mss_htf", mss_i, htf_ok)
            take("B_mss_london", mss_i, session_ok(int(hours[mss_i]) if mss_i is not None else h_rec, "london"))
            take("B_mss_ny_open", mss_i, session_ok(int(hours[mss_i]) if mss_i is not None else h_rec, "ny_open"))
            take("B_mss_disp_london", mss_i, bool(disp_ok and session_ok(int(hours[mss_i]) if mss_i is not None else h_rec, "london")))

            take("C_fvg", fvg_i)
            take("C_fvg_disp", fvg_i, disp_ok)
            take("C_fvg_htf", fvg_i, htf_ok)
            take("C_fvg_london", fvg_i, session_ok(int(hours[fvg_i]) if fvg_i is not None else h_rec, "london"))
            take("C_fvg_ny_open", fvg_i, session_ok(int(hours[fvg_i]) if fvg_i is not None else h_rec, "ny_open"))
            take("C_fvg_disp_london", fvg_i, bool(disp_ok and session_ok(int(hours[fvg_i]) if fvg_i is not None else h_rec, "london")))
            take("C_fvg_stale8", fvg_i, stale_ok)

            take("D_cisd", cisd_i)
            take("D_cisd_london", cisd_i, session_ok(int(hours[cisd_i]) if cisd_i is not None else h_rec, "london"))

            meta_rows.append({
                "sweep_i": int(i),
                "side": side,
                "reclaim_i": int(reclaim_i),
                "mss_i": None if mss_i is None else int(mss_i),
                "fvg_i": None if fvg_i is None else int(fvg_i),
                "cisd_i": None if cisd_i is None else int(cisd_i),
                "disp_ok": bool(disp_ok),
                "htf_ok": bool(htf_ok),
                "stale_ok": bool(stale_ok),
            })

    table = {k: metrics(v) for k, v in buckets.items()}
    ranked = sorted(
        table.items(),
        key=lambda kv: (
            1 if kv[1]["trades"] >= 20 else 0,
            kv[1]["pf"],
            kv[1]["expr"],
            kv[1]["trades"],
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else ("none", metrics([]))
    cert = [k for k, m in ranked if m["trades"] >= 20 and m["pf"] >= 1.25 and m["expr"] > 0]

    labels = {
        "A_reclaim_any": "A current reclaim (07-17)",
        "A_reclaim_london": "A reclaim London 07-10",
        "A_reclaim_ny_live": "A reclaim NY live 10-17",
        "A_reclaim_ny_open": "A reclaim NY open 12-15",
        "B_mss": "B MSS after reclaim",
        "B_mss_disp": "B MSS + displacement",
        "B_mss_stale8": "B MSS within 8 bars",
        "B_mss_htf": "B MSS + H4 bias",
        "B_mss_london": "B MSS London",
        "B_mss_ny_open": "B MSS NY open",
        "B_mss_disp_london": "B MSS+disp London",
        "C_fvg": "C FVG retrace after MSS",
        "C_fvg_disp": "C FVG + displacement",
        "C_fvg_htf": "C FVG + H4 bias",
        "C_fvg_london": "C FVG London",
        "C_fvg_ny_open": "C FVG NY open",
        "C_fvg_disp_london": "C FVG+disp London",
        "C_fvg_stale8": "C FVG + stale<=8",
        "D_cisd": "D CISD after reclaim",
        "D_cisd_london": "D CISD London",
    }

    lines = [
        "PHASE 20C — MSS / FVG / CISD / session / HTF shadow tests",
        "MODE=SHADOW_ONLY",
        "USE_ML_KERNEL=false",
        "PATCH_APPLIED=NO",
        "LIVE_LOGIC_CHANGED=NO",
        "CONFIG_CHANGED=NO",
        f"DATA={CACHE.name}",
        f"RANGE={df.index[0]} -> {df.index[-1]}",
        f"UNIQUE_SWEEPS={n_sweep}",
        f"RECLAIMED={n_reclaim}",
        "SIM_BARS=24  MIN_RR=1.5  SL_ATR=0.35",
        "MSS=body close beyond last confirmed swing (L/R=3) frozen at sweep",
        "DISP=body/ATR>=0.60 in trade direction",
        "FVG=3-candle gap on/after MSS, entry on first tap",
        "STALE=MSS within 8 bars of reclaim",
        "HTF=last closed H4 close vs EMA20",
        "",
        f"{'Model':<28} {'Trades':>7} {'WR%':>7} {'PF':>8} {'ExpR':>8} {'MaxDD':>8} {'NetR':>8}",
        "-" * 80,
    ]
    order = list(labels.keys())
    for k in order:
        m = table.get(k, metrics([]))
        lines.append(
            f"{labels[k]:<28} {m['trades']:>7} {m['wr']:>7.2f} {m['pf']:>8.4f} {m['expr']:>8.4f} {m['maxdd']:>8.4f} {m['net_r']:>8.4f}"
        )
    lines += [
        "",
        "RANKED_BY_PF (min 20 trades first):",
    ]
    for k, m in ranked:
        star = " <-- BEST" if k == best[0] else ""
        cert_s = " CERT" if k in cert else ""
        lines.append(
            f"  {labels.get(k, k):<28} trades={m['trades']:<5} PF={m['pf']:<7} ExpR={m['expr']:<8}{star}{cert_s}"
        )
    lines += [
        "",
        f"BEST_MODEL={best[0]}",
        f"BEST_LABEL={labels.get(best[0], best[0])}",
        f"BEST_PF={best[1]['pf']}",
        f"BEST_EXPECTANCY_R={best[1]['expr']}",
        f"BEST_TRADES={best[1]['trades']}",
        f"ANY_CERTIFIED_PF_GE_1_25={'YES' if cert else 'NO'}",
        f"CERTIFIED_MODELS={','.join(cert) if cert else 'none'}",
        "SAFE_LIVE_PATCH=NO",
        "PATCH_APPLIED=NO",
        "",
        "PHASE_20C_RESULT",
        f"SWEEPS={n_sweep}",
        f"RECLAIMS={n_reclaim}",
        f"BEST_MODEL={best[0]}",
        f"BEST_PF={best[1]['pf']}",
        f"BEST_EXPECTANCY_R={best[1]['expr']}",
        f"BEST_TRADES={best[1]['trades']}",
        f"BEATS_CURRENT_RECLAIM={'YES' if best[0] != 'A_reclaim_ny_live' and best[1]['pf'] > table.get('A_reclaim_ny_live', metrics([]))['pf'] else 'NO'}",
        f"ANY_PF_ABOVE_1_25={'YES' if cert else 'NO'}",
        "PATCH_APPLIED=NO",
    ]
    text = "\n".join(lines) + "\n"
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(text, encoding="utf-8")
    DETAIL.write_text(json.dumps({"n_sweep": n_sweep, "n_reclaim": n_reclaim, "models": table, "best": best[0]}, indent=2), encoding="utf-8")
    emit(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())