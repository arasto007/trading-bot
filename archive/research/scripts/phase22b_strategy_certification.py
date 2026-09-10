#!/usr/bin/env python3
"""PHASE 22B — robust strategy certification (research-only, no live patches).

Certifies only Phase 22A candidates. Model B is the sole 22A candidate.
No parameter search is added. Live files are not modified.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = ROOT / "logs" / "phase22b"
CANDIDATE_22A = "MODEL_B_SWEEP_MSS_FVG"
NAMES = {
    "A": "MODEL_A_CURRENT_PA",
    "B": "MODEL_B_SWEEP_MSS_FVG",
    "C": "MODEL_C_HTF_LIQUIDITY",
}
CANDIDATE_KEYS = ("B",)
FAMILY_KEYS = ("A", "B", "C")
N_SLICES = 5
N_WF_FOLDS = 3
K_PURGE = 5
CSCV_S = 8
MC_BOOT = 2000
MC_SHUFFLE = 1000
MC_SEED = 20260814
MIN_OOS_TRADES = 30
MIN_PF = 1.30
MIN_EXP = 0.15
MAX_DD = 10.0
HORIZON = 96
EMBARGO = 96


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


def collect_family(p22a):
    from tradingbot.config.price_action import get_price_action_config

    df = p22a.load_df()
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    hours = np.array([int(ts.hour) for ts in df.index])
    dates = np.array([ts.date().isoformat() for ts in df.index])
    atr_pct = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct = np.where(np.isnan(atr_pct), 50.0, atr_pct)
    regime = p22a.infer_regimes(df)
    swings = p22a.swing_arrays(high, low, n)
    pdh, pdl = p22a.last_completed_day_hl(dates, high, low, n)
    pwh, pwl = p22a.last_completed_week_hl(df.index, high, low, n)
    asian_hi, asian_lo = p22a.causal_range(dates, hours, high, low, n, 0, 8)
    lon_hi, lon_lo = p22a.causal_range(dates, hours, high, low, n, 7, 12)
    sess_hi, sess_lo = p22a.session_hl_arrays(dates, hours, n, asian_hi, asian_lo, lon_hi, lon_lo)
    htf_bias = p22a.htf_bias_array(df.index, close, n)
    ctx = {
        "n": n, "index": df.index, "hours": hours, "dates": dates,
        "high": high, "low": low, "close": close, "open": open_, "atr": atr,
        "atr_pct": atr_pct, "regime": regime, "swings": swings, "pdh": pdh,
        "pdl": pdl, "pwh": pwh, "pwl": pwl, "sess_hi": sess_hi, "sess_lo": sess_lo,
        "asian_hi": asian_hi, "asian_lo": asian_lo, "htf_bias": htf_bias,
    }
    live = get_price_action_config("XAUUSD", "M5")
    ny_s = int(live.get("NY_ENTRY_START_UTC", 15))
    ny_e = int(live.get("NY_ENTRY_END_UTC", 16))
    asian_end = int(live.get("ASIAN_SESSION_END_UTC", 8))
    emit("collect Model A (family only, not a 22B candidate) ...")
    raw_a = p22a.collect_a(ctx, ny_s, ny_e, asian_end)
    emit("  A raw=%s" % len(raw_a))
    emit("collect Model B (22A candidate) ...")
    raw_b, fun_b = p22a.collect_structural(
        ctx, session=p22a.B_SESSION, use_htf_levels=False, require_pd=False
    )
    emit("  B raw=%s funnel=%s" % (len(raw_b), fun_b))
    emit("collect Model C (family only) ...")
    raw_c, fun_c = p22a.collect_structural(
        ctx, session=p22a.C_SESSION, use_htf_levels=True, require_pd=True
    )
    emit("  C raw=%s funnel=%s" % (len(raw_c), fun_c))
    return df, n, {"A": raw_a, "B": raw_b, "C": raw_c}, {"B": fun_b, "C": fun_c}


def slice_edges(n: int, n_slices: int) -> np.ndarray:
    return np.linspace(0, n, n_slices + 1, dtype=int)


def in_range(i: int, lo: int, hi: int) -> bool:
    return lo <= int(i) < hi


def filter_range(rows, lo: int, hi: int):
    return [r for r in rows if in_range(r["i"], lo, hi)]


def summarize(p22a, raw):
    trades = p22a.apply_cd(raw)
    rs = [float(t["final_R"]) for t in trades]
    base = p22a.metrics_from_rs(rs)
    mfe = [float(t.get("MFE_R") or 0.0) for t in trades]
    mae = [float(t.get("MAE_R") or 0.0) for t in trades]
    base["median_mfe"] = round(float(np.median(mfe)), 4) if mfe else 0.0
    base["median_mae"] = round(float(np.median(mae)), 4) if mae else 0.0
    base["raw_setups"] = len(raw)
    return base, trades


def cost_variants(trades):
    out = {
        "raw": [],
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
        out["raw"].append(r)
        out["normal_spread"].append(r - cs)
        out["spread_p25"].append(r - 1.25 * cs)
        out["spread_p50"].append(r - 1.50 * cs)
        out["realistic_slip"].append(r - ct)
        out["adverse_slip"].append(r - (1.25 * cs + 1.50 * slip))
    return out


def metrics_pack(p22a, rs):
    return p22a.metrics_from_rs(rs)


def regime_bucket(reg: str) -> str:
    r = str(reg)
    if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return "trend"
    if r in ("VOLATILE", "CRISIS"):
        return "expansion"
    return "ranging"


def grouped_metrics(p22a, trades, key_fn):
    groups = defaultdict(list)
    for t in trades:
        groups[str(key_fn(t))].append(t)
    out = {}
    for k, rows in sorted(groups.items()):
        rs = [float(x["final_R"]) for x in rows]
        m = metrics_pack(p22a, rs)
        m["n"] = len(rows)
        out[k] = m
    return out


def stability_flag(bucket_metrics, min_n: int = 8):
    scored = []
    catastrophic = False
    for m in bucket_metrics.values():
        n = int(m.get("n") or m.get("trades") or 0)
        if n < min_n:
            continue
        pf = float(m["profit_factor"])
        exp = float(m["expectancy_R"])
        scored.append(exp >= -0.05 and pf >= 0.85)
        if pf < 0.50 or exp < -0.50:
            catastrophic = True
    if len(scored) < 2:
        return False, catastrophic
    return all(scored), catastrophic


def sharpe_rs(rs):
    if len(rs) < 2:
        return float(np.mean(rs)) if rs else -1e9
    arr = np.asarray(rs, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd <= 1e-12:
        return float(arr.mean()) * 10.0
    return float(arr.mean() / sd * math.sqrt(len(arr)))


def walk_forward(p22a, raw_map, n: int):
    edges = slice_edges(n, N_SLICES)
    folds = []
    for k in range(N_WF_FOLDS):
        train_lo, train_hi = int(edges[0]), int(edges[k + 1])
        calib_lo, calib_hi = int(edges[k + 1]), int(edges[k + 2])
        oos_lo, oos_hi = int(edges[k + 2]), int(edges[k + 3])
        embargo_cut = max(train_lo, oos_lo - EMBARGO)
        fold = {
            "fold": k + 1,
            "train_bars": [train_lo, train_hi],
            "calib_bars": [calib_lo, calib_hi],
            "oos_bars": [oos_lo, oos_hi],
            "embargo_bars": EMBARGO,
            "models": {},
        }
        for key in FAMILY_KEYS:
            raw = raw_map[key]
            train_raw = [r for r in filter_range(raw, train_lo, train_hi) if int(r["i"]) + HORIZON < embargo_cut]
            calib_raw = [r for r in filter_range(raw, calib_lo, calib_hi) if int(r["i"]) + HORIZON < oos_lo]
            oos_raw = filter_range(raw, oos_lo, oos_hi)
            tr_m, _ = summarize(p22a, train_raw)
            ca_m, _ = summarize(p22a, calib_raw)
            oo_m, _ = summarize(p22a, oos_raw)
            fold["models"][NAMES[key]] = {"research": tr_m, "calibration": ca_m, "oos": oo_m}
        folds.append(fold)
    pooled = {}
    oos_lo0 = int(edges[2])
    oos_hiN = int(edges[-1])
    for key in FAMILY_KEYS:
        oos_raw = filter_range(raw_map[key], oos_lo0, oos_hiN)
        m, trades = summarize(p22a, oos_raw)
        pooled[NAMES[key]] = {"metrics": m, "trades": trades}
    research_hi = int(edges[2])
    research = {}
    for key in FAMILY_KEYS:
        m, _ = summarize(p22a, filter_range(raw_map[key], 0, research_hi))
        research[NAMES[key]] = m
    return {
        "slices": [int(x) for x in edges],
        "design": "expanding research + calibration + untouched OOS, 3 rolls, embargo=96, horizon=96",
        "folds": folds,
        "pooled_oos": {k: v["metrics"] for k, v in pooled.items()},
        "research_window": research,
        "pooled_oos_trades": {k: v["trades"] for k, v in pooled.items()},
        "oos_bar_range": [oos_lo0, oos_hiN],
        "research_bar_range": [0, research_hi],
    }


def purged_cv(p22a, raw, n: int):
    edges = slice_edges(n, K_PURGE)
    folds = []
    test_metrics = []
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
        tr_m, _ = summarize(p22a, train_raw)
        te_m, _ = summarize(p22a, test_raw)
        folds.append({
            "fold": k + 1,
            "test_bars": [test_lo, test_hi],
            "train": tr_m,
            "test": te_m,
            "purged_train_raw": len(train_raw),
            "test_raw": len(test_raw),
        })
        if int(te_m["trades"]) > 0:
            test_metrics.append(te_m)
    if test_metrics:
        pfs = [float(m["profit_factor"]) for m in test_metrics]
        exps = [float(m["expectancy_R"]) for m in test_metrics]
        ntr = [int(m["trades"]) for m in test_metrics]
        agg = {
            "folds_with_trades": len(test_metrics),
            "mean_test_pf": round(float(np.mean(pfs)), 3),
            "median_test_pf": round(float(np.median(pfs)), 3),
            "min_test_pf": round(float(np.min(pfs)), 3),
            "mean_test_exp_R": round(float(np.mean(exps)), 4),
            "total_test_trades": int(sum(ntr)),
        }
    else:
        agg = {
            "folds_with_trades": 0, "mean_test_pf": 0.0, "median_test_pf": 0.0,
            "min_test_pf": 0.0, "mean_test_exp_R": 0.0, "total_test_trades": 0,
        }
    return {"k": K_PURGE, "horizon_bars": HORIZON, "embargo_bars": EMBARGO, "folds": folds, "aggregate": agg}


def cscv_pbo(raw_map, n: int, p22a):
    edges = slice_edges(n, CSCV_S)
    blocks = {k: [] for k in FAMILY_KEYS}
    for s in range(CSCV_S):
        lo, hi = int(edges[s]), int(edges[s + 1])
        for k in FAMILY_KEYS:
            _, trades = summarize(p22a, filter_range(raw_map[k], lo, hi))
            blocks[k].append([float(t["final_R"]) for t in trades])
    n_half = CSCV_S // 2
    n_models = len(FAMILY_KEYS)
    under = 0
    used = 0
    skipped = 0
    lambdas = []
    is_best_counts = {NAMES[k]: 0 for k in FAMILY_KEYS}
    oos_under_median = {NAMES[k]: 0 for k in FAMILY_KEYS}
    for is_idx in combinations(range(CSCV_S), n_half):
        oos_idx = [j for j in range(CSCV_S) if j not in set(is_idx)]
        is_scores = {}
        oos_scores = {}
        ok = True
        for k in FAMILY_KEYS:
            is_r = []
            oos_r = []
            for j in is_idx:
                is_r.extend(blocks[k][j])
            for j in oos_idx:
                oos_r.extend(blocks[k][j])
            if len(is_r) < 6 or len(oos_r) < 6:
                ok = False
                break
            is_scores[k] = sharpe_rs(is_r)
            oos_scores[k] = sharpe_rs(oos_r)
        if not ok:
            skipped += 1
            continue
        best = max(FAMILY_KEYS, key=lambda kk: is_scores[kk])
        ranked = sorted(FAMILY_KEYS, key=lambda kk: oos_scores[kk], reverse=True)
        rank = ranked.index(best) + 1
        is_best_counts[NAMES[best]] += 1
        used += 1
        if rank > n_models / 2.0:
            under += 1
            oos_under_median[NAMES[best]] += 1
        omega = rank / (n_models + 1.0)
        if 0.0 < omega < 1.0:
            lambdas.append(math.log(omega / (1.0 - omega)))
    pbo = (under / used) if used else None
    limitation = (
        "PBO estimated on a tiny strategy universe (N=%s structural models from 22A; "
        "no extra 22B grid). Estimate is coarse and is not a high-power CSCV."
        % n_models
    )
    return {
        "method": "CSCV_PBO",
        "S": CSCV_S,
        "combinations_total": int(math.comb(CSCV_S, n_half)),
        "combinations_used": used,
        "combinations_skipped": skipped,
        "n_strategies": n_models,
        "strategies": [NAMES[k] for k in FAMILY_KEYS],
        "metric": "sharpe_of_trade_R",
        "PBO": None if pbo is None else round(float(pbo), 4),
        "mean_logit_lambda": None if not lambdas else round(float(np.mean(lambdas)), 4),
        "is_best_counts": is_best_counts,
        "oos_under_median_when_is_best": oos_under_median,
        "limitation": limitation,
        "reliable": bool(used >= 20 and n_models >= 8),
    }

def monte_carlo(p22a, trades, seed: int):
    rs = np.array([float(t["final_R"]) for t in trades], dtype=float)
    nn = len(rs)
    rng = np.random.default_rng(seed)
    if nn == 0:
        return {"n_trades": 0, "bootstrap": {}, "order_shuffle": {}, "note": "no trades"}
    boot_pf = np.empty(MC_BOOT, dtype=float)
    boot_exp = np.empty(MC_BOOT, dtype=float)
    boot_dd = np.empty(MC_BOOT, dtype=float)
    for b in range(MC_BOOT):
        sample = rng.choice(rs, size=nn, replace=True)
        m = metrics_pack(p22a, sample.tolist())
        boot_pf[b] = float(m["profit_factor"])
        boot_exp[b] = float(m["expectancy_R"])
        boot_dd[b] = float(m["max_dd_R"])
    sh_dd = np.empty(MC_SHUFFLE, dtype=float)
    for s in range(MC_SHUFFLE):
        perm = rng.permutation(rs)
        m = metrics_pack(p22a, perm.tolist())
        sh_dd[s] = float(m["max_dd_R"])
    note = (
        "PF is invariant to order-shuffle, so median/p05 PF come from bootstrap "
        "resampling of OOS trades (with replacement). Order-shuffle is used for DD tail."
    )
    return {
        "n_trades": nn,
        "n_bootstrap": MC_BOOT,
        "n_order_shuffle": MC_SHUFFLE,
        "seed": seed,
        "note": note,
        "bootstrap": {
            "median_pf": round(float(np.median(boot_pf)), 3),
            "p05_pf": round(float(np.percentile(boot_pf, 5)), 3),
            "p95_pf": round(float(np.percentile(boot_pf, 95)), 3),
            "median_exp_R": round(float(np.median(boot_exp)), 4),
            "p05_exp_R": round(float(np.percentile(boot_exp, 5)), 4),
            "median_dd_R": round(float(np.median(boot_dd)), 3),
            "p95_dd_R": round(float(np.percentile(boot_dd, 95)), 3),
            "worst_dd_R": round(float(np.max(boot_dd)), 3),
        },
        "order_shuffle": {
            "median_dd_R": round(float(np.median(sh_dd)), 3),
            "p95_dd_R": round(float(np.percentile(sh_dd, 95)), 3),
            "worst_dd_R": round(float(np.max(sh_dd)), 3),
            "pf_invariant": True,
        },
    }


def pick_best_name(metrics_by_name):
    best = "NONE"
    best_pf = -1.0
    for name, m in metrics_by_name.items():
        if int(m.get("trades") or 0) < 8:
            continue
        pf = float(m.get("profit_factor") or 0.0)
        if pf > best_pf:
            best_pf = pf
            best = name
    if best != "NONE":
        return best
    for name, m in metrics_by_name.items():
        pf = float(m.get("profit_factor") or 0.0)
        if pf > best_pf:
            best_pf = pf
            best = name
    return best


def gates(oos, cost, cat_reg: bool, cat_sess: bool, tiny_window_only: bool):
    ntr = int(oos.get("trades") or 0)
    pf = float(oos.get("profit_factor") or 0.0)
    exp = float(oos.get("expectancy_R") or 0.0)
    dd = float(oos.get("max_dd_R") or 0.0)
    slip_pf = float(cost.get("realistic_slip", {}).get("profit_factor") or 0.0)
    slip_exp = float(cost.get("realistic_slip", {}).get("expectancy_R") or 0.0)
    return {
        "oos_trades_ge_30": ntr >= MIN_OOS_TRADES,
        "oos_pf_ge_1_30": pf >= MIN_PF,
        "oos_exp_gt_0_15": exp > MIN_EXP,
        "oos_maxdd_le_10R": dd <= MAX_DD,
        "positive_under_realistic_cost": slip_pf >= 1.0 and slip_exp > 0.0,
        "no_catastrophic_regime": not cat_reg,
        "no_catastrophic_session": not cat_sess,
        "not_tiny_window_only": not tiny_window_only,
    }


def fmt(v):
    if v is None:
        return "NA"
    return str(v)

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p22a = load_phase22a()
    df, n, raw_map, funnels = collect_family(p22a)
    emit("DF bars=%s %s -> %s" % (n, df.index.min(), df.index.max()))
    emit("walk-forward ...")
    wf = walk_forward(p22a, raw_map, n)
    cand_name = CANDIDATE_22A
    oos_trades = wf["pooled_oos_trades"][cand_name]
    oos_m = wf["pooled_oos"][cand_name]
    is_m = wf["research_window"][cand_name]
    emit("candidate %s research trades=%s PF=%s OOS trades=%s PF=%s" % (
        cand_name, is_m["trades"], is_m["profit_factor"], oos_m["trades"], oos_m["profit_factor"]
    ))

    emit("purged CV ...")
    pcv = purged_cv(p22a, raw_map["B"], n)

    emit("cost stress on pooled OOS ...")
    cv = cost_variants(oos_trades)
    cost_metrics = {k: metrics_pack(p22a, rs) for k, rs in cv.items()}

    emit("stability ...")
    full_b_m, full_b_trades = summarize(p22a, raw_map["B"])
    stab_src = oos_trades if len(oos_trades) >= 20 else full_b_trades
    stab_src_name = "pooled_oos" if stab_src is oos_trades else "full_candidate"
    by_regime = grouped_metrics(p22a, stab_src, lambda t: regime_bucket(t.get("regime")))
    by_session = grouped_metrics(p22a, stab_src, lambda t: str(t.get("session") or "NA"))
    by_direction = grouped_metrics(p22a, stab_src, lambda t: str(t.get("direction") or "NA"))
    by_hour = grouped_metrics(p22a, stab_src, lambda t: str(t.get("hour")))
    reg_stable, cat_reg = stability_flag(by_regime, min_n=8)
    sess_stable, cat_sess = stability_flag(by_session, min_n=8)
    dir_stable, cat_dir = stability_flag(by_direction, min_n=8)

    fold_oos_pfs = []
    for fold in wf["folds"]:
        cell = fold["models"][cand_name]["oos"]
        if int(cell["trades"]) >= 8:
            fold_oos_pfs.append(float(cell["profit_factor"]))
    tiny_window_only = bool(fold_oos_pfs) and (sum(1 for x in fold_oos_pfs if x >= 1.0) <= 1) and (max(fold_oos_pfs) >= 1.0)

    emit("PBO/CSCV ...")
    pbo = cscv_pbo(raw_map, n, p22a)

    emit("Monte Carlo ...")
    mc = monte_carlo(p22a, oos_trades, MC_SEED)

    best_is_family = pick_best_name(wf["research_window"])
    best_oos_family = pick_best_name(wf["pooled_oos"])
    is_pf = float(is_m["profit_factor"])
    oos_pf = float(oos_m["profit_factor"])
    is_exp = float(is_m["expectancy_R"])
    oos_exp = float(oos_m["expectancy_R"])
    deg_pf = round(oos_pf - is_pf, 3)
    deg_exp = round(oos_exp - is_exp, 4)
    deg_pct = round(100.0 * (oos_pf / is_pf - 1.0), 2) if is_pf > 0 else None

    gate = gates(oos_m, cost_metrics, cat_reg or cat_dir, cat_sess, tiny_window_only)
    pbo_val = pbo.get("PBO")
    pbo_unreliable = not bool(pbo.get("reliable"))
    gate["pbo_reliable"] = not pbo_unreliable
    if not pbo_unreliable:
        gate["pbo_lt_0_5"] = (pbo_val is not None) and (float(pbo_val) < 0.50)

    certified = all(gate.values())
    if pbo_unreliable:
        certified = False

    if pbo_unreliable or (pbo_val is not None and float(pbo_val) >= 0.45):
        overfit = "HIGH"
    elif pbo_val is not None and float(pbo_val) >= 0.25:
        overfit = "MEDIUM"
    elif deg_pf < -0.20 or oos_pf < 1.0:
        overfit = "HIGH"
    else:
        overfit = "LOW"

    selection_bias = {
        "n_models_tested_phase22a": 3,
        "n_parameter_variants_phase22b": 0,
        "phase22b_added_search": False,
        "selection_rule_22a": "robustness across 30d/90d/180d and WF folds; not max 180d PF",
        "best_full_sample_22a": "MODEL_A_CURRENT_PA (PF=1.733) rejected by 22A robustness",
        "advanced_candidate": CANDIDATE_22A,
        "selection_used_full_180d": True,
        "oos_not_fully_untouched_vs_selection": True,
        "evidence": (
            "Phase 22A compared 3 structural models on the same 180d cache. Model A had the "
            "best in-sample PF but failed 30d/90d. Model B was advanced because it was the only "
            "model with PF>=1 on all three windows. That selection already observed the period "
            "now labelled OOS, so 22B OOS is a temporal-stability test of a frozen rule, not a "
            "blind holdout relative to model choice. No extra grid was searched in 22B."
        ),
    }

    shadow = bool(certified)
    certified_models = [cand_name] if certified else []
    result_lines = [
        "PHASE_22B_RESULT",
        "",
        "CERTIFIED_MODELS=%s" % (",".join(certified_models) if certified_models else "NONE"),
        "BEST_MODEL=%s" % cand_name,
        "OOS_TRADES=%s" % oos_m["trades"],
        "OOS_PF=%s" % oos_m["profit_factor"],
        "OOS_EXPECTANCY_R=%s" % oos_m["expectancy_R"],
        "OOS_MAX_DD_R=%s" % oos_m["max_dd_R"],
        "",
        "COST_STRESS_PF=%s" % cost_metrics["realistic_slip"]["profit_factor"],
        "MC_MEDIAN_PF=%s" % mc["bootstrap"]["median_pf"],
        "MC_P05_PF=%s" % mc["bootstrap"]["p05_pf"],
        "",
        "PBO=%s" % fmt(pbo.get("PBO")),
        "REGIME_STABLE=%s" % ("YES" if reg_stable else "NO"),
        "SESSION_STABLE=%s" % ("YES" if sess_stable else "NO"),
        "",
        "OVERFIT_RISK=%s" % overfit,
        "CERTIFIED_FOR_SHADOW=%s" % ("YES" if shadow else "NO"),
        "LIVE_PATCH_APPLIED=NO",
        "",
    ]
    result = "\n".join(result_lines)

    matrix = {
        "phase": "22B",
        "live_files_modified": False,
        "meta_used": False,
        "bars": n,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "candidates_from_22a": [CANDIDATE_22A],
        "family_for_multiple_testing": [NAMES[k] for k in FAMILY_KEYS],
        "funnels": funnels,
        "acceptance": {
            "min_oos_trades": MIN_OOS_TRADES,
            "min_pf": MIN_PF,
            "min_exp_R": MIN_EXP,
            "max_dd_R": MAX_DD,
        },
        "gates": gate,
        "certified": certified,
        "walk_forward": {
            "design": wf["design"],
            "slices": wf["slices"],
            "folds": wf["folds"],
            "research_window": wf["research_window"],
            "pooled_oos": wf["pooled_oos"],
        },
        "purged_cv": pcv,
        "cost_stress_oos": cost_metrics,
        "stability": {
            "source": stab_src_name,
            "by_regime": by_regime,
            "by_session": by_session,
            "by_direction": by_direction,
            "by_hour": by_hour,
            "regime_stable": reg_stable,
            "session_stable": sess_stable,
            "direction_stable": dir_stable,
            "catastrophic_regime": cat_reg,
            "catastrophic_session": cat_sess,
            "catastrophic_direction": cat_dir,
            "tiny_window_only": tiny_window_only,
        },
        "multiple_testing": {
            "n_variants_models_tested": 3,
            "n_22b_extra_variants": 0,
            "best_in_sample": {
                "model": best_is_family,
                "window": "research=first 2/5 of bars",
                "metrics": wf["research_window"].get(best_is_family),
            },
            "candidate_is": is_m,
            "candidate_oos": oos_m,
            "oos_result_model": best_oos_family,
            "degradation_pf_points": deg_pf,
            "degradation_exp_R": deg_exp,
            "degradation_pf_pct": deg_pct,
            "selection_bias": selection_bias,
        },
        "full_candidate_sample": full_b_m,
        "result_block": result,
    }

    (OUT / "certification_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    (OUT / "pbo_results.json").write_text(json.dumps(pbo, indent=2, default=str), encoding="utf-8")
    (OUT / "monte_carlo_results.json").write_text(json.dumps(mc, indent=2, default=str), encoding="utf-8")
    extra = [
        result.rstrip(),
        "",
        "NOTES",
        "IS_WINDOW_PF=%s IS_EXP_R=%s IS_TRADES=%s" % (is_m["profit_factor"], is_m["expectancy_R"], is_m["trades"]),
        "OOS_DEGRADATION_PF_POINTS=%s OOS_DEGRADATION_EXP_R=%s OOS_DEGRADATION_PF_PCT=%s" % (deg_pf, deg_exp, deg_pct),
        "BEST_IS_FAMILY=%s BEST_OOS_FAMILY=%s" % (best_is_family, best_oos_family),
        "N_MODELS_TESTED=3 N_22B_VARIANTS=0",
        "PURGED_CV_MEAN_TEST_PF=%s PURGED_CV_MIN_TEST_PF=%s" % (pcv["aggregate"]["mean_test_pf"], pcv["aggregate"]["min_test_pf"]),
        "COST_NORMAL_SPREAD_PF=%s" % cost_metrics["normal_spread"]["profit_factor"],
        "COST_SPREAD_P25_PF=%s" % cost_metrics["spread_p25"]["profit_factor"],
        "COST_SPREAD_P50_PF=%s" % cost_metrics["spread_p50"]["profit_factor"],
        "COST_ADVERSE_SLIP_PF=%s" % cost_metrics["adverse_slip"]["profit_factor"],
        "MC_WORST_DD_R=%s MC_P95_DD_R=%s" % (mc["order_shuffle"]["worst_dd_R"], mc["order_shuffle"]["p95_dd_R"]),
        "PBO_RELIABLE=%s PBO_LIMITATION=%s" % (pbo.get("reliable"), pbo.get("limitation")),
        "GATES=%s" % json.dumps(gate),
        "LIVE_PATCH_APPLIED=NO",
        "",
    ]
    (OUT / "phase22b_result.txt").write_text("\n".join(extra), encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())