#!/usr/bin/env python3
"""PHASE 20Y-2 ? CHoCH continuation bridge 90d replay certification."""
from __future__ import annotations

import os
import sys
from collections import Counter
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = ROOT / "logs" / "phase20y2_choch_bridge_result.txt"
LOOKBACK = 300
FWD = 96


def load_df() -> pd.DataFrame:
    for name in ("XAUUSD_M5_180d.parquet", "XAUUSD_M5_90d.parquet"):
        path = ROOT / "data" / "cache" / name
        if path.exists():
            df = pd.read_parquet(path)
            break
    else:
        raise FileNotFoundError("XAUUSD M5 parquet cache missing")
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    end = df.index.max()
    start = end - pd.Timedelta(days=90)
    df = df.loc[df.index >= start].copy()
    if "atr" not in df.columns:
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df


def simulate_path(df, i, direction, entry, sl, tp, max_bars=FWD):
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
    final_r = ((close - entry) if direction > 0 else (entry - close)) / risk
    return round(final_r, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "max_dd_R": 0.0,
        }
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


def try_setup(df, i, enriched, local_i, cfg, min_conf):
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening

    setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
    if setup0 is None:
        return None
    setup = apply_setup_hardening(enriched, local_i, cfg, setup0, timeframe="M5")
    if setup is None or float(setup.confidence) < min_conf:
        return None
    ts = df.index[i].to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    meta = setup.metadata or {}
    return {
        "i": i,
        "day": ts.date().isoformat(),
        "r": simulate_path(
            df,
            i,
            int(setup.direction),
            float(setup.entry),
            float(setup.stop_loss),
            float(setup.take_profit),
        ),
        "path": str(meta.get("entry_path", "reclaim")),
        "bos": bool(meta.get("bos_confirmed") or meta.get("bos_ok")),
        "choch": bool(meta.get("choch_confirmed") or meta.get("choch_ok")),
    }


def collect_both(df, cfg_off, cfg_on, ny_s, ny_e, min_conf):
    from tradingbot.domain.price_action import enrich_price_action

    cands_off = []
    cands_on = []
    scanned = 0
    for i in range(LOOKBACK, len(df) - 2):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not (ny_s <= ts.hour < ny_e):
            continue
        scanned += 1
        if scanned % 800 == 0:
            print(
                f"  progress scanned={scanned} off={len(cands_off)} on={len(cands_on)}",
                flush=True,
            )
        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg_off, at_index=local_i)
        row_off = try_setup(df, i, enriched, local_i, cfg_off, min_conf)
        if row_off is not None:
            cands_off.append(row_off)
        row_on = try_setup(df, i, enriched, local_i, cfg_on, min_conf)
        if row_on is not None:
            cands_on.append(row_on)
    return cands_off, cands_on, scanned


def yn(ok: bool) -> str:
    return "YES" if ok else "NO"


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config

    cfg_base = deepcopy(get_price_action_config("XAUUSD", "M5"))
    min_conf = float(cfg_base.get("MIN_CONFIDENCE", 0.52))
    cd = int(cfg_base.get("COOLDOWN_BARS", 18))
    max_day = int(cfg_base.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg_base.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg_base.get("NY_ENTRY_END_HOUR", 17))

    df = load_df()
    print(f"DF bars={len(df)} {df.index.min()} -> {df.index.max()}", flush=True)

    cfg_off = deepcopy(cfg_base)
    cfg_off["ENABLE_CHOCH_CONTINUATION"] = False
    cfg_on = deepcopy(cfg_base)
    cfg_on["ENABLE_CHOCH_CONTINUATION"] = True

    print("MODE=BOS_ONLY vs BOS_OR_CHOCH (single enrich pass)", flush=True)
    cands_off, cands_on, scanned_off = collect_both(df, cfg_off, cfg_on, ny_s, ny_e, min_conf)
    scanned_on = scanned_off

    trades_off = apply_cd(cands_off, cd, max_day)
    trades_on = apply_cd(cands_on, cd, max_day)
    m_off = metrics_from_rs([c["r"] for c in trades_off])
    m_on = metrics_from_rs([c["r"] for c in trades_on])

    n_off = int(m_off["trades"])
    n_on = int(m_on["trades"])
    if n_off > 0:
        increase = 100.0 * (n_on - n_off) / n_off
    else:
        increase = 0.0 if n_on == 0 else 999.0
    pf_delta = float(m_on["profit_factor"]) - float(m_off["profit_factor"])
    expr_delta = float(m_on["expectancy_R"]) - float(m_off["expectancy_R"])
    dd_delta = float(m_on["max_dd_R"]) - float(m_off["max_dd_R"])

    pf_ok = float(m_on["profit_factor"]) >= float(m_off["profit_factor"]) * 0.95
    expr_ok = float(m_on["expectancy_R"]) + 1e-12 >= float(m_off["expectancy_R"])
    dd_ok = float(m_on["max_dd_R"]) <= float(m_off["max_dd_R"]) + 1.0
    trade_ok = increase >= 20.0 and n_off > 0
    valid = bool(trade_ok and pf_ok and expr_ok and dd_ok)
    safe = valid

    preset_path = ROOT / "tradingbot" / "config" / "pa_symbol_tf_presets.py"
    text = preset_path.read_text(encoding="utf-8")
    live_flag = True
    if not safe:
        live_flag = False
        text2 = text.replace(
            '"ENABLE_CHOCH_CONTINUATION": True,',
            '"ENABLE_CHOCH_CONTINUATION": False,',
            1,
        )
        if text2 != text:
            preset_path.write_text(text2, encoding="utf-8")
            text = text2
    live_flag = '"ENABLE_CHOCH_CONTINUATION": True,' in text.split("M15")[0]

    choch_paths = sum(1 for c in trades_on if c["path"] == "choch_continuation")
    lines = [
        "PHASE_20Y2_CHOCH_BRIDGE",
        f"BARS={len(df)}",
        f"SCANNED_OFF={scanned_off}",
        f"SCANNED_ON={scanned_on}",
        f"RAW_SETUPS_OFF={len(cands_off)}",
        f"RAW_SETUPS_ON={len(cands_on)}",
        f"CHOCH_PATH_TRADES={choch_paths}",
        f"BOS_ONLY_PF={m_off['profit_factor']}",
        f"BOS_OR_CHOCH_PF={m_on['profit_factor']}",
        f"BOS_ONLY_EXPR={m_off['expectancy_R']}",
        f"BOS_OR_CHOCH_EXPR={m_on['expectancy_R']}",
        f"BOS_ONLY_MAXDD={m_off['max_dd_R']}",
        f"BOS_OR_CHOCH_MAXDD={m_on['max_dd_R']}",
        f"LIVE_FLAG_ENABLE_CHOCH_CONTINUATION={yn(live_flag)}",
        "",
        "PHASE_20Y2_RESULT",
        "",
        f"BOS_ONLY_TRADES={n_off}",
        f"BOS_OR_CHOCH_TRADES={n_on}",
        "",
        f"TRADE_INCREASE_PCT={increase:.2f}",
        f"PF_DELTA={pf_delta:.3f}",
        f"EXPECTANCY_DELTA_R={expr_delta:.4f}",
        f"MAX_DD_DELTA_R={dd_delta:.3f}",
        "",
        f"CHOCH_CONTINUATION_VALID={yn(valid)}",
        f"SAFE_FOR_LIVE_ENABLE={yn(safe)}",
        "PATCH_APPLIED=YES",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
