#!/usr/bin/env python3
"""PHASE 16B — OB+FVG Institutional Confluence comparison (research only)."""
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


def is_false_breakout(df, i, direction, entry, sl, bars: int = 8) -> bool:
    """False if price closes back through entry against direction before 0.3R progress."""
    risk = abs(entry - sl)
    if risk <= 0:
        return True
    end = min(len(df), i + 1 + bars)
    saw = False
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        c = float(df["close"].iloc[j])
        if direction > 0:
            if (hi - entry) / risk >= 0.3:
                saw = True
                break
            if c < entry:
                return True
        else:
            if (entry - lo) / risk >= 0.3:
                saw = True
                break
            if c > entry:
                return True
    return not saw


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_dd": 0.0}
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
        "trades": len(rs),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(pf, 3) if pf < 999 else 999.0,
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_dd": round(mdd, 3),
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


def apply_trade_filter(cands: list[dict], cd: int, max_day: int) -> list[dict]:
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


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.research.ob_fvg_confluence import (
        current_loose_ob_valid,
        evaluate_institutional_confluence,
    )
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler

    reload_meta_labeler()
    meta = MetaLabeler()
    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    df = load_df()
    meta_th = float(cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))

    print(f"DF bars={len(df)} window={ny_s}-{ny_e}", flush=True)

    raw = Counter()
    meta_acc = Counter()
    false_n = Counter()
    false_d = Counter()
    cands = defaultdict(list)

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
        setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
        if setup0 is None:
            continue
        setup = apply_setup_hardening(enriched, local_i, cfg, setup0, timeframe="M5")
        if setup is None:
            continue

        direction = int(setup.direction)
        price = float(setup.entry)
        loose_ok = current_loose_ob_valid(enriched, local_i, direction, price)
        inst = evaluate_institutional_confluence(
            enriched, local_i, direction=direction, price=price
        )
        inst_ok = bool(inst.valid)

        for mode, ok in (("before", loose_ok), ("after", inst_ok)):
            if not ok:
                continue
            raw[mode] += 1
            false_d[mode] += 1
            if is_false_breakout(df, i, direction, price, float(setup.stop_loss)):
                false_n[mode] += 1

            if float(setup.confidence) < min_conf:
                continue
            # stash score in metadata for after mode
            setup_meta = deepcopy(setup)
            if mode == "after":
                setup_meta.metadata = dict(setup_meta.metadata or {})
                setup_meta.metadata.update(
                    {
                        "ob_fvg_confluence_score": inst.total,
                        "ob_fvg_overlap_pct": inst.overlap_pct,
                        "institutional_ob_valid": True,
                    }
                )
            prob = score_meta(meta, setup_meta, enriched, ts)
            if prob is None or prob < meta_th:
                continue
            meta_acc[mode] += 1
            cands[mode].append(
                {
                    "i": i,
                    "day": str(ts.date()),
                    "direction": direction,
                    "entry": price,
                    "sl": float(setup.stop_loss),
                    "tp": float(setup.take_profit),
                    "confluence": float(inst.total) if mode == "after" else None,
                }
            )

    table = {}
    for mode in ("before", "after"):
        traded = apply_trade_filter(cands[mode], cd, max_day)
        rs = [
            simulate_r(df, c["i"], c["direction"], c["entry"], c["sl"], c["tp"])
            for c in traded
        ]
        m = metrics_from_rs(rs)
        fb = (100.0 * false_n[mode] / false_d[mode]) if false_d[mode] else 0.0
        table[mode] = {
            "raw_setups": int(raw[mode]),
            "meta_accepted": int(meta_acc[mode]),
            "profit_factor": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "false_breakout_rate": round(fb, 2),
            "final_trades": m["trades"],
            "win_rate": m["win_rate"],
            "max_dd": m["max_dd"],
        }
        print(mode, json.dumps(table[mode]), flush=True)

    b, a = table["before"], table["after"]
    raw_red = ((b["raw_setups"] - a["raw_setups"]) / max(b["raw_setups"], 1)) * 100.0
    meta_red = ((b["meta_accepted"] - a["meta_accepted"]) / max(b["meta_accepted"], 1)) * 100.0
    pf_delta = a["profit_factor"] - b["profit_factor"]
    exp_delta = a["expectancy_R"] - b["expectancy_R"]
    fb_delta = a["false_breakout_rate"] - b["false_breakout_rate"]

    # Valid if quality improves: PF up or expectancy up, AND false breakouts down (or flat with PF up)
    valid = bool(
        (pf_delta > 0 or exp_delta > 0)
        and fb_delta <= 0
        and a["raw_setups"] > 0
    )
    # Recommend only if valid and after is not worse expectancy with tiny sample
    recommend = bool(
        valid
        and a["final_trades"] >= 10
        and (a["profit_factor"] >= b["profit_factor"] or a["expectancy_R"] > b["expectancy_R"])
        and a["false_breakout_rate"] <= b["false_breakout_rate"]
    )

    lines = [
        "PHASE 16B OB + FVG Institutional Confluence (Research Only)",
        "DATA=XAUUSD_M5_90d.parquet",
        "PATCH_APPLIED=NO",
        "BEFORE=loose OB touch/near (current)",
        "AFTER=institutional OB+FVG confluence (5 rules)",
        "",
        f"raw_setups_before={b['raw_setups']}",
        f"raw_setups_after={a['raw_setups']}",
        f"meta_accepted_before={b['meta_accepted']}",
        f"meta_accepted_after={a['meta_accepted']}",
        f"PF_before={b['profit_factor']}",
        f"PF_after={a['profit_factor']}",
        f"expectancy_before={b['expectancy_R']}",
        f"expectancy_after={a['expectancy_R']}",
        f"false_breakout_rate_before={b['false_breakout_rate']}",
        f"false_breakout_rate_after={a['false_breakout_rate']}",
        "",
        f"final_trades_before={b['final_trades']} win_rate_before={b['win_rate']}",
        f"final_trades_after={a['final_trades']} win_rate_after={a['win_rate']}",
        "",
        "PHASE_16B_RESULT",
        f"RAW_REDUCTION_PCT={round(raw_red, 2)}",
        f"META_ACCEPTED_REDUCTION_PCT={round(meta_red, 2)}",
        f"PF_DELTA={round(pf_delta, 4)}",
        f"EXPECTANCY_DELTA={round(exp_delta, 4)}",
        f"FALSE_BREAKOUT_DELTA={round(fb_delta, 2)}",
        f"INSTITUTIONAL_CONFLUENCE_VALID={'YES' if valid else 'NO'}",
        f"RECOMMENDED_FOR_PA_ENGINE={'YES' if recommend else 'NO'}",
    ]
    text = "\n".join(lines) + "\n"
    out = ROOT / "logs" / "phase16b_ob_fvg_result.txt"
    out.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase16b_ob_fvg_result.json").write_text(
        json.dumps({"before": b, "after": a, "valid": valid, "recommend": recommend}, indent=2),
        encoding="utf-8",
    )
    print(text)
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())