#!/usr/bin/env python3
"""PHASE 21D — join Meta rejects to 24-bar MFE outcomes (research; no live gating change)."""
from __future__ import annotations

import json
import os
import sys
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

from tradingbot.services.meta_false_negative import (
    FORWARD_BARS,
    classify_24_bar_outcome,
    summarize_outcomes,
)

LIVE_JSONL = ROOT / "logs" / "engines" / "meta_false_negative_candidates.jsonl"
RESEARCH_JSONL = ROOT / "logs" / "phase21d" / "research_fn.jsonl"
REPORT = ROOT / "logs" / "phase21d_meta_false_negative_report.txt"
CACHE = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"

SKIP_REGIMES = frozenset({"CRISIS", "VOLATILE"})
REGIME_MAP = {
    "STRONG_TREND_UP": 1.0,
    "STRONG_TREND_DOWN": -1.0,
    "RANGING": 0.0,
    "VOLATILE": 0.5,
    "CRISIS": -0.5,
}
MIN_RR = 1.5
SL_ATR = 0.35
MIN_RANGE = 0.2
SWEEP_LB = 12
SWEEP_ATR = 0.12
ATR_MIN, ATR_MAX = 12.0, 94.0
MAX_SPREAD = 15.0
BASE_SPREAD = 4.0
BASE_TH = 0.38


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_df() -> pd.DataFrame:
    df = pd.read_parquet(CACHE)
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


def precompute_asian(dates, hours, high, low, n, end_hour):
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


