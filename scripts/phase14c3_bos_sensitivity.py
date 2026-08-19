#!/usr/bin/env python3
"""PHASE 14C-3 BOS Sensitivity Audit — research only (no live changes)."""
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
MODES = ("STRICT_BOS", "MINOR_BOS")
FALSE_BREAK_BARS = 8
CONT_ATR = 0.30


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


def detect_strict_bos_at(df, swings, breaks, i: int) -> list:
    """Current BOS: structure break kind==bos at bar i (from enrich/detect_structure_breaks)."""
    from tradingbot.domain.price_action import StructureBreak

    out: list[StructureBreak] = []
    for br in breaks:
        if br.index == i and br.kind == "bos":
            out.append(br)
    return out


def detect_minor_bos_at(df, swings_minor, i: int) -> list:
    """Research MINOR_BOS: break last small swing via wick + close; no displacement."""
    from tradingbot.domain.price_action import StructureBreak

    out: list = []
    last_high, last_low = last_swings(swings_minor, i)
    row = df.iloc[i]
    h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
    # wick pierces + close confirms beyond last swing; no body/ATR displacement gate
    if last_high is not None and h > last_high.price and c > last_high.price:
        out.append(StructureBreak(i, float(last_high.price), "bos", 1))
    if last_low is not None and l < last_low.price and c < last_low.price:
        out.append(StructureBreak(i, float(last_low.price), "bos", -1))
    return out


def bos_continuation(breaks, i: int, direction: int, lookback: int = 12) -> bool:
    for br in reversed(breaks):
        if br.index > i or br.index < i - lookback:
            continue
        if br.kind == "bos" and br.direction == direction:
            return True
    return False


def is_false_breakout(df, i: int, direction: int, level: float) -> bool:
    """False if price closes back through level within N bars before 0.3 ATR continuation."""
    import pandas as pd

    atr = float(df["atr"].iloc[i]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[i]) else 0.0
    atr = max(atr, 1e-9)
    end = min(len(df), i + 1 + FALSE_BREAK_BARS)
    saw_cont = False
    for j in range(i + 1, end):
        c = float(df["close"].iloc[j])
        h = float(df["high"].iloc[j])
        l = float(df["low"].iloc[j])
        if direction > 0:
            if (h - level) / atr >= CONT_ATR:
                saw_cont = True
                break
            if c < level:
                return True
        else:
            if (level - l) / atr >= CONT_ATR:
                saw_cont = True
                break
            if c > level:
                return True
    return not saw_cont


