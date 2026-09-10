#!/usr/bin/env python3
"""PHASE 14C-1 NY window research — fast lookback enrich."""
from __future__ import annotations

import json, os, sys
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

SCENARIOS = {"baseline": 10, "candidate_1": 9, "candidate_2": 8}
NY_END = 17
LOOKBACK = 500


def load_df():
    import pandas as pd
    path = ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet"
    if not path.is_file():
        path = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    cutoff = df.index.max() - pd.Timedelta(days=90)
    df = df[df.index >= cutoff].copy()
    if "atr" not in df.columns:
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df


def make_cfg(ny_start: int) -> dict[str, Any]:
    from tradingbot.config.price_action import get_price_action_config
    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    cfg["NY_ENTRY_START_HOUR"] = ny_start
    cfg["NY_ENTRY_END_HOUR"] = NY_END
    cfg["SESSION_START_HOUR"] = ny_start
    cfg["SESSION_END_HOUR"] = NY_END
    cfg["M5_USE_NY_SESSION"] = True
    cfg["M5_USE_LONDON_SESSION"] = False
    return cfg


def simulate_r(df, i, direction, entry, sl, tp, max_bars=96) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    end = min(len(df), i + 1 + max_bars)
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j]); lo = float(df["low"].iloc[j])
        if direction > 0:
            if lo <= sl: return round((sl - entry) / risk, 4)
            if hi >= tp: return round((tp - entry) / risk, 4)
        else:
            if hi >= sl: return round((entry - sl) / risk, 4)
            if lo <= tp: return round((entry - tp) / risk, 4)
    close = float(df["close"].iloc[end - 1])
    return round(((close - entry) if direction > 0 else (entry - close)) / risk, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"final_signals": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "max_drawdown_R": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = max(mdd, peak - eq)
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
            direction=direction, confidence=float(setup.confidence), symbol="XAUUSD", timeframe="M5",
            strategy_name="priceaction", stop_loss=float(setup.stop_loss), take_profit=float(setup.take_profit),
            metadata=dict(setup.metadata or {}), created_at=ts,
        )
        return float(meta.score(sig, {"symbol": "XAUUSD", "timeframe": "M5", "regime": "TREND", "ohlcv": enriched}, "TREND"))
    except Exception:
        return None


def main() -> int:
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler

    reload_meta_labeler()
    meta = MetaLabeler()
    df = load_df()
    print(f"DF bars={len(df)} first={df.index[0]} last={df.index[-1]}", flush=True)
    cfgs = {name: make_cfg(start) for name, start in SCENARIOS.items()}
    enrich_cfg = cfgs["candidate_2"]
    meta_th = float(enrich_cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_conf = float(enrich_cfg.get("MIN_CONFIDENCE", 0.52))
    cd = int(enrich_cfg.get("COOLDOWN_BARS", 18))
    max_day = int(enrich_cfg.get("MAX_TRADES_PER_DAY", 3))

    raw = Counter()
    cands = defaultdict(list)
    scanned = 0
    for i in range(LOOKBACK, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        h = ts.hour
        if not (8 <= h < 17):
            continue
        scanned += 1
        if scanned % 1000 == 0:
            print(f"progress scanned={scanned}", flush=True)
        # fixed lookback slice (local index = LOOKBACK-1 ... end)
        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, enrich_cfg, at_index=local_i)
        for name, cfg in cfgs.items():
            start = SCENARIOS[name]
            if not (start <= h < NY_END):
                continue
            setup = evaluate_gold_setup(enriched, local_i, cfg, timeframe="M5")
            if setup is None:
                continue
            raw[name] += 1
            if float(setup.confidence) < min_conf:
                continue
            prob = score_meta(meta, setup, enriched, ts)
            if prob is None or prob < meta_th:
                continue
            cands[name].append({
                "i": i, "day": str(ts.date()), "direction": int(setup.direction),
                "entry": float(setup.entry), "sl": float(setup.stop_loss), "tp": float(setup.take_profit),
            })

    results = []
    for name, start in SCENARIOS.items():
        rs = []
        last = -10000
        open_until = -1
        day_counts = Counter()
        for c in cands[name]:
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
        row = {"scenario": name, "ny_window": f"{start}-{NY_END}", "raw_setups": int(raw[name]), "meta_passed": len(cands[name]), **m}
        results.append(row)
        print(json.dumps(row), flush=True)

    base = next(r for r in results if r["scenario"] == "baseline")
    best = max(results, key=lambda r: (r["profit_factor"], r["expectancy_R"], r["final_signals"]))
    safe = "NO"
    rec = "KEEP_BASELINE_10_17"
    for r in results:
        if r["scenario"] == "baseline":
            continue
        if (r["final_signals"] >= base["final_signals"] and r["profit_factor"] >= base["profit_factor"]
            and r["expectancy_R"] >= base["expectancy_R"] - 1e-9
            and r["max_drawdown_R"] <= max(base["max_drawdown_R"] * 1.15, base["max_drawdown_R"] + 0.5)
            and r["raw_setups"] > base["raw_setups"]):
            safe = "YES"
            rec = f"OPTIONAL_PATCH_{r['scenario'].upper()}_{r['ny_window'].replace('-', '_')}"
            best = r
            break
    if safe == "NO" and best["scenario"] != "baseline" and best["raw_setups"] > base["raw_setups"]:
        rec = f"RESEARCH_ONLY_BEST_{best['scenario'].upper()}_NOT_SAFE_TO_PATCH"

    lines = ["PHASE 14C-1 NY Window Recovery Research", ""]
    lines.append("| scenario | NY | raw_setups | final_signals | win_rate | profit_factor | expectancy_R | max_drawdown_R |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        lines.append(f"| {r['scenario']} | {r['ny_window']} | {r['raw_setups']} | {r['final_signals']} | {r['win_rate']} | {r['profit_factor']} | {r['expectancy_R']} | {r['max_drawdown_R']} |")
    lines.append("")
    lines.append("RESULT")
    for r in results:
        p = r["scenario"].upper()
        lines += [f"{p}_RAW_SETUPS={r['raw_setups']}", f"{p}_FINAL_SIGNALS={r['final_signals']}", f"{p}_WIN_RATE={r['win_rate']}", f"{p}_PROFIT_FACTOR={r['profit_factor']}", f"{p}_EXPECTANCY_R={r['expectancy_R']}", f"{p}_MAX_DRAWDOWN_R={r['max_drawdown_R']}"]
    lines += [f"BEST_SCENARIO={best['scenario']}", f"SAFE_TO_PATCH={safe}", f"RECOMMENDED_ACTION={rec}", "PATCH_APPLIED=NO"]
    text = "\n".join(lines) + "\n"
    (ROOT / "logs" / "phase14c1_ny_window_recovery.txt").write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase14c1_ny_window_recovery.json").write_text(json.dumps({"results": results, "best": best, "safe_to_patch": safe, "recommended": rec}, indent=2), encoding="utf-8")
    print(text)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
