#!/usr/bin/env python3
"""PHASE 23A - multi-strategy alpha discovery lab (research-only, no live patches)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
from tradingbot.domain.pa_hardening import session_label

OUT = ROOT / "logs" / "phase23a"
SYMBOL = "XAUUSD"
N_SLICES = 5
N_WF_FOLDS = 3
K_PURGE = 5
MC_BOOT = 2000
MC_SEED = 20260818
HORIZON = 96
EMBARGO = 96
LONDON_OPEN_MIN = 7 * 60
SESSION_END_MIN = 12 * 60
TOTAL_TRIALS = 7

ORB_CONFIGS: list[dict[str, Any]] = [
    {"strategy_id": "ORB_15M_RETEST", "range_minutes": 15, "atr_break": 0.20, "require_retest": True, "target_R": 2.0, "sl_pad_atr": 0.15},
    {"strategy_id": "ORB_30M_CONT", "range_minutes": 30, "atr_break": 0.25, "require_retest": False, "target_R": 2.0, "sl_pad_atr": 0.15},
    {"strategy_id": "ORB_60M_CONT", "range_minutes": 60, "atr_break": 0.30, "require_retest": False, "target_R": 1.5, "sl_pad_atr": 0.20},
]

MOM_CONFIGS: list[dict[str, Any]] = [
    {"strategy_id": "MOM_30M", "horizon_minutes": 30, "move_atr": 0.35, "confirm_bars": 2, "target_R": 2.0, "sl_atr": 0.35},
    {"strategy_id": "MOM_60M", "horizon_minutes": 60, "move_atr": 0.45, "confirm_bars": 3, "target_R": 2.0, "sl_atr": 0.35},
    {"strategy_id": "MOM_90M", "horizon_minutes": 90, "move_atr": 0.55, "confirm_bars": 3, "target_R": 1.8, "sl_atr": 0.40},
]


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_phase22a():
    path = ROOT / "scripts" / "phase22a_strategy_discovery.py"
    spec = importlib.util.spec_from_file_location("phase22a_strategy_discovery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load phase22a_strategy_discovery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def slice_edges(n: int, n_slices: int) -> np.ndarray:
    return np.linspace(0, n, n_slices + 1, dtype=int)


def filter_range(rows: list[dict[str, Any]], lo: int, hi: int) -> list[dict[str, Any]]:
    return [r for r in rows if lo <= int(r["i"]) < hi]

def build_ctx(p22a, df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    hours = np.array([int(ts.hour) for ts in df.index])
    dates = np.array([ts.date().isoformat() for ts in df.index])
    day_min = np.array([int(ts.hour) * 60 + int(ts.minute) for ts in df.index])
    regime = p22a.infer_regimes(df)
    return {
        "n": n,
        "index": df.index,
        "hours": hours,
        "dates": dates,
        "day_min": day_min,
        "high": high,
        "low": low,
        "close": close,
        "open": open_,
        "atr": atr,
        "regime": regime,
        "df": df,
    }


def model_a_cfg() -> dict[str, Any]:
    return {
        "M5_USE_LONDON_SESSION": False,
        "M5_USE_NY_SESSION": True,
        "NY_ENTRY_START_UTC": 15,
        "NY_ENTRY_END_UTC": 16,
        "ASIAN_START_HOUR": 0,
        "ASIAN_SESSION_END_UTC": 7,
        "ENABLE_CHOCH_CONTINUATION": False,
        "M5_REQUIRE_REJECTION": True,
        "MIN_RR": 1.8,
        "MIN_RANGE_ATR": 0.25,
        "SWEEP_LOOKBACK_BARS": 12,
        "SWEEP_BUFFER_ATR": 0.15,
        "SL_ATR_MULT": 0.35,
    }


def collect_model_a(p22a, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    df = ctx["df"]
    n = ctx["n"]
    high, low, close, open_, hours = ctx["high"], ctx["low"], ctx["close"], ctx["open"], ctx["hours"]
    atr, regime = ctx["atr"], ctx["regime"]
    index, dates = ctx["index"], ctx["dates"]
    atr_pct_arr = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct_arr = np.where(np.isnan(atr_pct_arr), 50.0, atr_pct_arr)
    cfg = model_a_cfg()
    asian = p22a.precompute_asian(dates, hours, high, low, n, int(cfg["ASIAN_SESSION_END_UTC"]))
    roll_hi = pd.Series(high).rolling(p22a.SWEEP_LB + 1, min_periods=1).max().to_numpy()
    roll_lo = pd.Series(low).rolling(p22a.SWEEP_LB + 1, min_periods=1).min().to_numpy()
    out: list[dict[str, Any]] = []
    for i in range(80, n - 3):
        if not (15 <= int(hours[i]) < 16):
            continue
        bounds = asian.get(dates[i])
        if bounds is None:
            continue
        asian_hi, asian_lo = bounds
        a = float(atr[i])
        if a <= 0 or (asian_hi - asian_lo) < a * float(cfg.get("MIN_RANGE_ATR", 0.25)):
            continue
        buf = a * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
        wh, wl = float(roll_hi[i]), float(roll_lo[i])
        price = float(close[i])
        if not (
            (wh > asian_hi + buf and asian_lo < price < asian_hi)
            or (wl < asian_lo - buf and asian_lo < price < asian_hi)
        ):
            continue
        sp = p22a.variable_spread_pips(p22a.BASE_SPREAD, int(hours[i]))
        if sp > p22a.MAX_SPREAD or not (p22a.ATR_MIN <= float(atr_pct_arr[i]) <= p22a.ATR_MAX):
            continue
        setup = evaluate_m5_london_sweep(df, i, cfg)
        if setup is None:
            continue
        direction = int(setup.direction)
        ts = index[i]
        row: dict[str, Any] = {
            "i": i,
            "timestamp": ts.isoformat(),
            "symbol": SYMBOL,
            "day": dates[i],
            "hour": int(hours[i]),
            "direction": "BUY" if direction > 0 else "SELL",
            "dir": direction,
            "strategy_id": "MODEL_A_LONDON_SWEEP",
            "regime": str(regime[i]),
            "session": session_label(ts.to_pydatetime()),
            "sl": float(setup.stop_loss),
            "tp": float(setup.take_profit),
        }
        out.append(p22a.annotate_fill(row, high, low, close, open_, n, hours))
    return out

def _opening_range(ctx: dict[str, Any], day: str, range_minutes: int) -> tuple[float, float, int] | None:
    day_min, dates, high, low = ctx["day_min"], ctx["dates"], ctx["high"], ctx["low"]
    end = LONDON_OPEN_MIN + range_minutes
    idxs = [i for i, d in enumerate(dates) if d == day and LONDON_OPEN_MIN <= int(day_min[i]) < end]
    if len(idxs) < 3:
        return None
    or_hi = float(np.max(high[idxs]))
    or_lo = float(np.min(low[idxs]))
    if or_hi <= or_lo:
        return None
    return or_hi, or_lo, int(idxs[-1])

def collect_orb_variant(p22a, ctx: dict[str, Any], cfg_orb: dict[str, Any]) -> list[dict[str, Any]]:
    n = ctx["n"]
    high, low, close, open_ = ctx["high"], ctx["low"], ctx["close"], ctx["open"]
    atr, hours, dates, day_min = ctx["atr"], ctx["hours"], ctx["dates"], ctx["day_min"]
    regime, index = ctx["regime"], ctx["index"]
    range_min = int(cfg_orb["range_minutes"])
    atr_break = float(cfg_orb["atr_break"])
    require_retest = bool(cfg_orb["require_retest"])
    target_r = float(cfg_orb["target_R"])
    sl_pad = float(cfg_orb["sl_pad_atr"])
    sid = str(cfg_orb["strategy_id"])
    range_end = LONDON_OPEN_MIN + range_min
    out: list[dict[str, Any]] = []
    used_days: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}
    for i in range(30, n - 3):
        if int(day_min[i]) < range_end or int(day_min[i]) >= SESSION_END_MIN:
            continue
        day = dates[i]
        if day in used_days:
            continue
        bounds = _opening_range(ctx, day, range_min)
        if bounds is None:
            continue
        or_hi, or_lo, freeze_i = bounds
        if i <= freeze_i:
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        sp = p22a.variable_spread_pips(p22a.BASE_SPREAD, int(hours[i]))
        if sp > p22a.MAX_SPREAD:
            continue
        c = float(close[i])
        buf = atr_break * a
        direction = 0
        if c > or_hi + buf:
            direction = 1
        elif c < or_lo - buf:
            direction = -1
        if direction == 0:
            continue
        if require_retest:
            st = pending.get(day)
            if st is None:
                pending[day] = {"dir": direction, "level": or_hi if direction > 0 else or_lo}
                continue
            if st["dir"] != direction:
                pending.pop(day, None)
                continue
            level = float(st["level"])
            tol = 0.05 * a
            if direction > 0:
                if not (float(low[i]) <= level + tol and c >= level):
                    continue
            elif not (float(high[i]) >= level - tol and c <= level):
                continue
        if direction > 0:
            sl = or_lo - sl_pad * a
            tp = c + target_r * (c - sl)
        else:
            sl = or_hi + sl_pad * a
            tp = c - target_r * (sl - c)
        ts = index[i]
        row: dict[str, Any] = {
            "i": i,
            "timestamp": ts.isoformat(),
            "symbol": SYMBOL,
            "day": day,
            "hour": int(hours[i]),
            "direction": "BUY" if direction > 0 else "SELL",
            "dir": direction,
            "strategy_id": sid,
            "regime": str(regime[i]),
            "session": session_label(ts.to_pydatetime()),
            "sl": float(sl),
            "tp": float(tp),
        }
        out.append(p22a.annotate_fill(row, high, low, close, open_, n, hours))
        used_days.add(day)
        pending.pop(day, None)
    return out


def collect_mom_variant(p22a, ctx: dict[str, Any], cfg_mom: dict[str, Any]) -> list[dict[str, Any]]:
    n = ctx["n"]
    high, low, close, open_ = ctx["high"], ctx["low"], ctx["close"], ctx["open"]
    atr, hours, dates, day_min = ctx["atr"], ctx["hours"], ctx["dates"], ctx["day_min"]
    regime, index = ctx["regime"], ctx["index"]
    horizon = int(cfg_mom["horizon_minutes"])
    move_atr = float(cfg_mom["move_atr"])
    confirm = int(cfg_mom["confirm_bars"])
    target_r = float(cfg_mom["target_R"])
    sl_atr = float(cfg_mom["sl_atr"])
    sid = str(cfg_mom["strategy_id"])
    earliest = LONDON_OPEN_MIN + horizon
    out: list[dict[str, Any]] = []
    used_days: set[str] = set()
    open_price: dict[str, float] = {}
    for i in range(30, n - 3):
        dm = int(day_min[i])
        day = dates[i]
        if dm >= LONDON_OPEN_MIN and day not in open_price:
            open_price[day] = float(open_[i])
        if day in used_days or dm < earliest or dm >= SESSION_END_MIN:
            continue
        anchor = open_price.get(day)
        if anchor is None:
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        sp = p22a.variable_spread_pips(p22a.BASE_SPREAD, int(hours[i]))
        if sp > p22a.MAX_SPREAD:
            continue
        move = float(close[i]) - anchor
        direction = 0
        if move >= move_atr * a:
            direction = 1
        elif move <= -move_atr * a:
            direction = -1
        if direction == 0:
            continue
        ok = True
        for j in range(i - confirm + 1, i + 1):
            if j < 1:
                ok = False
                break
            if direction > 0 and float(close[j]) < float(close[j - 1]):
                ok = False
                break
            if direction < 0 and float(close[j]) > float(close[j - 1]):
                ok = False
                break
        if not ok:
            continue
        c = float(close[i])
        if direction > 0:
            sl = c - sl_atr * a
            tp = c + target_r * (c - sl)
        else:
            sl = c + sl_atr * a
            tp = c - target_r * (sl - c)
        ts = index[i]
        row: dict[str, Any] = {
            "i": i,
            "timestamp": ts.isoformat(),
            "symbol": SYMBOL,
            "day": day,
            "hour": int(hours[i]),
            "direction": "BUY" if direction > 0 else "SELL",
            "dir": direction,
            "strategy_id": sid,
            "regime": str(regime[i]),
            "session": session_label(ts.to_pydatetime()),
            "sl": float(sl),
            "tp": float(tp),
        }
        out.append(p22a.annotate_fill(row, high, low, close, open_, n, hours))
        used_days.add(day)
    return out


def export_trade_row(p22a, t: dict[str, Any]) -> dict[str, Any]:
    hour = int(t.get("hour") or 0)
    slip = float(t.get("slippage_pips") or p22a.variable_slippage_pips(p22a.BASE_SLIP, hour))
    spread = float(t.get("spread_pips") or 0.0)
    risk = abs(float(t.get("entry") or 0) - float(t.get("sl") or 0))
    rr = float(t.get("planned_rr") or 0.0)
    if rr == 0.0 and risk > 0:
        rr = round(abs(float(t.get("tp") or 0) - float(t.get("entry") or 0)) / risk, 2)
    return {
        "timestamp": t.get("timestamp"),
        "symbol": t.get("symbol", SYMBOL),
        "direction": t.get("direction"),
        "strategy_id": t.get("strategy_id"),
        "session": t.get("session"),
        "regime": t.get("regime"),
        "entry": t.get("entry"),
        "SL": t.get("sl"),
        "TP": t.get("tp"),
        "planned_RR": rr,
        "spread": round(spread, 3),
        "slippage": round(slip, 3),
        "MFE_R": t.get("MFE_R"),
        "MAE_R": t.get("MAE_R"),
        "final_R": t.get("final_R"),
        "exit_reason": t.get("exit_reason"),
    }


def summarize_trades(p22a, raw: list[dict[str, Any]], name: str) -> dict[str, Any]:
    trades = p22a.apply_cd(raw)
    rs = [float(t["final_R"]) for t in trades]
    rs_sp = [float(t.get("final_R_spread") or 0.0) for t in trades]
    rs_st = [float(t.get("final_R_stress") or 0.0) for t in trades]
    base = p22a.metrics_from_rs(rs)
    sp = p22a.metrics_from_rs(rs_sp)
    st = p22a.metrics_from_rs(rs_st)
    return {
        "model": name,
        "raw_setups": len(raw),
        **base,
        "pf_after_spread": sp["profit_factor"],
        "exp_after_spread": sp["expectancy_R"],
        "pf_after_stress": st["profit_factor"],
        "exp_after_stress": st["expectancy_R"],
        "trades_export": [export_trade_row(p22a, t) for t in trades],
    }


def cost_variants(trades: list[dict[str, Any]]) -> dict[str, list[float]]:
    out = {
        "normal_spread": [],
        "spread_p25": [],
        "spread_p50": [],
        "realistic_slip": [],
        "adverse_slip": [],
    }
    for t in trades:
        r = float(t.get("final_R") or 0.0)
        cs = float(t.get("cost_spread_R") or 0.0)
        ct = float(t.get("cost_stress_R") or cs)
        slip = max(0.0, ct - cs)
        out["normal_spread"].append(r - cs)
        out["spread_p25"].append(r - 1.25 * cs)
        out["spread_p50"].append(r - 1.50 * cs)
        out["realistic_slip"].append(r - ct)
        out["adverse_slip"].append(r - (1.25 * cs + 1.50 * slip))
    return out


def pick_variant(p22a, variants: dict[str, list[dict[str, Any]]], lo: int, hi: int) -> str:
    best_id = next(iter(variants))
    best_score = -1e18
    for sid, raw in variants.items():
        sub = filter_range(raw, lo, hi)
        m = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(sub)])
        score = float(m["expectancy_R"]) + 0.05 * float(m["profit_factor"])
        if int(m["trades"]) >= 4 and score > best_score:
            best_score = score
            best_id = sid
    return best_id


def oos_stability(p22a, trades: list[dict[str, Any]]) -> str:
    if len(trades) < 12:
        return "NO"
    reg_ok = p22a.stability(trades, "regime")
    sess_ok = p22a.stability(trades, "session")
    return "YES" if reg_ok and sess_ok else "NO"


def walk_forward(p22a, raw_map: dict[str, list[dict[str, Any]]], n: int) -> dict[str, Any]:
    edges = slice_edges(n, N_SLICES)
    folds = []
    for k in range(N_WF_FOLDS):
        train_lo, train_hi = int(edges[0]), int(edges[k + 1])
        oos_lo, oos_hi = int(edges[k + 2]), int(edges[k + 3])
        embargo_cut = max(train_lo, oos_lo - EMBARGO)
        fold: dict[str, Any] = {"fold": k + 1, "models": {}}
        for key, raw in raw_map.items():
            train_raw = [r for r in filter_range(raw, train_lo, train_hi) if int(r["i"]) + HORIZON < embargo_cut]
            oos_raw = filter_range(raw, oos_lo, oos_hi)
            tr = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(train_raw)])
            oo = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(oos_raw)])
            fold["models"][key] = {"research": tr, "oos": oo}
        folds.append(fold)
    oos_lo0, oos_hiN = int(edges[2]), int(edges[-1])
    pooled: dict[str, Any] = {}
    pooled_trades: dict[str, list[dict[str, Any]]] = {}
    for key, raw in raw_map.items():
        oos_raw = filter_range(raw, oos_lo0, oos_hiN)
        trades = p22a.apply_cd(oos_raw)
        pooled[key] = p22a.metrics_from_rs([float(t["final_R"]) for t in trades])
        pooled_trades[key] = trades
    return {
        "slices": [int(x) for x in edges],
        "folds": folds,
        "pooled_oos": pooled,
        "pooled_oos_trades": pooled_trades,
        "research_bar_range": [0, int(edges[2])],
    }


def purged_cv(p22a, raw: list[dict[str, Any]], n: int) -> dict[str, Any]:
    edges = slice_edges(n, K_PURGE)
    test_metrics = []
    folds = []
    for k in range(K_PURGE):
        test_lo, test_hi = int(edges[k]), int(edges[k + 1])
        test_raw = filter_range(raw, test_lo, test_hi)
        train_raw = []
        for r in raw:
            i = int(r["i"])
            t0, t1 = i, i + HORIZON
            overlaps = not (t1 + EMBARGO < test_lo or t0 > test_hi + EMBARGO)
            if overlaps or (test_lo <= i < test_hi):
                continue
            train_raw.append(r)
        te = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(test_raw)])
        tr = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(train_raw)])
        folds.append({"fold": k + 1, "train": tr, "test": te})
        if int(te["trades"]) > 0:
            test_metrics.append(te)
    if test_metrics:
        pfs = [float(m["profit_factor"]) for m in test_metrics]
        exps = [float(m["expectancy_R"]) for m in test_metrics]
        agg = {
            "mean_test_pf": round(float(np.mean(pfs)), 3),
            "min_test_pf": round(float(np.min(pfs)), 3),
            "mean_test_exp_R": round(float(np.mean(exps)), 4),
        }
    else:
        agg = {"mean_test_pf": 0.0, "min_test_pf": 0.0, "mean_test_exp_R": 0.0}
    return {"k": K_PURGE, "folds": folds, "aggregate": agg}


def monte_carlo(p22a, trades: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    rs = np.array([float(t["final_R"]) for t in trades], dtype=float)
    rng = np.random.default_rng(seed)
    nn = len(rs)
    if nn == 0:
        return {"bootstrap": {"p05_pf": 0.0, "median_pf": 0.0}}
    boot_pf = np.empty(MC_BOOT, dtype=float)
    for b in range(MC_BOOT):
        sample = rng.choice(rs, size=nn, replace=True)
        boot_pf[b] = float(p22a.metrics_from_rs(sample.tolist())["profit_factor"])
    return {
        "n_trades": nn,
        "bootstrap": {
            "median_pf": round(float(np.median(boot_pf)), 3),
            "p05_pf": round(float(np.percentile(boot_pf, 5)), 3),
            "p95_pf": round(float(np.percentile(boot_pf, 95)), 3),
        },
    }


def pick_best_model_key(metrics: dict[str, dict[str, Any]]) -> str:
    best = "A"
    best_pf = -1.0
    for key in ("A", "B", "C"):
        m = metrics[key]
        if int(m.get("trades") or 0) < 8:
            continue
        pf = float(m.get("profit_factor") or 0.0)
        if pf > best_pf:
            best_pf = pf
            best = key
    if best_pf >= 0:
        return best
    for key in ("A", "B", "C"):
        pf = float(metrics[key].get("profit_factor") or 0.0)
        if pf > best_pf:
            best_pf = pf
            best = key
    return best


def candidate_phase23b(key: str, summaries: dict[str, dict[str, Any]], wf: dict[str, Any]) -> bool:
    m180 = summaries["180d"][key]
    m90 = summaries["90d"][key]
    m30 = summaries["30d"][key]
    if int(m180["trades"]) < 10:
        return False
    if float(m180["profit_factor"]) < 1.0 or float(m180["expectancy_R"]) < 0:
        return False
    ok_other = 0
    for o in (m90, m30):
        if int(o["trades"]) >= 5 and (float(o["profit_factor"]) >= 1.0 or float(o["expectancy_R"]) >= 0):
            ok_other += 1
    folds_ok = 0
    for fold in wf["folds"]:
        cell = fold["models"][key]["oos"]
        if int(cell["trades"]) >= 3 and float(cell["profit_factor"]) >= 0.9:
            folds_ok += 1
    return ok_other >= 1 and folds_ok >= 2


def overfit_risk(is_pf: float, oos_pf: float, pcv_min: float) -> str:
    if is_pf > 0 and oos_pf < is_pf * 0.65:
        return "HIGH"
    if pcv_min < 0.85 or oos_pf < 1.0:
        return "MEDIUM"
    return "LOW"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p22a = load_phase22a()
    df = p22a.load_df()
    n = len(df)
    emit("DF bars=%s %s -> %s" % (n, df.index.min(), df.index.max()))
    ctx = build_ctx(p22a, df)

    emit("MODEL A: evaluate_m5_london_sweep hour 15-16 UTC ...")
    raw_a = collect_model_a(p22a, ctx)
    emit("  raw=%s" % len(raw_a))

    orb_variants: dict[str, list[dict[str, Any]]] = {}
    for cfg in ORB_CONFIGS:
        sid = str(cfg["strategy_id"])
        emit("MODEL B variant %s ..." % sid)
        orb_variants[sid] = collect_orb_variant(p22a, ctx, cfg)
        emit("  raw=%s" % len(orb_variants[sid]))

    mom_variants: dict[str, list[dict[str, Any]]] = {}
    for cfg in MOM_CONFIGS:
        sid = str(cfg["strategy_id"])
        emit("MODEL C variant %s ..." % sid)
        mom_variants[sid] = collect_mom_variant(p22a, ctx, cfg)
        emit("  raw=%s" % len(mom_variants[sid]))

    edges = slice_edges(n, N_SLICES)
    research_hi = int(edges[2])
    pick_orb = pick_variant(p22a, orb_variants, 0, research_hi)
    pick_mom = pick_variant(p22a, mom_variants, 0, research_hi)
    emit("research [0,%s) picks ORB=%s MOM=%s" % (research_hi, pick_orb, pick_mom))

    raw_b = orb_variants[pick_orb]
    raw_c = mom_variants[pick_mom]
    models_raw = {"A": raw_a, "B": raw_b, "C": raw_c}
    model_names = {"A": "MODEL_A_LONDON_SWEEP", "B": pick_orb, "C": pick_mom}

    windows = {
        "180d": np.arange(n),
        "90d": p22a.slice_by_days(df, 90),
        "30d": p22a.slice_by_days(df, 30),
    }
    summaries: dict[str, dict[str, dict[str, Any]]] = {}
    matrix_windows: dict[str, Any] = {}
    for wname, idx in windows.items():
        summaries[wname] = {}
        matrix_windows[wname] = {}
        allowed = set(int(x) for x in idx)
        for key, raw in models_raw.items():
            sub = p22a.filter_idx(raw, allowed)
            s = summarize_trades(p22a, sub, model_names[key])
            summaries[wname][key] = s
            matrix_windows[wname][model_names[key]] = {k: v for k, v in s.items() if k != "trades_export"}
            emit(
                "  %s %s trades=%s PF=%s ExpR=%s"
                % (wname, key, s["trades"], s["profit_factor"], s["expectancy_R"])
            )

    emit("walk-forward ...")
    wf = walk_forward(p22a, models_raw, n)

    best_key = pick_best_model_key(summaries["180d"])
    best_raw = models_raw[best_key]
    best_oos_trades = wf["pooled_oos_trades"][best_key]
    eval_trades = best_oos_trades if best_oos_trades else p22a.apply_cd(best_raw)

    emit("purged CV + Monte Carlo on best model ...")
    pcv = purged_cv(p22a, best_raw, n)
    cost_metrics = {k: p22a.metrics_from_rs(v) for k, v in cost_variants(eval_trades).items()}
    mc = monte_carlo(p22a, eval_trades, MC_SEED)

    wf_pfs = [float(fold["models"][best_key]["oos"]["profit_factor"]) for fold in wf["folds"]]
    wf_exps = [float(fold["models"][best_key]["oos"]["expectancy_R"]) for fold in wf["folds"]]
    wf_pf = round(float(np.mean(wf_pfs)), 3) if wf_pfs else 0.0
    wf_exp = round(float(np.mean(wf_exps)), 4) if wf_exps else 0.0

    stab = {
        "A": oos_stability(p22a, wf["pooled_oos_trades"]["A"]),
        "B": oos_stability(p22a, wf["pooled_oos_trades"]["B"]),
        "C": oos_stability(p22a, wf["pooled_oos_trades"]["C"]),
    }

    best30 = pick_best_model_key(summaries["30d"])
    best90 = pick_best_model_key(summaries["90d"])
    best180 = pick_best_model_key(summaries["180d"])

    is_m = wf["folds"][0]["models"][best_key]["research"] if wf["folds"] else summaries["180d"][best_key]
    oos_m = wf["pooled_oos"][best_key]
    risk = overfit_risk(
        float(is_m.get("profit_factor") or 0),
        float(oos_m.get("profit_factor") or 0),
        float(pcv["aggregate"]["min_test_pf"]),
    )

    cands = [model_names[k] for k in ("A", "B", "C") if candidate_phase23b(k, summaries, wf)]

    orb_results = {}
    for sid, raw in orb_variants.items():
        sub = filter_range(raw, 0, research_hi)
        research_m = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(sub)])
        full_m = summarize_trades(p22a, raw, sid)
        orb_results[sid] = {
            "research_metrics": research_m,
            "full_metrics": {k: v for k, v in full_m.items() if k != "trades_export"},
            "selected": sid == pick_orb,
            "trades": full_m["trades_export"],
        }

    mom_results = {}
    for sid, raw in mom_variants.items():
        sub = filter_range(raw, 0, research_hi)
        research_m = p22a.metrics_from_rs([float(t["final_R"]) for t in p22a.apply_cd(sub)])
        full_m = summarize_trades(p22a, raw, sid)
        mom_results[sid] = {
            "research_metrics": research_m,
            "full_metrics": {k: v for k, v in full_m.items() if k != "trades_export"},
            "selected": sid == pick_mom,
            "trades": full_m["trades_export"],
        }

    matrix = {
        "phase": "23A",
        "meta_used": False,
        "live_files_modified": False,
        "bars": n,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "total_trials_tested": TOTAL_TRIALS,
        "research_bar_range": [0, research_hi],
        "selected_orb": pick_orb,
        "selected_momentum": pick_mom,
        "cost_stress_labels": {
            "spread_p25": "+25% spread",
            "spread_p50": "+50% spread",
            "realistic_slip": "realistic slippage",
            "adverse_slip": "adverse slippage",
        },
        "windows": matrix_windows,
        "walk_forward": wf,
        "purged_cv_best_model": pcv,
        "cost_stress_best_oos": cost_metrics,
        "monte_carlo_best": mc,
        "best_model": best_key,
    }

    result = "\n".join(
        [
            "PHASE_23A_RESULT",
            "MODEL_A_PF=%s" % summaries["180d"]["A"]["profit_factor"],
            "MODEL_A_EXP_R=%s" % summaries["180d"]["A"]["expectancy_R"],
            "MODEL_A_OOS_STABILITY=%s" % stab["A"],
            "MODEL_B_PF=%s" % summaries["180d"]["B"]["profit_factor"],
            "MODEL_B_EXP_R=%s" % summaries["180d"]["B"]["expectancy_R"],
            "MODEL_B_OOS_STABILITY=%s" % stab["B"],
            "MODEL_C_PF=%s" % summaries["180d"]["C"]["profit_factor"],
            "MODEL_C_EXP_R=%s" % summaries["180d"]["C"]["expectancy_R"],
            "MODEL_C_OOS_STABILITY=%s" % stab["C"],
            "BEST_MODEL=%s" % best_key,
            "BEST_MODEL_30D=%s" % best30,
            "BEST_MODEL_90D=%s" % best90,
            "BEST_MODEL_180D=%s" % best180,
            "BEST_MODEL_COST_STRESS_PF=%s" % cost_metrics["adverse_slip"]["profit_factor"],
            "BEST_MODEL_MC_P05_PF=%s" % mc["bootstrap"]["p05_pf"],
            "BEST_MODEL_WF_PF=%s" % wf_pf,
            "BEST_MODEL_WF_EXPR=%s" % wf_exp,
            "TOTAL_TRIALS_TESTED=%s" % TOTAL_TRIALS,
            "OVERFIT_RISK=%s" % risk,
            "CANDIDATES_FOR_PHASE23B=%s" % (",".join(cands) if cands else "NONE"),
            "LIVE_PATCH_APPLIED=NO",
            "",
        ]
    )

    (OUT / "strategy_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    (OUT / "orb_results.json").write_text(json.dumps(orb_results, indent=2, default=str), encoding="utf-8")
    (OUT / "intraday_momentum_results.json").write_text(json.dumps(mom_results, indent=2, default=str), encoding="utf-8")
    (OUT / "phase23a_result.txt").write_text(result, encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())