def harden_with_bos(df, i, cfg, setup, bos: bool):
    """Mirror apply_setup_hardening but force research bos_confirmed."""
    from tradingbot.domain.pa_hardening import (
        compute_quality_score,
        confirm_fvg_fill,
        detect_liquidity_sweep_flag,
        project_mfe_mae_r,
        session_label,
        session_range_breakout_stats,
    )
    from tradingbot.domain.price_action import SetupType

    min_quality = int(cfg.get("MIN_QUALITY_SCORE", 0))
    swings = df.attrs.get("pa_swings", [])
    fvgs = df.attrs.get("pa_fvgs", [])
    ts = df.index[i]
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)

    fvg = confirm_fvg_fill(fvgs, price=setup.entry, direction=setup.direction, i=i)
    sweep = detect_liquidity_sweep_flag(df, swings, i) or setup.setup == SetupType.LIQUIDITY_SWEEP
    sess_stats = session_range_breakout_stats(df, i, cfg)
    quality = compute_quality_score(
        setup=setup,
        bos_confirmed=bos,
        fvg_confirmed=fvg,
        liquidity_sweep=sweep,
        session_breakout=bool(sess_stats.get("breakout")),
        confluence=float(setup.confluence),
    )
    if min_quality and quality < min_quality:
        return None

    mfe, mae = project_mfe_mae_r(
        df, i, entry=setup.entry, sl=setup.stop_loss, direction=setup.direction
    )
    setup_type = setup.metadata.get("strategy_mode", setup.setup.value)
    if cfg.get("GOLD_STRATEGY_MODE") == "london_sweep" and sweep:
        setup_type = "london_sweep"

    setup.metadata.update(
        {
            "setup_type": setup_type,
            "bos_confirmed": bos,
            "fvg_confirmed": fvg,
            "liquidity_sweep": sweep,
            "quality_score": quality,
            "session": session_label(ts),
            "session_range_breakout": bool(sess_stats.get("breakout")),
            "session_range_stats": {
                k: float(sess_stats[k])
                for k in ("range_high", "range_low", "range_atr")
                if k in sess_stats
            },
            "mfe_r_projected": mfe,
            "mae_r_projected": mae,
            "timeframe": "M5",
        }
    )
    return setup


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
        return {"win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_drawdown_R": 0.0, "final_signals": 0}
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
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(pf, 3) if pf < 999 else 999.0,
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_drawdown_R": round(mdd, 3),
        "final_signals": len(rs),
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
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.price_action import (
        StructureBreak,
        detect_structure_breaks,
        enrich_price_action,
        find_swings,
    )
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
    swing_l = int(cfg.get("SWING_LEFT", 3))
    swing_r = int(cfg.get("SWING_RIGHT", 3))

    print(f"DF bars={len(df)} window={ny_s}-{ny_e}", flush=True)

    bos_count = Counter()
    false_n = Counter()
    false_d = Counter()
    raw = Counter()
    cands = defaultdict(list)
    # accumulate mode breaks for continuation window (bar-local indices on slice)
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
        swings = enriched.attrs.get("pa_swings", [])
        breaks = enriched.attrs.get("pa_breaks", [])

        # minor swings L=1 R=1 on same slice (indices absolute to slice)
        work = enriched
        minor_swings = find_swings(work, 1, 1)

        # STRICT BOS events at this bar
        strict_ev = detect_strict_bos_at(enriched, swings, breaks, local_i)
        # Also count continuation-eligible: any bos in last 12 ending at local_i
        # Event count = new bos breaks at bar
        if strict_ev:
            bos_count["STRICT_BOS"] += len(strict_ev)
            for br in strict_ev:
                false_d["STRICT_BOS"] += 1
                # map local to global for forward check
                gi = i
                if is_false_breakout(df, gi, br.direction, br.level):
                    false_n["STRICT_BOS"] += 1

        minor_ev = detect_minor_bos_at(enriched, minor_swings, local_i)
        if minor_ev:
            bos_count["MINOR_BOS"] += len(minor_ev)
            for br in minor_ev:
                false_d["MINOR_BOS"] += 1
                if is_false_breakout(df, i, br.direction, br.level):
                    false_n["MINOR_BOS"] += 1

        # Build rolling break lists for continuation (recent bos only)
        # Use enrich breaks for STRICT; synthesize minor history cheaply from last 12 bars
        strict_recent = [br for br in breaks if br.kind == "bos" and br.index <= local_i]
        minor_recent: list = []
        for k in range(max(0, local_i - 12), local_i + 1):
            minor_recent.extend(detect_minor_bos_at(enriched, minor_swings, k))

        setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
        if setup0 is None:
            continue

        for mode in MODES:
            if mode == "STRICT_BOS":
                bos_ok = bos_continuation(strict_recent, local_i, setup0.direction)
            else:
                bos_ok = bos_continuation(minor_recent, local_i, setup0.direction)

            # Research: Raw Setups = london_sweep + hardening + bos_confirmed under mode
            # (sensitivity of BOS gate; live does not hard-require BOS but quality uses it)
            if not bos_ok:
                continue

            setup = harden_with_bos(enriched, local_i, cfg, deepcopy(setup0), bos=True)
            if setup is None:
                continue
            raw[mode] += 1
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

    table = {}
    for mode in MODES:
        rs = []
        last = -10000
        open_until = -1
        day_counts = Counter()
        for c in cands[mode]:
            ii = c["i"]
            if ii <= open_until or ii - last < cd:
                continue
            if day_counts[c["day"]] >= max_day:
                continue
            rs.append(simulate_r(df, ii, c["direction"], c["entry"], c["sl"], c["tp"]))
            last = ii
            open_until = ii + 12
            day_counts[c["day"]] += 1
        m = metrics_from_rs(rs)
        table[mode] = {
            "bos_count": int(bos_count[mode]),
            "raw_setups": int(raw[mode]),
            "meta_accepted": len(cands[mode]),
            "profit_factor": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "win_rate": m["win_rate"],
            "max_drawdown_R": m["max_drawdown_R"],
            "final_signals": m["final_signals"],
        }
        print(mode, json.dumps(table[mode]), flush=True)

    s = table["STRICT_BOS"]
    n = table["MINOR_BOS"]
    setup_gain = ((n["raw_setups"] - s["raw_setups"]) / max(s["raw_setups"], 1)) * 100.0
    meta_gain = ((n["meta_accepted"] - s["meta_accepted"]) / max(s["meta_accepted"], 1)) * 100.0
    # FALSE_BREAKOUT_RATE on MINOR (research mode under test); also report STRICT in JSON
    fb_rate = (
        (100.0 * false_n["MINOR_BOS"] / false_d["MINOR_BOS"]) if false_d["MINOR_BOS"] else 0.0
    )
    fb_strict = (
        (100.0 * false_n["STRICT_BOS"] / false_d["STRICT_BOS"]) if false_d["STRICT_BOS"] else 0.0
    )

    certified = (
        setup_gain >= 30.0
        and n["profit_factor"] >= 1.6
        and fb_rate <= 25.0
    )
    safe = certified

    # Best by PF among modes; if not certified prefer STRICT for live safety messaging
    if certified:
        best = n
        best_mode = "MINOR_BOS"
    else:
        best = s if s["profit_factor"] >= n["profit_factor"] else n
        best_mode = "STRICT_BOS" if s["profit_factor"] >= n["profit_factor"] else "MINOR_BOS"

    lines = [
        "PHASE 14C-3 BOS Sensitivity Audit (Research Only)",
        "DATA=XAUUSD_M5_90d.parquet",
        "PATCH_APPLIED=NO",
        "NOTE=Raw Setups = london_sweep setups with bos_confirmed under mode detector (BOS sensitivity).",
        "STRICT=swing L/R=3 + structure kind=bos (trend-aligned close break).",
        "MINOR=swing L/R=1 + wick pierce + close confirm last swing; no displacement.",
        "",
        "| BOS Mode | BOS Count | Raw Setups | Meta Accepted | PF | Expectancy R |",
        "| -------- | --------- | ---------- | ------------- | -- | ------------ |",
    ]
    for mode in MODES:
        t = table[mode]
        lines.append(
            f"| {mode} | {t['bos_count']} | {t['raw_setups']} | {t['meta_accepted']} | "
            f"{t['profit_factor']} | {t['expectancy_R']} |"
        )
    lines.append("")
    lines.append(f"STRICT_TO_MINOR_SETUP_GAIN_PCT={round(setup_gain, 2)}")
    lines.append(f"STRICT_TO_MINOR_META_GAIN_PCT={round(meta_gain, 2)}")
    lines.append(f"FALSE_BREAKOUT_RATE={round(fb_rate, 2)}")
    lines.append(f"FALSE_BREAKOUT_RATE_STRICT={round(fb_strict, 2)}")
    lines.append("")
    lines.append("PHASE_14C_3_RESULT")
    lines.append(f"STRICT_BOS_COUNT={s['bos_count']}")
    lines.append(f"MINOR_BOS_COUNT={n['bos_count']}")
    lines.append(f"RAW_SETUP_GAIN_PCT={round(setup_gain, 2)}")
    lines.append(f"META_ACCEPTED_GAIN_PCT={round(meta_gain, 2)}")
    lines.append(f"BEST_PF={best['profit_factor']}")
    lines.append(f"BEST_EXPECTANCY_R={best['expectancy_R']}")
    lines.append(f"BOS_RELAXATION_CERTIFIED={'YES' if certified else 'NO'}")
    lines.append(f"SAFE_LIVE_PATCH={'YES' if safe else 'NO'}")

    text = "\n".join(lines) + "\n"
    out = ROOT / "logs" / "phase14c3_bos_sensitivity.txt"
    out.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase14c3_bos_sensitivity.json").write_text(
        json.dumps(
            {
                "table": table,
                "setup_gain_pct": round(setup_gain, 2),
                "meta_gain_pct": round(meta_gain, 2),
                "false_breakout_rate_minor": round(fb_rate, 2),
                "false_breakout_rate_strict": round(fb_strict, 2),
                "certified": certified,
                "best_mode": best_mode,
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
