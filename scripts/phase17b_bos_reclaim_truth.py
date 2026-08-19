#!/usr/bin/env python3
"""PHASE 17B — BOS/Reclaim Truth Engine (research only, no live changes)."""
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

OUT = ROOT / "logs" / "phase17b"
LOOKBACK = 500
BOS_LB = 12
FWD_BOS = 12
MODES = ("STRICT", "RECLAIM_ONLY", "MINOR_BOS", "BOS_BEFORE_RECLAIM")


def load_df():
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


def minor_bos_at(df, swings_minor, i: int):
    from tradingbot.domain.price_action import StructureBreak

    out = []
    last_high, last_low = last_swings(swings_minor, i)
    row = df.iloc[i]
    h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
    if last_high is not None and h > last_high.price and c > last_high.price:
        out.append(StructureBreak(i, float(last_high.price), "bos", 1))
    if last_low is not None and l < last_low.price and c < last_low.price:
        out.append(StructureBreak(i, float(last_low.price), "bos", -1))
    return out


def bos_cont(breaks, i: int, direction: int, lookback: int = BOS_LB, *, before_i: bool = False) -> bool:
    for br in reversed(breaks):
        if br.kind != "bos":
            continue
        if br.direction != direction:
            continue
        if br.index > i:
            continue
        if before_i and br.index >= i:
            continue
        if br.index < i - lookback:
            continue
        return True
    return False


def reclaim_flags(price, asian_hi, asian_lo, swept_hi, swept_lo):
    rng = max(asian_hi - asian_lo, 1e-9)
    inside = asian_lo < price < asian_hi
    dist = 0.0
    side = ""
    if swept_hi:
        side = "high"
        if inside and price < asian_hi:
            return True, True, True, True, "high", 0.0
        if price >= asian_hi:
            dist = (price - asian_hi) / rng
            return False, dist <= 0.25, dist <= 0.40, False, "high", dist
    if swept_lo:
        side = "low"
        if inside and price > asian_lo:
            return True, True, True, True, "low", 0.0
        if price <= asian_lo:
            dist = (asian_lo - price) / rng
            return False, dist <= 0.25, dist <= 0.40, False, "low", dist
    return False, False, False, inside, side, dist