def collect_hour15(df: pd.DataFrame, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from tradingbot.domain.session_logic import variable_spread_pips

    n = len(df)
    hours = np.array([int(ts.hour) for ts in df.index])
    weekdays = np.array([int(ts.weekday()) for ts in df.index])
    dates = np.array([ts.date().isoformat() for ts in df.index])
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    adx = df["adx"].to_numpy(dtype=float) if "adx" in df.columns else np.zeros(n)
    atr_pct = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct = np.where(np.isnan(atr_pct), 50.0, atr_pct)
    regime = infer_regimes(df)
    ny_s = int(cfg.get("NY_ENTRY_START_UTC", cfg.get("NY_ENTRY_START_HOUR", 15)))
    ny_e = int(cfg.get("NY_ENTRY_END_UTC", cfg.get("NY_ENTRY_END_HOUR", 16)))
    asian_end = int(cfg.get("ASIAN_SESSION_END_UTC", cfg.get("ASIAN_END_HOUR", 8)))
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", SWEEP_LB))
    sweep_atr = float(cfg.get("SWEEP_BUFFER_ATR", SWEEP_ATR))
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    roll_hi = df["high"].rolling(lookback + 1, min_periods=1).max().to_numpy(dtype=float)
    roll_lo = df["low"].rolling(lookback + 1, min_periods=1).min().to_numpy(dtype=float)
    asian = precompute_asian(dates, hours, high, low, n, asian_end)
    cands: list[dict[str, Any]] = []
    for i in range(40, n - FORWARD_BARS - 1):
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
        ts = df.index[i]
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        cands.append(
            {
                "i": int(i),
                "timestamp": ts_s,
                "symbol": "XAUUSD_i",
                "direction": "BUY" if direction > 0 else "SELL",
                "dir": int(direction),
                "entry": round(price, 5),
                "stop_loss": round(float(sl), 5),
                "take_profit": round(float(tp), 5),
                "rr": round(rr, 2),
                "confidence": round(conf, 3),
                "regime": str(regime[i]),
                "features": {
                    "confidence": round(conf, 3),
                    "confluence": 3.2,
                    "rr": round(rr, 2),
                    "adx": float(adx[i]) if not np.isnan(adx[i]) else 0.0,
                    "atr_pct": float(atr_pct[i]),
                    "htf_bias": 0.0,
                    "hour_utc": float(hours[i]),
                    "weekday": float(weekdays[i]),
                    "direction": 1.0 if direction > 0 else -1.0,
                    "regime_code": REGIME_MAP.get(str(regime[i]), 0.0),
                    "spread_pips": float(sp),
                    "sl_atr_mult": SL_ATR,
                    "setup_code": 1.0,
                },
            }
        )
    return cands


def score_meta_rejects(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from tradingbot.ml.features.unified_feature_store import to_vector
    from tradingbot.services.meta_decision_log import setup_snapshot_id
    from tradingbot.services.meta_labeler import reload_meta_labeler

    meta = reload_meta_labeler()
    model = meta._models.get("M5")
    if model is None:
        raise RuntimeError("meta_labeler_m5.pkl missing")
    out: list[dict[str, Any]] = []
    for row in cands:
        if str(row.get("regime") or "") in SKIP_REGIMES:
            continue
        feats = dict(row["features"])
        vec = to_vector(feats)
        try:
            proba = model.predict_proba([vec])[0]
            score = float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception:
            continue
        th = float(meta.effective_threshold("M5", str(row["regime"]), BASE_TH))
        if score >= th:
            continue
        rec = {
            "timestamp": row["timestamp"],
            "symbol": row["symbol"],
            "direction": row["direction"],
            "meta_score": round(score, 4),
            "threshold": round(th, 4),
            "setup_snapshot_id": setup_snapshot_id(
                timestamp=row["timestamp"],
                symbol=row["symbol"],
                direction=row["direction"],
                entry=row["entry"],
                stop_loss=row["stop_loss"],
            ),
            "features": feats,
            "entry": row["entry"],
            "stop_loss": row["stop_loss"],
            "take_profit": row["take_profit"],
            "timeframe": "M5",
            "i": row["i"],
            "dir": row["dir"],
            "source": "research_hour15",
        }
        out.append(rec)
    return out


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def bar_index(df: pd.DataFrame, timestamp: str) -> int | None:
    try:
        t = pd.to_datetime(timestamp, utc=True)
    except Exception:
        return None
    loc = int(df.index.get_indexer([t], method="nearest")[0])
    if loc < 0:
        return None
    delta = abs((df.index[loc] - t).total_seconds())
    if delta > 300:
        return None
    return loc


def join_candidate(df: pd.DataFrame, high, low, n: int, rec: dict[str, Any]) -> dict[str, Any] | None:
    i = rec.get("i")
    if i is None:
        i = bar_index(df, str(rec.get("timestamp") or ""))
    if i is None:
        return None
    i = int(i)
    direction = rec.get("dir")
    if direction is None:
        d = str(rec.get("direction") or "").upper()
        direction = 1 if d == "BUY" else (-1 if d == "SELL" else 0)
    entry = rec.get("entry")
    sl = rec.get("stop_loss") or rec.get("sl")
    if entry is None or sl is None or int(direction) == 0:
        return None
    classified = classify_24_bar_outcome(
        high, low, i, int(direction), float(entry), float(sl), n, FORWARD_BARS
    )
    out = dict(rec)
    out.update(classified)
    out["i"] = i
    out["dir"] = int(direction)
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            dump = {k: v for k, v in row.items() if k not in ("dir",)}
            f.write(json.dumps(dump, ensure_ascii=False, default=str) + "\n")


def format_report(*, live_n: int, research_n: int, joined_n: int, stats: dict[str, Any], patch: str) -> str:
    return "\n".join(
        [
            "PHASE_21D_META_FALSE_NEGATIVE",
            f"LIVE_CANDIDATES={live_n}",
            f"RESEARCH_CANDIDATES={research_n}",
            f"JOINED={joined_n}",
            f"FORWARD_BARS={FORWARD_BARS}",
            "",
            "PHASE_21D_RESULT",
            "",
            f"CANDIDATES={stats['candidates']}",
            f"BECAME_+1R={stats['became_1r']}",
            f"BECAME_+1.5R={stats['became_15r']}",
            f"SL_FIRST={stats['sl_first']}",
            f"TIMEOUT={stats['timeout']}",
            "",
            f"FALSE_NEGATIVE_RATE={stats['false_negative_rate']}",
            f"POTENTIAL_RECOVERABLE_R={stats['potential_recoverable_r']}",
            "",
            f"PATCH_APPLIED={patch}",
            "",
        ]
    )


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config

    df = load_df()
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    emit(f"DF bars={n} {df.index.min()} -> {df.index.max()}")

    live_rows = load_jsonl(LIVE_JSONL)
    emit(f"LIVE jsonl={len(live_rows)}")

    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    emit("collect hour15 PA setups ...")
    raw = collect_hour15(df, cfg)
    emit(f"PA raw={len(raw)}")
    research = score_meta_rejects(raw)
    emit(f"research meta-rejects={len(research)}")
    write_jsonl(RESEARCH_JSONL, research)

    combined = list(research)
    seen = {r.get("setup_snapshot_id") for r in combined}
    for rec in live_rows:
        sid = rec.get("setup_snapshot_id")
        if sid and sid in seen:
            continue
        rec = dict(rec)
        rec["source"] = rec.get("source") or "live"
        combined.append(rec)
        if sid:
            seen.add(sid)

    joined: list[dict[str, Any]] = []
    unmatched = 0
    for rec in combined:
        hit = join_candidate(df, high, low, n, rec)
        if hit is None:
            unmatched += 1
            continue
        joined.append(hit)
    emit(f"joined={len(joined)} unmatched={unmatched}")

    stats = summarize_outcomes(joined)
    text = format_report(
        live_n=len(live_rows),
        research_n=len(research),
        joined_n=len(joined),
        stats=stats,
        patch="YES",
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    emit(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())