#!/usr/bin/env python3
"""PHASE 14C-1 Session Window Recovery — research only (10-17 vs 9-17)."""
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

LOOKBACK = 500
NY_END = 17
WINDOWS = {"BASELINE": 10, "TEST_WINDOW": 9}
DATASETS = ["30d", "60d", "90d"]


def load_df(tag: str):
    import pandas as pd
    path = ROOT / "data" / "cache" / f"XAUUSD_M5_{tag}.parquet"
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


def run_dataset(tag: str, meta) -> dict[str, dict[str, Any]]:
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.price_action import enrich_price_action

    df = load_df(tag)
    print(f"[{tag}] bars={len(df)} {df.index[0]} -> {df.index[-1]}", flush=True)
    cfgs = {name: make_cfg(start) for name, start in WINDOWS.items()}
    enrich_cfg = cfgs["TEST_WINDOW"]
    meta_th = float(enrich_cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_conf = float(enrich_cfg.get("MIN_CONFIDENCE", 0.52))
    cd = int(enrich_cfg.get("COOLDOWN_BARS", 18))
    max_day = int(enrich_cfg.get("MAX_TRADES_PER_DAY", 3))

    raw = Counter()
    cands = defaultdict(list)
    scanned = 0
    start_i = max(LOOKBACK, 60)
    for i in range(start_i, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        h = ts.hour
        if not (9 <= h < 17):  # cover both windows with one enrich
            continue
        scanned += 1
        if scanned % 1500 == 0:
            print(f"[{tag}] progress={scanned}", flush=True)
        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, enrich_cfg, at_index=local_i)
        for name, cfg in cfgs.items():
            start = WINDOWS[name]
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

    out = {}
    for name, start in WINDOWS.items():
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
        out[name] = {
            "window": f"{start}-{NY_END}",
            "raw_setups": int(raw[name]),
            "meta_accepted": len(cands[name]),
            "win_rate": m["win_rate"],
            "profit_factor": m["profit_factor"],
            "expectancy_R": m["expectancy_R"],
            "max_drawdown_R": m["max_drawdown_R"],
            "final_signals": m["final_signals"],
        }
        print(f"[{tag}] {name}={json.dumps(out[name])}", flush=True)
    return out


def gate_check(base: dict, test: dict) -> dict[str, Any]:
    raw_inc = ((test["raw_setups"] - base["raw_setups"]) / max(base["raw_setups"], 1)) * 100.0
    pf_drop = ((base["profit_factor"] - test["profit_factor"]) / max(base["profit_factor"], 1e-9)) * 100.0 if base["profit_factor"] > 0 else 999.0
    exp_pos = test["expectancy_R"] > 0
    dd_inc = test["max_drawdown_R"] - base["max_drawdown_R"]
    ok = (
        raw_inc >= 25.0
        and pf_drop <= 10.0
        and exp_pos
        and dd_inc <= 1.0
    )
    return {
        "raw_setups_increase_pct": round(raw_inc, 2),
        "pf_drop_pct": round(pf_drop, 2),
        "expectancy_stays_positive": "YES" if exp_pos else "NO",
        "max_dd_increase_R": round(dd_inc, 3),
        "gates_pass": "YES" if ok else "NO",
    }


def main() -> int:
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler
    reload_meta_labeler()
    meta = MetaLabeler()

    all_res = {}
    for tag in DATASETS:
        all_res[tag] = run_dataset(tag, meta)

    # primary certification on 90d; also require no catastrophic fail on 30/60
    primary = all_res["90d"]
    base = primary["BASELINE"]
    test = primary["TEST_WINDOW"]
    g90 = gate_check(base, test)
    gates = {tag: gate_check(all_res[tag]["BASELINE"], all_res[tag]["TEST_WINDOW"]) for tag in DATASETS}
    certified = all(g["gates_pass"] == "YES" for g in gates.values())
    # safe live only if certified
    safe = "YES" if certified else "NO"
    rec = "09-17" if certified else "10-17"

    lines = [
        "PHASE 14C-1 Session Window Recovery (Research Only)",
        "BASELINE=10-17 UTC | TEST_WINDOW=09-17 UTC",
        "",
    ]
    for tag in DATASETS:
        lines.append(f"=== {tag} ===")
        lines.append("| Window | Raw Setups | Meta Accepted | Win Rate | PF | Expectancy R | Max DD |")
        lines.append("| ------ | ---------- | ------------- | -------- | -- | ------------ | ------ |")
        for name in ("BASELINE", "TEST_WINDOW"):
            r = all_res[tag][name]
            lines.append(
                f"| {name} {r['window']} | {r['raw_setups']} | {r['meta_accepted']} | {r['win_rate']} | "
                f"{r['profit_factor']} | {r['expectancy_R']} | {r['max_drawdown_R']} |"
            )
        g = gates[tag]
        lines.append(
            f"gates {tag}: raw_inc={g['raw_setups_increase_pct']}% pf_drop={g['pf_drop_pct']}% "
            f"exp_pos={g['expectancy_stays_positive']} dd_inc={g['max_dd_increase_R']}R pass={g['gates_pass']}"
        )
        lines.append("")

    lines.append("PHASE_14C_1_RESULT")
    lines.append(f"BASELINE_RAW={base['raw_setups']}")
    lines.append(f"TEST_RAW={test['raw_setups']}")
    lines.append(f"RAW_INCREASE_PCT={g90['raw_setups_increase_pct']}")
    lines.append(f"BASELINE_PF={base['profit_factor']}")
    lines.append(f"TEST_PF={test['profit_factor']}")
    lines.append(f"BASELINE_EXPECTANCY_R={base['expectancy_R']}")
    lines.append(f"TEST_EXPECTANCY_R={test['expectancy_R']}")
    lines.append(f"BASELINE_MAX_DD_R={base['max_drawdown_R']}")
    lines.append(f"TEST_MAX_DD_R={test['max_drawdown_R']}")
    lines.append(f"SESSION_RECOVERY_CERTIFIED={'YES' if certified else 'NO'}")
    lines.append(f"SAFE_LIVE_PATCH={safe}")
    lines.append(f"RECOMMENDED_WINDOW={rec}")
    lines.append("NOTE=RESULT metrics from 90d primary; certification requires gates on 30d+60d+90d")
    lines.append("PATCH_APPLIED=NO")

    text = "\n".join(lines) + "\n"
    out = ROOT / "logs" / "phase14c1_session_window_recovery.txt"
    out.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase14c1_session_window_recovery.json").write_text(
        json.dumps({"datasets": all_res, "gates": gates, "certified": certified, "recommended": rec}, indent=2),
        encoding="utf-8",
    )
    print(text)
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
