#!/usr/bin/env python3
"""PHASE 14C-2 Asian Reclaim Softening — research only (no live changes)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

LOOKBACK = 500
MODES = ("STRICT", "SOFT_5", "SOFT_10")
SOFT_PCT = {"STRICT": 0.0, "SOFT_5": 0.05, "SOFT_10": 0.10}


def load_df():
    import pandas as pd

    path = ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet"
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    if "atr" not in df.columns:
        df = df.copy()
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df


def make_cfg() -> dict[str, Any]:
    from tradingbot.config.price_action import get_price_action_config

    return deepcopy(get_price_action_config("XAUUSD", "M5"))


def reclaim_ok(
    *,
    mode: str,
    price: float,
    asian_hi: float,
    asian_lo: float,
    swept_hi: bool,
    swept_lo: bool,
) -> tuple[bool, str, float]:
    """Return (ok, side, distance_pct). side in {high,low,''}."""
    rng = max(asian_hi - asian_lo, 1e-9)
    inside = asian_lo < price < asian_hi
    if swept_hi and (not swept_lo or True):
        # prefer matching sweep side; if both, evaluate both
        pass
    # high sweep reclaim: want close back at/below asian_hi (inside or near from above)
    if swept_hi:
        if inside and price < asian_hi:
            return True, "high", 0.0
        if price >= asian_hi:
            dist = (price - asian_hi) / rng
            if mode != "STRICT" and dist <= SOFT_PCT[mode]:
                return True, "high", dist
            return False, "high", dist
    if swept_lo:
        if inside and price > asian_lo:
            return True, "low", 0.0
        if price <= asian_lo:
            dist = (asian_lo - price) / rng
            if mode != "STRICT" and dist <= SOFT_PCT[mode]:
                return True, "low", dist
            return False, "low", dist
    return False, "", 0.0


def evaluate_research(df, i: int, cfg: dict[str, Any], mode: str):
    """Mirror evaluate_m5_london_sweep with reclaim softening (research only)."""
    import pandas as pd
    from tradingbot.domain.gold_strategies.m5_london_sweep import (
        _in_entry_window,
        asian_range,
    )
    from tradingbot.domain.price_action import PriceActionSetup, SetupType, _engulfing, _pin_bar

    if i < 30 or i >= len(df):
        return None, "warmup_or_oob"
    if not _in_entry_window(df, i, cfg):
        return None, "outside_ny_entry_window"

    bounds = asian_range(
        df,
        i,
        start_hour=int(cfg.get("ASIAN_START_HOUR", 0)),
        end_hour=int(cfg.get("ASIAN_END_HOUR", 7)),
        min_bars=4,
    )
    if bounds is None:
        return None, "no_asian_range"
    asian_hi, asian_lo = bounds
    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else price * 0.001
    if atr <= 0:
        return None, "atr_invalid"
    if (asian_hi - asian_lo) < atr * float(cfg.get("MIN_RANGE_ATR", 0.25)):
        return None, "no_asian_range"

    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
    window = df.iloc[max(0, i - lookback) : i + 1]
    win_high = float(window["high"].max())
    win_low = float(window["low"].min())
    swept_hi = win_high > asian_hi + buf
    swept_lo = win_low < asian_lo - buf
    if not (swept_hi or swept_lo):
        return None, "no_sweep"

    ok, side, dist = reclaim_ok(
        mode=mode,
        price=price,
        asian_hi=asian_hi,
        asian_lo=asian_lo,
        swept_hi=swept_hi,
        swept_lo=swept_lo,
    )
    if not ok:
        return None, "no_reclaim_inside_asian"

    min_rr = float(cfg.get("MIN_RR", 1.8))
    sl_pad = atr * float(cfg.get("SL_ATR_MULT", 0.35))
    direction = None
    sl = tp = risk = 0.0
    meta: dict[str, Any] = {
        "strategy_mode": "m5_london_sweep",
        "asian_high": asian_hi,
        "asian_low": asian_lo,
        "reclaim_mode": mode,
        "reclaim_distance_pct": round(dist, 4),
    }

    # If both sweeps, prefer the soft/strict side that passed
    if side == "high" and swept_hi:
        direction = -1
        meta["sweep_side"] = "high"
        sl = win_high + sl_pad
        risk = sl - price
        tp = price - max(max(price - asian_lo, 0.0), risk * min_rr)
    elif side == "low" and swept_lo:
        direction = 1
        meta["sweep_side"] = "low"
        sl = win_low - sl_pad
        risk = price - sl
        tp = price + max(max(asian_hi - price, 0.0), risk * min_rr)
    else:
        return None, "no_reclaim_inside_asian"

    if bool(cfg.get("M5_REQUIRE_REJECTION", True)) and not (
        _engulfing(df, i) == direction or _pin_bar(row, direction)
    ):
        return None, "rejection_candle_fail"
    if risk <= 0:
        return None, "risk_invalid"
    rr = abs(tp - price) / risk
    if rr < min_rr * 0.95:
        return None, "rr_below_min"
    confidence = min(0.92, 0.55 + min(rr, 3.0) * 0.08)
    setup = PriceActionSetup(
        direction=direction,
        setup=SetupType.LIQUIDITY_SWEEP,
        entry=price,
        stop_loss=float(sl),
        take_profit=float(tp),
        confidence=round(confidence, 3),
        confluence=3.2,
        metadata={**meta, "rr": round(rr, 2)},
    )
    return setup, "ok"


def simulate_r(df, i, direction, entry, sl, tp, max_bars=96) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    end = min(len(df), i + 1 + max_bars)
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
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
    close = float(df["close"].iloc[end - 1])
    return round(((close - entry) if direction > 0 else (entry - close)) / risk, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {
            "final_signals": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "max_drawdown_R": 0.0,
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "final_signals": len(rs),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(pf, 3) if pf < 999 else 999.0,
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_drawdown_R": round(mdd, 3),
    }


def score_meta(meta, setup, enriched, ts):
    try:
        from tradingbot.domain.enums import SignalDirection
        from tradingbot.domain.models import TradingSignal

        direction = SignalDirection.BUY if setup.direction > 0 else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(setup.confidence),
            symbol="XAUUSD",
            timeframe="M5",
            strategy_name="priceaction",
            stop_loss=float(setup.stop_loss),
            take_profit=float(setup.take_profit),
            metadata=dict(setup.metadata or {}),
            created_at=ts,
        )
        return float(
            meta.score(
                sig,
                {"symbol": "XAUUSD", "timeframe": "M5", "regime": "TREND", "ohlcv": enriched},
                "TREND",
            )
        )
    except Exception:
        return None


def main() -> int:
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler

    reload_meta_labeler()
    meta = MetaLabeler()
    df = load_df()
    cfg = make_cfg()
    meta_th = float(cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))

    print(f"DF bars={len(df)} window={ny_s}-{ny_e}", flush=True)

    raw = Counter()
    rejects = Counter()  # mode -> no_reclaim counts among sweep bars
    cands = defaultdict(list)
    # track bar indices where STRICT rejected reclaim but soft recovered
    strict_reclaim_reject_bars: set[int] = set()
    soft5_recover_bars: set[int] = set()
    soft10_recover_bars: set[int] = set()

    scanned = 0
    for i in range(LOOKBACK, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not (ny_s <= ts.hour < ny_e):
            continue
        scanned += 1
        if scanned % 1500 == 0:
            print(f"progress={scanned}", flush=True)

        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg, at_index=local_i)

        # evaluate each mode on same bar
        results_bar = {}
        for mode in MODES:
            setup0, reason = evaluate_research(enriched, local_i, cfg, mode)
            if setup0 is None:
                if reason == "no_reclaim_inside_asian":
                    rejects[mode] += 1
                results_bar[mode] = (None, reason)
                continue
            setup = apply_setup_hardening(enriched, local_i, cfg, setup0, timeframe="M5")
            if setup is None:
                results_bar[mode] = (None, "hardening_rejected")
                continue
            raw[mode] += 1
            results_bar[mode] = (setup, "ok")
            if float(setup.confidence) < min_conf:
                continue
            prob = score_meta(meta, setup, enriched, ts)
            if prob is None or prob < meta_th:
                continue
            cands[mode].append(
                {
                    "i": i,
                    "day": str(ts.date()),
                    "direction": int(setup.direction),
                    "entry": float(setup.entry),
                    "sl": float(setup.stop_loss),
                    "tp": float(setup.take_profit),
                }
            )

        # recovery accounting: only when sweep existed (strict reject reason reclaim)
        s_setup, s_reason = results_bar.get("STRICT", (None, ""))
        if s_reason == "no_reclaim_inside_asian":
            strict_reclaim_reject_bars.add(i)
            if results_bar.get("SOFT_5", (None, ""))[0] is not None:
                soft5_recover_bars.add(i)
            if results_bar.get("SOFT_10", (None, ""))[0] is not None:
                soft10_recover_bars.add(i)

    # trade metrics per mode
    table = {}
    for mode in MODES:
        rs = []
        last = -10000
        open_until = -1
        day_counts = Counter()
        for c in cands[mode]:
            i = c["i"]
            if i <= open_until or i - last < cd:
                continue
            if day_counts[c["day"]] >= max_day:
                continue
            rs.append(simulate_r(df, i, c["direction"], c["entry"], c["sl"], c["tp"]))
            last = i
            open_until = i + 12
            day_counts[c["day"]] += 1
        m = metrics_from_rs(rs)
        table[mode] = {
            "raw_setups": int(raw[mode]),
            "meta_accepted": len(cands[mode]),
            "win_rate": m["win_rate"],
            "profit_factor": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "max_drawdown_R": m["max_drawdown_R"],
            "final_signals": m["final_signals"],
        }
        print(mode, json.dumps(table[mode]), flush=True)

    strict_rejects = len(strict_reclaim_reject_bars)
    soft5_rec = len(soft5_recover_bars)
    soft10_rec = len(soft10_recover_bars)

    base_meta = table["STRICT"]["meta_accepted"]
    best_mode = "STRICT"
    best_score = (-1e9, -1e9, -1e9)
    for mode in MODES:
        t = table[mode]
        score = (t["profit_factor"], t["expectancy_R"], t["meta_accepted"])
        if score > best_score:
            best_score = score
            best_mode = mode
    best = table[best_mode]
    meta_inc = (
        ((best["meta_accepted"] - base_meta) / max(base_meta, 1)) * 100.0
        if best_mode != "STRICT"
        else 0.0
    )
    # certification vs STRICT baseline using BEST soft mode if soft, else STRICT can't "increase"
    # Gate: compare best non-strict if any passes; else check if any mode passes absolute gates
    certified = False
    safe = False
    for mode in ("SOFT_5", "SOFT_10"):
        t = table[mode]
        inc = ((t["meta_accepted"] - base_meta) / max(base_meta, 1)) * 100.0
        if (
            inc >= 20.0
            and t["profit_factor"] >= 1.8
            and t["expectancy_R"] >= 0.40
            and t["max_drawdown_R"] <= 5.0
        ):
            certified = True
            safe = True
            best_mode = mode
            best = t
            meta_inc = inc
            break
    # if none certified, still report absolute best by PF among modes that beat meta count
    if not certified:
        # pick best by PF among soft modes with higher meta, else STRICT
        soft_best = None
        for mode in ("SOFT_5", "SOFT_10"):
            t = table[mode]
            if t["meta_accepted"] >= base_meta:
                if soft_best is None or t["profit_factor"] > table[soft_best]["profit_factor"]:
                    soft_best = mode
        if soft_best is not None:
            best_mode = soft_best
            best = table[soft_best]
            meta_inc = ((best["meta_accepted"] - base_meta) / max(base_meta, 1)) * 100.0
        else:
            best_mode = "STRICT"
            best = table["STRICT"]
            meta_inc = 0.0

    lines = [
        "PHASE 14C-2 Asian Reclaim Softening (Research Only)",
        "DATA=XAUUSD_M5_90d.parquet",
        "PATCH_APPLIED=NO",
        "",
        "| Mode | Raw Setups | Meta Accepted | Win Rate | PF | Expectancy R | Max DD |",
        "| ---- | ---------- | ------------- | -------- | -- | ------------ | ------ |",
    ]
    for mode in MODES:
        t = table[mode]
        lines.append(
            f"| {mode} | {t['raw_setups']} | {t['meta_accepted']} | {t['win_rate']} | "
            f"{t['profit_factor']} | {t['expectancy_R']} | {t['max_drawdown_R']} |"
        )
    lines.append("")
    lines.append(f"STRICT_REJECTS={strict_rejects}")
    lines.append(f"SOFT5_RECOVERED={soft5_rec}")
    lines.append(f"SOFT10_RECOVERED={soft10_rec}")
    lines.append("")
    lines.append("PHASE_14C_2_RESULT")
    lines.append(f"BEST_MODE={best_mode}")
    lines.append(f"META_ACCEPTED_INCREASE_PCT={round(meta_inc, 2)}")
    lines.append(f"BEST_PF={best['profit_factor']}")
    lines.append(f"BEST_EXPECTANCY_R={best['expectancy_R']}")
    lines.append(f"BEST_MAX_DD_R={best['max_drawdown_R']}")
    lines.append(f"RECLAIM_SOFTENING_CERTIFIED={'YES' if certified else 'NO'}")
    lines.append(f"SAFE_LIVE_PATCH={'YES' if safe else 'NO'}")

    text = "\n".join(lines) + "\n"
    out = ROOT / "logs" / "phase14c2_reclaim_softening.txt"
    out.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase14c2_reclaim_softening.json").write_text(
        json.dumps(
            {
                "table": table,
                "strict_rejects": strict_rejects,
                "soft5_recovered": soft5_rec,
                "soft10_recovered": soft10_rec,
                "best_mode": best_mode,
                "certified": certified,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text)
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
