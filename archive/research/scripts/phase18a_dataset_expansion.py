#!/usr/bin/env python3
"""PHASE 18A — ML Dataset Expansion Pipeline (RESEARCH ONLY).

Collects all NY-session PA sweep setups from 180d XAUUSD M5, labels
TP/SL/timeout within 24 bars, enriches MFE/MAE, splits by regime, and
joins live quality telemetry.

Does not enable live ML. Does not change live.py or execution flags.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
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

SYMBOL = "XAUUSD"
HOLDING_BARS = 24
LOOKBACK = 280
WARMUP = 500

CACHE_PATH = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
OUT_DIR = ROOT / "data" / "ml" / "research" / "phase18a"
RAW_PATH = OUT_DIR / "raw_setups_180d.parquet"
LABELED_PATH = OUT_DIR / "labeled_setups_180d.parquet"
REPORT_PATH = ROOT / "logs" / "phase18a_dataset_expansion_result.txt"
DECISIONS_PATH = ROOT / "logs" / "phase17a" / "pa_live_decisions.jsonl"
HOLD_PATH = ROOT / "logs" / "engines" / "pa_hold_reasons.jsonl"


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5() -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    if not CACHE_PATH.is_file():
        raise FileNotFoundError(f"Missing cache: {CACHE_PATH}")
    df = pd.read_parquet(CACHE_PATH)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df["volume"] = df["tick_volume"]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    df = df[keep].dropna().sort_index()
    return prepare_indicator_frame(df)


def adx_series(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.rolling(period).mean()
    return adx.fillna(0.0).to_numpy(dtype=np.float64)


def atr_pct_series(atr: np.ndarray, lookback: int = 252) -> np.ndarray:
    n = len(atr)
    out = np.full(n, 50.0, dtype=np.float64)
    for i in range(lookback, n):
        w = atr[i - lookback + 1 : i + 1]
        cur = atr[i]
        if np.isfinite(cur) and cur > 0:
            finite = w[np.isfinite(w)]
            if len(finite):
                out[i] = float((finite <= cur).mean() * 100.0)
    return out


def asian_range_by_day(df: pd.DataFrame, start_hour: int, end_hour: int) -> dict[Any, tuple[float, float]]:
    dates = df.index.date
    hours = df.index.hour
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    buckets: dict[Any, list[int]] = {}
    for i, (d, h) in enumerate(zip(dates, hours)):
        if start_hour <= int(h) < end_hour:
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


def session_name(hour: int) -> str:
    if 0 <= hour < 7:
        return "ASIAN"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "NY"
    if 17 <= hour < 21:
        return "NY_LATE"
    return "OFF"


def synthesize_levels(
    *,
    direction: int,
    price: float,
    atr: float,
    asian_hi: float,
    asian_lo: float,
    win_high: float,
    win_low: float,
    min_rr: float,
    sl_atr_mult: float,
) -> tuple[float, float, float] | None:
    sl_pad = atr * sl_atr_mult
    if direction < 0:
        sl = win_high + sl_pad
        risk = sl - price
        if risk <= 0:
            return None
        tp = price - max(max(price - asian_lo, 0.0), risk * min_rr)
    else:
        sl = win_low - sl_pad
        risk = price - sl
        if risk <= 0:
            return None
        tp = price + max(max(asian_hi - price, 0.0), risk * min_rr)
    if abs(tp - price) / risk < min_rr * 0.50:
        return None
    return float(sl), float(tp), float(risk)


def path_enrich(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    i: int,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
    horizon: int,
) -> dict[str, Any]:
    risk = abs(entry - sl)
    n = len(highs)
    start = i + 1
    end = min(n, i + 1 + horizon)
    if risk <= 0 or start >= n:
        return {
            "label": -1,
            "tp_hit": False,
            "sl_hit": False,
            "timeout": True,
            "exit_reason": "invalid_levels",
            "bars_to_outcome": None,
            "mfe_r": 0.0,
            "mae_r": 0.0,
            "time_to_mfe": None,
            "time_to_mae": None,
            "close_position_at_+1R": False,
            "retrace_after_+1R": 0.0,
            "realized_r_multiple": 0.0,
            "holding_window_bars": horizon,
        }

    mfe = mae = 0.0
    t_mfe = t_mae = None
    label = -1
    tp_hit = sl_hit = False
    exit_reason = "timeout"
    bars_to = end - i
    hit_1r_ext = False
    t_1r = None
    peak_r_after_1r = 1.0
    close_at_1r = False
    retrace = 0.0

    for j in range(start, end):
        hi = float(highs[j])
        lo = float(lows[j])
        cl = float(closes[j])
        bars = j - i
        if direction > 0:
            fav = (hi - entry) / risk
            adv = (entry - lo) / risk
            close_r = (cl - entry) / risk
            bar_sl = lo <= sl
            bar_tp = hi >= tp
        else:
            fav = (entry - lo) / risk
            adv = (hi - entry) / risk
            close_r = (entry - cl) / risk
            bar_sl = hi >= sl
            bar_tp = lo <= tp

        if fav >= mfe:
            mfe = fav
            t_mfe = bars
        if adv >= mae:
            mae = adv
            t_mae = bars
        if close_r >= 1.0:
            close_at_1r = True
        if (not hit_1r_ext) and fav >= 1.0:
            hit_1r_ext = True
            t_1r = bars
            peak_r_after_1r = fav
        if hit_1r_ext:
            peak_r_after_1r = max(peak_r_after_1r, fav)
            retrace = max(retrace, peak_r_after_1r - close_r)

        if bar_sl and bar_tp:
            label, sl_hit, tp_hit, exit_reason, bars_to = 0, True, False, "sl", bars
            break
        if bar_sl:
            label, sl_hit, tp_hit, exit_reason, bars_to = 0, True, False, "sl", bars
            break
        if bar_tp:
            label, sl_hit, tp_hit, exit_reason, bars_to = 1, False, True, "tp", bars
            break

    timeout = label == -1
    if exit_reason == "tp":
        realized = abs(tp - entry) / risk
    elif exit_reason == "sl":
        realized = -1.0
    else:
        realized = 0.0

    return {
        "label": int(label),
        "tp_hit": bool(tp_hit),
        "sl_hit": bool(sl_hit),
        "timeout": bool(timeout),
        "exit_reason": exit_reason,
        "bars_to_outcome": int(bars_to) if bars_to is not None else None,
        "mfe_r": round(float(mfe), 4),
        "mae_r": round(float(mae), 4),
        "time_to_mfe": int(t_mfe) if t_mfe is not None else None,
        "time_to_mae": int(t_mae) if t_mae is not None else None,
        "close_position_at_+1R": bool(close_at_1r),
        "retrace_after_+1R": round(float(retrace), 4),
        "realized_r_multiple": round(float(realized), 4),
        "holding_window_bars": horizon,
        "hit_plus_1r_extreme": bool(hit_1r_ext),
        "bars_to_plus_1r": int(t_1r) if t_1r is not None else None,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def telemetry_index(rows: list[dict[str, Any]], prefix: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rec in rows:
        ts = rec.get("timestamp")
        if not ts:
            continue
        try:
            key = pd.Timestamp(ts, tz="UTC").floor("5min").isoformat()
        except Exception:
            continue
        mapped = {
            f"{prefix}event": rec.get("event"),
            f"{prefix}reject_reason": rec.get("reject_reason"),
            f"{prefix}session_ok": rec.get("session_ok"),
            f"{prefix}sweep": rec.get("sweep_detected"),
            f"{prefix}reclaim": rec.get("reclaim_detected", rec.get("reclaim_ok")),
            f"{prefix}bos": rec.get("bos_detected", rec.get("bos_ok")),
            f"{prefix}fvg": rec.get("fvg_detected", rec.get("fvg_ok")),
            f"{prefix}confidence": rec.get("confidence_score", rec.get("confidence")),
            f"{prefix}quality_score": rec.get("quality_score"),
        }
        out[key] = mapped
    return out


def collect_raw(df: pd.DataFrame) -> pd.DataFrame:
    from copy import deepcopy

    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies.m5_london_sweep import (
        _in_entry_window,
        evaluate_m5_london_sweep,
    )
    from tradingbot.domain.market_filters import compute_adx
    from tradingbot.domain.pa_hardening import (
        apply_setup_hardening,
        compute_quality_score,
        confirm_fvg_fill,
        detect_bos_continuation,
        session_range_breakout_stats,
    )
    from tradingbot.domain.price_action import PriceActionSetup, SetupType, enrich_price_action
    from tradingbot.ml.feature_store import classify_regime
    from tradingbot.research.displacement_intelligence import compute_displacement_score
    from tradingbot.research.setup_quality_score import compute_setup_score

    cfg = deepcopy(get_price_action_config(SYMBOL, "M5"))
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))
    asian_s = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_e = int(cfg.get("ASIAN_END_HOUR", 7))
    lookback_sw = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf_mult = float(cfg.get("SWEEP_BUFFER_ATR", 0.12))
    min_range_atr = float(cfg.get("MIN_RANGE_ATR", 0.2))
    min_rr = float(cfg.get("MIN_RR", 1.5))
    sl_atr_mult = float(cfg.get("SL_ATR_MULT", 0.35))

    emit(f"TASK 1 — collect PA setups 180d | bars={len(df)} window={ny_s}-{ny_e}")

    asian = asian_range_by_day(df, asian_s, asian_e)
    adx_arr = adx_series(df)
    atr_arr = df["atr"].to_numpy(dtype=np.float64) if "atr" in df.columns else np.full(len(df), np.nan)
    if not np.isfinite(atr_arr).any():
        tr = (df["high"] - df["low"]).abs()
        atr_arr = tr.rolling(14, min_periods=1).mean().to_numpy(dtype=np.float64)
        df = df.copy()
        df["atr"] = atr_arr
    atrp_arr = atr_pct_series(atr_arr)

    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    hours = df.index.hour.to_numpy()
    dates = df.index.date

    roll_hi = pd.Series(highs).rolling(lookback_sw, min_periods=1).max().to_numpy()
    roll_lo = pd.Series(lows).rolling(lookback_sw, min_periods=1).min().to_numpy()

    rows: list[dict[str, Any]] = []
    scanned = 0
    n = len(df)
    for i in range(WARMUP, n):
        h = int(hours[i])
        if not (ny_s <= h < ny_e):
            continue
        scanned += 1
        if scanned % 2000 == 0:
            emit(f"  scan progress ny_bars={scanned} setups={len(rows)}")

        ts = df.index[i]
        ts_py = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else pd.Timestamp(ts).to_pydatetime()
        if ts_py.tzinfo is None:
            ts_py = ts_py.replace(tzinfo=timezone.utc)

        bounds = asian.get(dates[i])
        if bounds is None:
            continue
        asian_hi, asian_lo = bounds
        atr = float(atr_arr[i]) if np.isfinite(atr_arr[i]) and atr_arr[i] > 0 else float(closes[i]) * 0.001
        if atr <= 0:
            continue
        if (asian_hi - asian_lo) < atr * min_range_atr:
            continue

        buf = atr * buf_mult
        win_high = float(roll_hi[i])
        win_low = float(roll_lo[i])
        swept_hi = win_high > asian_hi + buf
        swept_lo = win_low < asian_lo - buf
        if not (swept_hi or swept_lo):
            continue

        price = float(closes[i])
        inside = asian_lo < price < asian_hi
        if swept_hi and (not swept_lo or price >= (asian_hi + asian_lo) / 2.0):
            direction = -1
            side = "high"
        else:
            direction = 1
            side = "low"
        reclaim = bool(swept_hi and inside and price < asian_hi) or bool(
            swept_lo and inside and price > asian_lo
        )

        levels = synthesize_levels(
            direction=direction,
            price=price,
            atr=atr,
            asian_hi=asian_hi,
            asian_lo=asian_lo,
            win_high=win_high,
            win_low=win_low,
            min_rr=min_rr,
            sl_atr_mult=sl_atr_mult,
        )
        if levels is None:
            continue
        sl, tp, risk = levels
        rr_target = abs(tp - price) / risk

        tail_start = max(0, i - LOOKBACK)
        window = df.iloc[tail_start : i + 1]
        wi = len(window) - 1
        enriched = enrich_price_action(window, cfg, at_index=wi)
        breaks = enriched.attrs.get("pa_breaks", []) or []
        fvgs = enriched.attrs.get("pa_fvgs", []) or []
        bos = detect_bos_continuation(breaks, wi, direction)
        fvg = confirm_fvg_fill(fvgs, price=price, direction=direction, i=wi)
        sess_stats = session_range_breakout_stats(enriched, wi, cfg)
        session_breakout = bool(sess_stats.get("breakout"))

        setup_pa = PriceActionSetup(
            direction=direction,
            setup=SetupType.LIQUIDITY_SWEEP,
            entry=price,
            stop_loss=sl,
            take_profit=tp,
            confidence=round(min(0.92, 0.55 + min(rr_target, 3.0) * 0.08), 3),
            confluence=3.2,
            metadata={"strategy_mode": "m5_london_sweep", "sweep_side": side, "rr": round(rr_target, 2)},
        )
        quality = compute_quality_score(
            setup=setup_pa,
            bos_confirmed=bool(bos),
            fvg_confirmed=bool(fvg),
            liquidity_sweep=True,
            session_breakout=session_breakout,
            confluence=3.2,
        )

        live_setup = None
        if reclaim and _in_entry_window(enriched, wi, cfg):
            live_setup = evaluate_m5_london_sweep(enriched, wi, cfg)
            if live_setup is not None:
                hardened = apply_setup_hardening(enriched, wi, cfg, deepcopy(live_setup), timeframe="M5")
            else:
                hardened = None
        else:
            hardened = None

        disp = compute_displacement_score(df, i, direction=direction)
        adx_i = float(adx_arr[i]) if np.isfinite(adx_arr[i]) else compute_adx(df.iloc[: i + 1])
        atr_pct = float(atrp_arr[i]) if np.isfinite(atrp_arr[i]) else 50.0
        regime = classify_regime(adx_i, atr_pct)

        try:
            inst = compute_setup_score(
                enriched,
                wi,
                direction=direction,
                price=price,
                htf_bias=0,
                asian_hi=asian_hi,
                asian_lo=asian_lo,
                sweep_side=side,
            )
            research_quality = float(inst.total)
        except Exception:
            research_quality = float(quality)

        rows.append(
            {
                "setup_id": f"{ts_py.isoformat()}|{direction}|{round(price, 2)}",
                "timestamp_utc": ts_py.isoformat(),
                "bar_index": int(i),
                "timeframe": "M5",
                "symbol": SYMBOL,
                "direction": "BUY" if direction > 0 else "SELL",
                "direction_int": int(direction),
                "entry_price": round(price, 5),
                "stop_price": round(sl, 5),
                "tp_price": round(tp, 5),
                "rr_target": round(float(rr_target), 4),
                "sweep": True,
                "sweep_side": side,
                "reclaim": bool(reclaim),
                "bos": bool(bos),
                "fvg": bool(fvg),
                "session": session_name(h),
                "session_hour": h,
                "quality_score": int(quality),
                "research_quality_score": round(research_quality, 2),
                "displacement_score": float(disp.total),
                "body_atr": float(disp.features.body_atr),
                "range_expansion": float(disp.features.range_expansion),
                "fvg_size_atr": float(disp.features.fvg_size_atr),
                "follow_through_2": float(disp.features.follow_through_2),
                "displacement_velocity": float(disp.features.displacement_velocity),
                "close_near_extreme": float(disp.features.close_near_extreme),
                "regime": regime,
                "adx": round(adx_i, 4),
                "atr_pct": round(atr_pct, 4),
                "atr": round(atr, 5),
                "asian_high": round(asian_hi, 5),
                "asian_low": round(asian_lo, 5),
                "session_breakout": bool(session_breakout),
                "live_eligible": hardened is not None,
                "confidence": float(setup_pa.confidence),
                "source_window_days": 180,
            }
        )

    raw = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(RAW_PATH, index=False)
    emit(f"Saved raw: {RAW_PATH} rows={len(raw)}")
    if not raw.empty:
        emit(f"  reclaim={int(raw['reclaim'].sum())} bos={int(raw['bos'].sum())} fvg={int(raw['fvg'].sum())}")
        emit(f"  live_eligible={int(raw['live_eligible'].sum())}")
        emit(f"  regime={raw['regime'].value_counts().to_dict()}")
    return raw


def label_and_enrich(raw: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    emit(f"TASK 2/3 — triple outcome + MFE/MAE | horizon={HOLDING_BARS}")
    if raw.empty:
        return raw
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    extra: list[dict[str, Any]] = []
    n = len(raw)
    for k, row in enumerate(raw.itertuples(index=False), start=1):
        if k % 2000 == 0:
            emit(f"  label progress {k}/{n}")
        info = path_enrich(
            highs,
            lows,
            closes,
            int(row.bar_index),
            int(row.direction_int),
            float(row.entry_price),
            float(row.stop_price),
            float(row.tp_price),
            HOLDING_BARS,
        )
        extra.append(info)
    labeled = pd.concat([raw.reset_index(drop=True), pd.DataFrame(extra)], axis=1)
    emit(f"  labels={labeled['label'].value_counts().to_dict()}")
    return labeled


def join_telemetry(labeled: pd.DataFrame) -> pd.DataFrame:
    emit("TASK 5 — join quality telemetry")
    dec = telemetry_index(load_jsonl(DECISIONS_PATH), "tel_dec_")
    hold = telemetry_index(load_jsonl(HOLD_PATH), "tel_hold_")
    emit(f"  decisions_keys={len(dec)} hold_keys={len(hold)}")
    if labeled.empty:
        return labeled

    keys = []
    for ts in labeled["timestamp_utc"]:
        try:
            keys.append(pd.Timestamp(ts, tz="UTC").floor("5min").isoformat())
        except Exception:
            keys.append("")
    labeled = labeled.copy()
    labeled["telemetry_key"] = keys
    labeled["telemetry_matched"] = False

    tel_cols = [
        "tel_dec_event",
        "tel_dec_reject_reason",
        "tel_dec_session_ok",
        "tel_dec_sweep",
        "tel_dec_reclaim",
        "tel_dec_bos",
        "tel_dec_fvg",
        "tel_dec_confidence",
        "tel_dec_quality_score",
        "tel_hold_event",
        "tel_hold_reject_reason",
        "tel_hold_session_ok",
        "tel_hold_sweep",
        "tel_hold_reclaim",
        "tel_hold_bos",
        "tel_hold_fvg",
        "tel_hold_confidence",
        "tel_hold_quality_score",
    ]
    for c in tel_cols:
        labeled[c] = None

    matched = 0
    for i, key in enumerate(labeled["telemetry_key"]):
        hit = False
        if key in dec:
            for k, v in dec[key].items():
                labeled.at[i, k] = v
            hit = True
        if key in hold:
            for k, v in hold[key].items():
                labeled.at[i, k] = v
            hit = True
        if hit:
            labeled.at[i, "telemetry_matched"] = True
            matched += 1
    emit(f"  telemetry_matched={matched}/{len(labeled)}")
    return labeled


def top_success_features(labeled: pd.DataFrame) -> list[tuple[str, float, float, float]]:
    """Rank entry-time features by TP-rate lift (label==1 vs rest)."""
    if labeled.empty or "label" not in labeled.columns:
        return []
    y = labeled["label"].astype(int) == 1
    base = float(y.mean()) if len(y) else 0.0
    if base <= 0:
        return []

    candidates: list[tuple[str, pd.Series]] = []
    for col in ("reclaim", "bos", "fvg", "session_breakout", "live_eligible", "close_position_at_+1R"):
        if col in labeled.columns:
            candidates.append((col, labeled[col].astype(bool)))
    if "quality_score" in labeled.columns:
        candidates.append(("quality_score>=55", labeled["quality_score"].astype(float) >= 55))
        candidates.append(("quality_score>=70", labeled["quality_score"].astype(float) >= 70))
    if "displacement_score" in labeled.columns:
        candidates.append(("displacement_score>=50", labeled["displacement_score"].astype(float) >= 50))
        candidates.append(("displacement_score>=60", labeled["displacement_score"].astype(float) >= 60))
    if "session" in labeled.columns:
        candidates.append(("session=NY", labeled["session"] == "NY"))
        candidates.append(("session=LONDON", labeled["session"] == "LONDON"))
    if "regime" in labeled.columns:
        candidates.append(("regime=TREND", labeled["regime"] == "TREND"))
        candidates.append(("regime=EXPANSION", labeled["regime"] == "EXPANSION"))
        candidates.append(("regime=RANGING", labeled["regime"] == "RANGING"))
    if "direction" in labeled.columns:
        candidates.append(("direction=BUY", labeled["direction"] == "BUY"))
        candidates.append(("direction=SELL", labeled["direction"] == "SELL"))
    if "body_atr" in labeled.columns:
        med = float(labeled["body_atr"].median())
        candidates.append((f"body_atr>={med:.3f}", labeled["body_atr"].astype(float) >= med))
    if "range_expansion" in labeled.columns:
        med = float(labeled["range_expansion"].median())
        candidates.append((f"range_expansion>={med:.3f}", labeled["range_expansion"].astype(float) >= med))
    if "tel_dec_reclaim" in labeled.columns:
        mask = labeled["telemetry_matched"].astype(bool) if "telemetry_matched" in labeled.columns else pd.Series(False, index=labeled.index)
        if mask.any():
            rec = labeled["tel_dec_reclaim"].fillna(False).astype(bool)
            candidates.append(("telemetry_reclaim_ok", rec & mask))
            bos = labeled["tel_dec_bos"].fillna(False).astype(bool)
            candidates.append(("telemetry_bos_ok", bos & mask))

    ranked: list[tuple[str, float, float, float]] = []
    for name, mask in candidates:
        if name == "close_position_at_+1R":
            continue  # outcome-leaky
        on = mask.fillna(False).astype(bool)
        n_on = int(on.sum())
        if n_on < 30:
            continue
        rate = float(y[on].mean())
        lift = rate / base if base > 0 else 0.0
        ranked.append((name, rate, lift, float(n_on)))
    ranked.sort(key=lambda x: (x[2], x[1]), reverse=True)
    return ranked[:8]


def write_report(raw: pd.DataFrame, labeled: pd.DataFrame) -> None:
    n_raw = int(len(raw))
    n_lab = int(len(labeled))
    tp = int((labeled["label"] == 1).sum()) if n_lab else 0
    sl = int((labeled["label"] == 0).sum()) if n_lab else 0
    to = int((labeled["label"] == -1).sum()) if n_lab else 0
    trend = int((labeled["regime"] == "TREND").sum()) if n_lab else 0
    exp = int((labeled["regime"] == "EXPANSION").sum()) if n_lab else 0
    rng = int((labeled["regime"] == "RANGING").sum()) if n_lab else 0
    mean_mfe = float(labeled["mfe_r"].mean()) if n_lab else 0.0
    mean_mae = float(labeled["mae_r"].mean()) if n_lab else 0.0
    timeout_pct = (to / n_lab * 100.0) if n_lab else 100.0
    tops = top_success_features(labeled)
    while len(tops) < 5:
        tops.append(("n/a", 0.0, 0.0, 0.0))

    ready = (
        n_raw >= 8000
        and n_lab >= 5000
        and trend >= 500
        and exp >= 500
        and rng >= 500
        and timeout_pct < 30.0
    )

    lines = [
        "PHASE_18A_RESULT",
        "",
        f"RAW_SETUPS={n_raw}",
        f"LABELED_SAMPLES={n_lab}",
        f"TP_COUNT={tp}",
        f"SL_COUNT={sl}",
        f"TIMEOUT_COUNT={to}",
        "",
        f"TREND_SAMPLES={trend}",
        f"EXPANSION_SAMPLES={exp}",
        f"RANGING_SAMPLES={rng}",
        "",
        f"MEAN_MFE_R={mean_mfe:.4f}",
        f"MEAN_MAE_R={mean_mae:.4f}",
        "",
        "TOP_SUCCESS_FEATURES=",
    ]
    for i, (name, rate, lift, n_on) in enumerate(tops[:5], start=1):
        lines.append(f"{i}. {name} tp_rate={rate:.3f} lift={lift:.3f} n={int(n_on)}")
    lines += [
        "",
        f"DATASET_INSTITUTIONAL_READY={'YES' if ready else 'NO'}",
        "PATCH_APPLIED=NO",
        "",
        f"TIMEOUT_PCT={timeout_pct:.2f}",
        f"RECLAIM_COUNT={int(raw['reclaim'].sum()) if n_raw and 'reclaim' in raw.columns else 0}",
        f"BOS_COUNT={int(raw['bos'].sum()) if n_raw and 'bos' in raw.columns else 0}",
        f"FVG_COUNT={int(raw['fvg'].sum()) if n_raw and 'fvg' in raw.columns else 0}",
        f"LIVE_ELIGIBLE={int(raw['live_eligible'].sum()) if n_raw and 'live_eligible' in raw.columns else 0}",
        f"TELEMETRY_MATCHED={int(labeled['telemetry_matched'].sum()) if n_lab and 'telemetry_matched' in labeled.columns else 0}",
        "MODE=RESEARCH_ONLY",
        "LIVE_ML_ENABLED=NO",
        "LIVE_FLAGS_CHANGED=NO",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    emit(f"Wrote {REPORT_PATH}")
    emit("\n".join(lines))


def main() -> int:
    emit("PHASE 18A — ML Dataset Expansion (research only)")
    df = load_m5()
    emit(f"loaded {CACHE_PATH.name} bars={len(df)} start={df.index[0]} end={df.index[-1]}")
    raw = collect_raw(df)
    labeled = label_and_enrich(raw, df)
    labeled = join_telemetry(labeled)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labeled.to_parquet(LABELED_PATH, index=False)
    emit(f"Saved labeled: {LABELED_PATH} rows={len(labeled)}")
    write_report(raw, labeled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