def simulate_path(df, i, direction, entry, sl, tp, max_bars=96):
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0, 0.0, 0.0
    end = min(len(df), i + 1 + max_bars)
    mfe = mae = 0.0
    final_r = 0.0
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        if direction > 0:
            mfe = max(mfe, max(0.0, (hi - entry) / risk))
            mae = max(mae, max(0.0, (entry - lo) / risk))
            if lo <= sl:
                return round(mfe, 4), round(mae, 4), round((sl - entry) / risk, 4)
            if hi >= tp:
                return round(mfe, 4), round(mae, 4), round((tp - entry) / risk, 4)
        else:
            mfe = max(mfe, max(0.0, (entry - lo) / risk))
            mae = max(mae, max(0.0, (hi - entry) / risk))
            if hi >= sl:
                return round(mfe, 4), round(mae, 4), round((entry - sl) / risk, 4)
            if lo <= tp:
                return round(mfe, 4), round(mae, 4), round((entry - tp) / risk, 4)
    close = float(df["close"].iloc[end - 1])
    final_r = ((close - entry) if direction > 0 else (entry - close)) / risk
    return round(mfe, 4), round(mae, 4), round(final_r, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_dd_R": 0.0}
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


def apply_cd(cands, cd, max_day):
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


def later_strict_bos(df_full, i, direction, n=FWD_BOS) -> bool:
    """Forward scan: close-break last swing L/R=3 in direction (cheap, no full enrich)."""
    from tradingbot.domain.price_action import find_swings

    end = min(len(df_full), i + 1 + n)
    start = max(0, i - 80)
    window = df_full.iloc[start:end]
    swings = find_swings(window, 3, 3)
    # remap to window-relative; compare using window index
    local_i = i - start
    for j in range(local_i + 1, len(window)):
        c = float(window["close"].iloc[j])
        for sp in reversed(swings):
            if sp.index >= j:
                continue
            if direction > 0 and sp.kind == "high" and c > sp.price:
                return True
            if direction < 0 and sp.kind == "low" and c < sp.price:
                return True
            break
    return False


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies.m5_london_sweep import (
        _in_entry_window,
        asian_range,
        evaluate_m5_london_sweep,
    )
    from tradingbot.domain.pa_hardening import (
        apply_setup_hardening,
        confirm_fvg_fill,
        detect_bos_continuation,
    )
    from tradingbot.domain.price_action import find_swings, enrich_price_action
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler

    OUT.mkdir(parents=True, exist_ok=True)
    reload_meta_labeler()
    meta = MetaLabeler()
    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    meta_th = float(cfg.get("META_LABEL_THRESHOLD", 0.38))
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))

    df = load_df()
    print(f"DF bars={len(df)} window={ny_s}-{ny_e}", flush=True)

    truth_rows: list[dict[str, Any]] = []
    cands = defaultdict(list)
    raw = Counter()
    seq_cands = defaultdict(list)
    width_cands = defaultdict(list)
    hour_stats = {h: {"sweep": 0, "reclaim": 0, "bos": 0, "mfe1": 0} for h in range(24)}

    scanned = 0
    for i in range(LOOKBACK, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not (ny_s <= ts.hour < ny_e):
            continue
        scanned += 1
        if scanned % 1500 == 0:
            print(f"progress={scanned} truth={len(truth_rows)}", flush=True)

        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg, at_index=local_i)

        if not _in_entry_window(enriched, local_i, cfg):
            continue
        bounds = asian_range(
            enriched,
            local_i,
            start_hour=int(cfg.get("ASIAN_START_HOUR", 0)),
            end_hour=int(cfg.get("ASIAN_END_HOUR", 7)),
            min_bars=4,
        )
        if bounds is None:
            continue
        asian_hi, asian_lo = bounds
        row = enriched.iloc[local_i]
        price = float(row["close"])
        atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else price * 0.001
        if atr <= 0:
            continue
        if (asian_hi - asian_lo) < atr * float(cfg.get("MIN_RANGE_ATR", 0.25)):
            continue

        lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
        buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
        window = enriched.iloc[max(0, local_i - lookback) : local_i + 1]
        win_high = float(window["high"].max())
        win_low = float(window["low"].min())
        swept_hi = win_high > asian_hi + buf
        swept_lo = win_low < asian_lo - buf
        sweep = bool(swept_hi or swept_lo)
        if not sweep:
            continue

        rec_strict, rec_25, rec_40, inside, side, dist = reclaim_flags(
            price, asian_hi, asian_lo, swept_hi, swept_lo
        )
        direction = -1 if side == "high" else (1 if side == "low" else 0)
        if direction == 0:
            if swept_hi:
                direction = -1
                side = "high"
            else:
                direction = 1
                side = "low"

        breaks = enriched.attrs.get("pa_breaks", []) or []
        fvgs = enriched.attrs.get("pa_fvgs", []) or []
        swings = enriched.attrs.get("pa_swings", []) or []
        minor_swings = find_swings(enriched, 1, 1)
        minor_now = minor_bos_at(enriched, minor_swings, local_i)
        minor_recent = []
        for k in range(max(0, local_i - BOS_LB), local_i + 1):
            minor_recent.extend(minor_bos_at(enriched, minor_swings, k))

        bos_strict = bos_cont(breaks, local_i, direction)
        bos_strict_before = bos_cont(breaks, local_i, direction, before_i=True)
        bos_minor = bos_cont(minor_recent, local_i, direction)
        fvg = confirm_fvg_fill(fvgs, price=price, direction=direction, i=local_i)

        # Build a research setup (same SL/TP as london_sweep) when reclaim-ish
        setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
        # For soft reclaim, evaluate_m5 may be None; synthesize if we have side
        if setup0 is None and (rec_25 or rec_40 or rec_strict):
            from tradingbot.domain.price_action import PriceActionSetup, SetupType

            min_rr = float(cfg.get("MIN_RR", 1.8))
            sl_pad = atr * float(cfg.get("SL_ATR_MULT", 0.35))
            if direction < 0:
                slv = win_high + sl_pad
                risk = slv - price
                tp = price - max(max(price - asian_lo, 0.0), risk * min_rr)
            else:
                slv = win_low - sl_pad
                risk = price - slv
                tp = price + max(max(asian_hi - price, 0.0), risk * min_rr)
            if risk > 0:
                rr = abs(tp - price) / risk
                setup0 = PriceActionSetup(
                    direction=direction,
                    setup=SetupType.LIQUIDITY_SWEEP,
                    entry=price,
                    stop_loss=float(slv),
                    take_profit=float(tp),
                    confidence=round(min(0.92, 0.55 + min(rr, 3.0) * 0.08), 3),
                    confluence=3.2,
                    metadata={"strategy_mode": "m5_london_sweep", "sweep_side": side, "rr": round(rr, 2)},
                )

        setup = None
        if setup0 is not None:
            setup = apply_setup_hardening(enriched, local_i, cfg, deepcopy(setup0), timeframe="M5")

        mfe = mae = final_r = 0.0
        if setup is not None:
            mfe, mae, final_r = simulate_path(
                df, i, int(setup.direction), float(setup.entry), float(setup.stop_loss), float(setup.take_profit)
            )

        hour_stats[ts.hour]["sweep"] += 1
        if rec_strict:
            hour_stats[ts.hour]["reclaim"] += 1
        if bos_strict:
            hour_stats[ts.hour]["bos"] += 1
        if mfe >= 1.0:
            hour_stats[ts.hour]["mfe1"] += 1

        truth_rows.append(
            {
                "timestamp": ts.isoformat(),
                "bar_index": i,
                "hour": int(ts.hour),
                "direction": int(direction),
                "sweep": True,
                "reclaim": bool(rec_strict),
                "reclaim_soft25": bool(rec_25),
                "reclaim_soft40": bool(rec_40),
                "bos_strict": bool(bos_strict),
                "bos_strict_before": bool(bos_strict_before),
                "bos_minor": bool(bos_minor),
                "fvg": bool(fvg),
                "mfe_r": mfe,
                "mae_r": mae,
                "final_r": final_r,
                "reclaim_dist_pct": round(dist, 4),
            }
        )

        def accept_setup(ok_gate: bool, bucket: dict, key: str, *, count_raw: bool = False):
            if not ok_gate or setup is None:
                return
            if count_raw:
                raw[key] += 1
            if float(setup.confidence) < min_conf:
                return
            prob = score_meta(meta, setup, enriched, ts)
            if prob is None or prob < meta_th:
                return
            bucket[key].append(
                {
                    "i": i,
                    "day": str(ts.date()),
                    "direction": int(setup.direction),
                    "entry": float(setup.entry),
                    "sl": float(setup.stop_loss),
                    "tp": float(setup.take_profit),
                    "mfe": mfe,
                    "final_r": final_r,
                }
            )

        accept_setup(rec_strict and bos_strict, cands, "STRICT", count_raw=True)
        accept_setup(rec_strict, cands, "RECLAIM_ONLY", count_raw=True)
        accept_setup(rec_strict and bos_minor, cands, "MINOR_BOS", count_raw=True)
        accept_setup(rec_strict and bos_strict_before, cands, "BOS_BEFORE_RECLAIM", count_raw=True)

        # Sequence A: sweep -> reclaim -> BOS -> FVG
        accept_setup(rec_strict and bos_strict and fvg, seq_cands, "A", count_raw=True)
        # Sequence B: sweep -> BOS -> reclaim -> FVG
        accept_setup(bos_strict_before and rec_strict and fvg, seq_cands, "B", count_raw=True)

        # Width sweep: only if later real BOS (or already has strict BOS)
        later = bos_strict
        if setup is not None and not later:
            later = later_strict_bos(df, i, int(setup.direction))
        accept_setup(rec_strict and later, width_cands, "STRICT")
        accept_setup(rec_25 and later, width_cands, "SOFT_25")
        accept_setup(rec_40 and later, width_cands, "SOFT_40")

    # persist truth table
    tdf = pd.DataFrame(truth_rows)
    tpath = OUT / "bos_reclaim_truth_table.parquet"
    tdf.to_parquet(tpath, index=False)
    print(f"truth_rows={len(tdf)} wrote {tpath}", flush=True)

    def eval_bucket(bucket, keys):
        table = {}
        for key in keys:
            traded = apply_cd(bucket[key], cd, max_day)
            rs = [c["final_r"] for c in traded]
            m = metrics_from_rs(rs)
            table[key] = {
                "raw_setups": int(raw[key]) if key in raw else len(bucket[key]),
                "meta_accepted": len(bucket[key]),
                **m,
            }
        return table

    # raw counts for seq/width stored via accept_setup into raw Counter overlapping names
    # isolate: recompute raw from accept_setup already mixed. For seq/width use meta list lengths as meta_accepted
    # Fix: store separate counters
    mode_table = {}
    for key in MODES:
        traded = apply_cd(cands[key], cd, max_day)
        rs = [simulate_path(df, c["i"], c["direction"], c["entry"], c["sl"], c["tp"])[2] for c in traded]
        m = metrics_from_rs(rs)
        mode_table[key] = {
            "raw_setups": int(raw[key]),
            "meta_accepted": len(cands[key]),
            **m,
        }
        print(key, json.dumps(mode_table[key]), flush=True)

    seq_table = {}
    for key in ("A", "B"):
        traded = apply_cd(seq_cands[key], cd, max_day)
        rs = [simulate_path(df, c["i"], c["direction"], c["entry"], c["sl"], c["tp"])[2] for c in traded]
        seq_table[key] = {
            "raw_setups": int(raw[key]) if key in raw else 0,
            "meta_accepted": len(seq_cands[key]),
            **metrics_from_rs(rs),
        }
    (OUT / "sequence_comparison.json").write_text(
        json.dumps({"A_sweep_reclaim_bos_fvg": seq_table.get("A"), "B_sweep_bos_reclaim_fvg": seq_table.get("B")}, indent=2),
        encoding="utf-8",
    )

    width_table = {}
    for key in ("STRICT", "SOFT_25", "SOFT_40"):
        traded = apply_cd(width_cands[key], cd, max_day)
        rs = [simulate_path(df, c["i"], c["direction"], c["entry"], c["sl"], c["tp"])[2] for c in traded]
        width_table[key] = {
            "meta_accepted": len(width_cands[key]),
            **metrics_from_rs(rs),
        }

    heat_lines = [
        "| Hour | Sweep | Reclaim | BOS | +1R MFE |",
        "| ---- | ----- | ------- | --- | ------- |",
    ]
    for h in range(24):
        s = hour_stats[h]
        heat_lines.append(f"| {h:02d} | {s['sweep']} | {s['reclaim']} | {s['bos']} | {s['mfe1']} |")

    def passes_gate(m):
        return (
            m["trades"] >= 25
            and m["profit_factor"] >= 1.40
            and m["expectancy_R"] >= 0.20
            and m["max_dd_R"] <= 8.0
        )

    best_mode = max(MODES, key=lambda k: (passes_gate(mode_table[k]), mode_table[k]["profit_factor"], mode_table[k]["expectancy_R"]))
    best_seq = "A" if seq_table["A"]["profit_factor"] >= seq_table["B"]["profit_factor"] else "B"
    best_width = max(("STRICT", "SOFT_25", "SOFT_40"), key=lambda k: (width_table[k]["profit_factor"], width_table[k]["expectancy_R"], width_table[k]["trades"]))

    # killer: among truth rows with sweep, what fails most
    n_sw = max(len(tdf), 1)
    n_rec = int(tdf["reclaim"].sum()) if len(tdf) else 0
    n_bos = int(tdf["bos_strict"].sum()) if len(tdf) else 0
    n_min = int(tdf["bos_minor"].sum()) if len(tdf) else 0
    drop_rec = 1.0 - n_rec / n_sw
    drop_bos_given_rec = 1.0 - (int(((tdf["reclaim"]) & (tdf["bos_strict"])).sum()) / max(n_rec, 1))
    if drop_rec >= drop_bos_given_rec:
        killer = "reclaim"
    else:
        killer = "bos_strict"
    recoverable = int(((tdf["reclaim"]) & (tdf["bos_minor"]) & (~tdf["bos_strict"])).sum()) if len(tdf) else 0

    any_pass = any(passes_gate(mode_table[k]) for k in MODES) or any(passes_gate(width_table[k]) for k in width_table)
    safe = "YES" if any_pass else "NO"
    rec_change = "NONE"
    if any_pass:
        rec_change = f"RESEARCH_ONLY_CANDIDATE_{best_mode}"
    else:
        rec_change = "NONE_ENTER_PHASE_18A"

    st = mode_table["STRICT"]
    mn = mode_table["MINOR_BOS"]
    ro = mode_table["RECLAIM_ONLY"]

    lines = [
        "PHASE 17B BOS/Reclaim Truth Engine (Research Only)",
        "DATA=XAUUSD_M5_90d.parquet",
        "PATCH_APPLIED=NO",
        f"TRUTH_ROWS={len(tdf)}",
        "",
        "=== Mode replay ===",
    ]
    for k in MODES:
        t = mode_table[k]
        lines.append(
            f"| {k} | raw={t['raw_setups']} meta={t['meta_accepted']} trades={t['trades']} "
            f"WR={t['win_rate']} PF={t['profit_factor']} ExpR={t['expectancy_R']} MaxDD={t['max_dd_R']} |"
        )
    lines.append("")
    lines.append("=== Sequence ===")
    lines.append(f"A sweep>reclaim>BOS>FVG PF={seq_table['A']['profit_factor']} ExpR={seq_table['A']['expectancy_R']} trades={seq_table['A']['trades']}")
    lines.append(f"B sweep>BOS>reclaim>FVG PF={seq_table['B']['profit_factor']} ExpR={seq_table['B']['expectancy_R']} trades={seq_table['B']['trades']}")
    lines.append("")
    lines.append("=== Reclaim width (kept only if later/real BOS) ===")
    for k, t in width_table.items():
        lines.append(f"{k}: trades={t['trades']} PF={t['profit_factor']} ExpR={t['expectancy_R']} MaxDD={t['max_dd_R']}")
    lines.append("")
    lines.append("=== +1R MFE heatmap ===")
    lines.extend(heat_lines)
    lines.append("")
    lines.append("PHASE_17B_RESULT")
    lines.append("")
    lines.append(f"BEST_MODE={best_mode}")
    lines.append(f"BEST_SEQUENCE={best_seq}")
    lines.append("")
    lines.append(f"STRICT_TRADES={st['trades']}")
    lines.append(f"MINOR_BOS_TRADES={mn['trades']}")
    lines.append(f"RECLAIM_ONLY_TRADES={ro['trades']}")
    lines.append("")
    lines.append(f"STRICT_PF={st['profit_factor']}")
    lines.append(f"MINOR_BOS_PF={mn['profit_factor']}")
    lines.append(f"RECLAIM_ONLY_PF={ro['profit_factor']}")
    lines.append("")
    lines.append(f"STRICT_EXPECTANCY_R={st['expectancy_R']}")
    lines.append(f"MINOR_BOS_EXPECTANCY_R={mn['expectancy_R']}")
    lines.append(f"RECLAIM_ONLY_EXPECTANCY_R={ro['expectancy_R']}")
    lines.append("")
    lines.append(f"BEST_RECLAIM_WIDTH={best_width}")
    lines.append("")
    lines.append(f"SEQUENCE_A_PF={seq_table['A']['profit_factor']}")
    lines.append(f"SEQUENCE_B_PF={seq_table['B']['profit_factor']}")
    lines.append("")
    lines.append(f"PRIMARY_SETUP_KILLER={killer}")
    lines.append(f"RECOVERABLE_SETUPS={recoverable}")
    lines.append(f"SAFE_FOR_LIVE_PATCH={safe}")
    lines.append(f"RECOMMENDED_LIVE_CHANGE={rec_change}")
    lines.append("PATCH_APPLIED=NO")
    text = "\n".join(lines) + "\n"
    (OUT / "phase17b_result.txt").write_text(text, encoding="utf-8")
    (OUT / "phase17b_matrix.json").write_text(
        json.dumps(
            {
                "modes": mode_table,
                "sequence": seq_table,
                "width": width_table,
                "killer": killer,
                "recoverable": recoverable,
                "truth_rows": len(tdf),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text)
    print("WROTE", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
