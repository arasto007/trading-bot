#!/usr/bin/env python3
"""PHASE 24A - specialized alpha certification (research-only, no live patches)."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = ROOT / "logs" / "phase24a"
WINDOW_DAYS = (30, 60, 90, 120, 180)
CSCV_S = 8
FAMILY_KEYS = ("A", "B")
MIN_TRADES = 100
MIN_PF = 1.30
MIN_EXP = 0.15
MAX_DD = 12.0
MIN_COST_PF = 1.05
MIN_MC_P05_PF = 0.95
MC_SEED = 20260818
PHASE23B_REFERENCE_PBO = 0.9143
ORB_INTENDED_HOURS = {7, 8}


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_p23a():
    path = ROOT / "scripts" / "phase23a_multi_strategy_discovery.py"
    spec = importlib.util.spec_from_file_location("phase23a_multi_strategy_discovery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load phase23a_multi_strategy_discovery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def fmt(v: Any) -> str:
    if v is None:
        return "NA"
    return str(v)


def regime_bucket(reg: str) -> str:
    r = str(reg)
    if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return "trend"
    if r in ("VOLATILE", "CRISIS"):
        return "expansion"
    return "ranging"


def sharpe_rs(rs: list[float]) -> float:
    if len(rs) < 2:
        return float(np.mean(rs)) if rs else -1e9
    arr = np.asarray(rs, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd <= 1e-12:
        return float(arr.mean()) * 10.0
    return float(arr.mean() / sd * math.sqrt(len(arr)))


def trade_metrics(p22a, trades: list[dict[str, Any]]) -> dict[str, Any]:
    rs = [float(t["final_R"]) for t in trades]
    m = p22a.metrics_from_rs(rs)
    if trades:
        m["mean_MFE_R"] = round(float(np.mean([float(t.get("MFE_R") or 0.0) for t in trades])), 4)
        m["mean_MAE_R"] = round(float(np.mean([float(t.get("MAE_R") or 0.0) for t in trades])), 4)
    else:
        m["mean_MFE_R"] = 0.0
        m["mean_MAE_R"] = 0.0
    return m


def window_trades(p22a, p23a, raw: list[dict[str, Any]], df, days: int, n: int) -> list[dict[str, Any]]:
    if days >= 180:
        lo, hi = 0, n
    else:
        idx = p22a.slice_by_days(df, days)
        if len(idx) == 0:
            return []
        lo, hi = int(idx[0]), int(idx[-1]) + 1
    sub = p23a.filter_range(raw, lo, hi)
    return p22a.apply_cd(sub)


def is_intended_trade(trade: dict[str, Any], key: str) -> bool:
    h = int(trade.get("hour") or -1)
    if key == "A":
        return h == 15
    return h in ORB_INTENDED_HOURS


def grouped_trade_metrics(
    p22a,
    trades: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
) -> dict[str, dict[str, Any]]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    return {k: trade_metrics(p22a, rows) for k, rows in sorted(groups.items())}


def concentration_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    def top_share(key_fn: Callable[[dict[str, Any]], str]) -> tuple[float, str | None]:
        buckets: defaultdict[str, float] = defaultdict(float)
        for t in trades:
            r = float(t.get("final_R") or 0.0)
            if r > 0:
                buckets[key_fn(t)] += r
        total = sum(buckets.values())
        if total <= 0:
            return 0.0, None
        top_key = max(buckets, key=buckets.get)
        return round(buckets[top_key] / total, 4), top_key

    hour_share, top_hour = top_share(lambda t: str(int(t.get("hour") or -1)))
    month_share, top_month = top_share(lambda t: str(t.get("day") or "")[:7])
    dir_share, top_dir = top_share(lambda t: str(t.get("direction") or "NA"))
    reg_share, top_reg = top_share(lambda t: regime_bucket(str(t.get("regime") or "")))
    return {
        "top_hour_profit_share": hour_share,
        "top_hour": top_hour,
        "top_month_profit_share": month_share,
        "top_month": top_month,
        "top_direction_profit_share": dir_share,
        "top_direction": top_dir,
        "top_regime_profit_share": reg_share,
        "top_regime": top_reg,
    }


def rolling_stability(p22a, trades: list[dict[str, Any]], window_days: int) -> dict[str, Any]:
    by_day: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_day[str(t.get("day") or "")].append(t)
    days_sorted = sorted(d for d in by_day if d)
    windows: list[dict[str, Any]] = []
    if len(days_sorted) >= window_days:
        for i in range(window_days - 1, len(days_sorted)):
            chunk_days = days_sorted[i - window_days + 1 : i + 1]
            chunk_trades: list[dict[str, Any]] = []
            for d in chunk_days:
                chunk_trades.extend(by_day[d])
            m = trade_metrics(p22a, chunk_trades)
            windows.append(
                {
                    "end_day": chunk_days[-1],
                    "trades": m["trades"],
                    "profit_factor": m["profit_factor"],
                    "expectancy_R": m["expectancy_R"],
                }
            )
    n_win = len(windows)
    if n_win == 0:
        pct = {"pf_ge_1_20": 0.0, "pf_ge_1_00": 0.0, "exp_gt_0": 0.0}
    else:
        pf120 = sum(1 for w in windows if float(w["profit_factor"]) >= 1.20)
        pf100 = sum(1 for w in windows if float(w["profit_factor"]) >= 1.00)
        exppos = sum(1 for w in windows if float(w["expectancy_R"]) > 0)
        pct = {
            "pf_ge_1_20": round(100.0 * pf120 / n_win, 2),
            "pf_ge_1_00": round(100.0 * pf100 / n_win, 2),
            "exp_gt_0": round(100.0 * exppos / n_win, 2),
        }
    return {
        "window_trading_days": window_days,
        "windows_evaluated": n_win,
        "pct_windows": pct,
        "windows": windows,
    }


def cscv_pbo(
    raw_map: dict[str, list[dict[str, Any]]],
    n: int,
    p22a,
    p23a,
    names: dict[str, str],
) -> dict[str, Any]:
    edges = p23a.slice_edges(n, CSCV_S)
    blocks = {k: [] for k in FAMILY_KEYS}
    for s in range(CSCV_S):
        lo, hi = int(edges[s]), int(edges[s + 1])
        for k in FAMILY_KEYS:
            sub = p23a.filter_range(raw_map[k], lo, hi)
            trades = p22a.apply_cd(sub)
            blocks[k].append([float(t["final_R"]) for t in trades])
    n_half = CSCV_S // 2
    n_models = len(FAMILY_KEYS)
    under = 0
    used = 0
    skipped = 0
    lambdas: list[float] = []
    is_best_counts = {names[k]: 0 for k in FAMILY_KEYS}
    oos_under_median = {names[k]: 0 for k in FAMILY_KEYS}
    for is_idx in combinations(range(CSCV_S), n_half):
        oos_idx = [j for j in range(CSCV_S) if j not in set(is_idx)]
        is_scores: dict[str, float] = {}
        oos_scores: dict[str, float] = {}
        ok = True
        for k in FAMILY_KEYS:
            is_r: list[float] = []
            oos_r: list[float] = []
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
        is_best_counts[names[best]] += 1
        used += 1
        if rank > n_models / 2.0:
            under += 1
            oos_under_median[names[best]] += 1
        omega = rank / (n_models + 1.0)
        if 0.0 < omega < 1.0:
            lambdas.append(math.log(omega / (1.0 - omega)))
    pbo = (under / used) if used else None
    limitation = (
        "PBO estimated on n_models=%s (PA/ORB only). With 2 models CSCV power is very low; "
        "treat PBO as indicative, not definitive. reliable=false when n_models<8."
        % n_models
    )
    return {
        "method": "CSCV_PBO",
        "S": CSCV_S,
        "combinations_total": int(math.comb(CSCV_S, n_half)),
        "combinations_used": used,
        "combinations_skipped": skipped,
        "n_strategies": n_models,
        "strategies": [names[k] for k in FAMILY_KEYS],
        "metric": "sharpe_of_trade_R",
        "PBO": None if pbo is None else round(float(pbo), 4),
        "mean_logit_lambda": None if not lambdas else round(float(np.mean(lambdas)), 4),
        "is_best_counts": is_best_counts,
        "oos_under_median_when_is_best": oos_under_median,
        "limitation": limitation,
        "reliable": bool(used >= 20 and n_models >= 8),
        "phase23b_reference_PBO": PHASE23B_REFERENCE_PBO,
    }


def deflated_sharpe_ratio(rs: list[float], n_trials: int) -> dict[str, Any]:
    arr = np.asarray(rs, dtype=float)
    n = len(arr)
    if n < 2:
        return {
            "DSR": None,
            "observed_SR": None,
            "n_obs": n,
            "n_trials": n_trials,
            "note": "insufficient trades",
        }
    mu = float(arr.mean())
    sd = float(arr.std(ddof=1))
    sr = mu / sd if sd > 1e-12 else 0.0
    skew = float(stats.skew(arr, bias=False))
    kurt = float(stats.kurtosis(arr, fisher=False, bias=False))
    sr_var = (1.0 + 0.5 * sr**2 - skew * sr + ((kurt - 3.0) / 4.0) * sr**2) / (n - 1)
    sr_var = max(sr_var, 1e-12)
    emc = 0.5772156649
    z1 = float(stats.norm.ppf(1.0 - 1.0 / max(n_trials, 1)))
    z2 = float(stats.norm.ppf(1.0 - 1.0 / (max(n_trials, 1) * math.e)))
    sr0 = math.sqrt(sr_var) * ((1.0 - emc) * z1 + emc * z2)
    dsr = float(stats.norm.cdf((sr - sr0) / math.sqrt(sr_var)))
    return {
        "DSR": round(dsr, 4),
        "observed_SR": round(sr, 4),
        "expected_max_SR_null": round(sr0, 4),
        "SR_variance": round(sr_var, 6),
        "skew": round(skew, 4),
        "kurtosis_pearson": round(kurt, 4),
        "n_obs": n,
        "n_trials": n_trials,
        "method": "Bailey_LdP_deflated_sharpe",
    }


def overfit_risk_label(pbo_val: float | None) -> str:
    if pbo_val is not None and float(pbo_val) >= 0.45:
        return "HIGH"
    if pbo_val is not None and float(pbo_val) >= 0.25:
        return "MEDIUM"
    return "LOW"


def window_positive(m: dict[str, Any]) -> bool:
    return float(m.get("profit_factor") or 0.0) >= 1.0 and float(m.get("expectancy_R") or 0.0) > 0


def certification_gates(
    oos: dict[str, Any],
    window_metrics: dict[int, dict[str, Any]],
    concentration: dict[str, Any],
    cost_realistic_pf: float,
    mc_p05_pf: float,
    pbo_reported: bool,
) -> tuple[dict[str, bool], list[str]]:
    ntr = int(oos.get("trades") or 0)
    notes: list[str] = []
    trades_ok = ntr >= MIN_TRADES
    if not trades_ok:
        notes.append("OOS trades=%s below MIN_TRADES=%s" % (ntr, MIN_TRADES))
    pos_windows = sum(1 for d in WINDOW_DAYS if window_positive(window_metrics.get(d, {})))
    gates = {
        "oos_trades_ge_100": trades_ok,
        "oos_pf_ge_1_30": float(oos.get("profit_factor") or 0.0) >= MIN_PF,
        "oos_exp_ge_0_15": float(oos.get("expectancy_R") or 0.0) >= MIN_EXP,
        "oos_maxdd_le_12R": float(oos.get("max_dd_R") or 0.0) <= MAX_DD,
        "cost_realistic_slip_pf_ge_1_05": cost_realistic_pf >= MIN_COST_PF,
        "mc_p05_pf_ge_0_95": mc_p05_pf >= MIN_MC_P05_PF,
        "at_least_3_windows_positive": pos_windows >= 3,
        "top_month_profit_share_le_0_50": float(concentration.get("top_month_profit_share") or 1.0) <= 0.50,
        "top_direction_profit_share_le_0_75": float(concentration.get("top_direction_profit_share") or 1.0) <= 0.75,
        "top_regime_profit_share_le_0_75": float(concentration.get("top_regime_profit_share") or 1.0) <= 0.75,
        "pbo_reported": pbo_reported,
    }
    return gates, notes


def specialized_status(gates: dict[str, bool], pbo_val: float | None, pbo_reliable: bool) -> str:
    metric_gates = {k: v for k, v in gates.items() if k != "pbo_reported"}
    if not all(metric_gates.values()):
        return "REJECTED"
    if (pbo_val is not None and float(pbo_val) >= 0.45) or not pbo_reliable:
        return "CONDITIONAL"
    return "SPECIALIZED_CERTIFIED"


def analyze_strategy(
    key: str,
    label: str,
    raw: list[dict[str, Any]],
    wf: dict[str, Any],
    p22a,
    p23a,
    df,
    n: int,
    pbo_doc: dict[str, Any],
) -> dict[str, Any]:
    oos_trades = wf["pooled_oos_trades"][key]
    oos_m = trade_metrics(p22a, oos_trades)

    window_metrics: dict[int, dict[str, Any]] = {}
    window_splits: dict[str, dict[str, Any]] = {}
    for days in WINDOW_DAYS:
        wtrades = window_trades(p22a, p23a, raw, df, days, n)
        wm = trade_metrics(p22a, wtrades)
        window_metrics[days] = wm
        intended = [t for t in wtrades if is_intended_trade(t, key)]
        non_intended = [t for t in wtrades if not is_intended_trade(t, key)]
        window_splits[str(days) + "d"] = {
            "all": wm,
            "intended_session": trade_metrics(p22a, intended),
            "non_intended_session": trade_metrics(p22a, non_intended),
            "by_month": grouped_trade_metrics(p22a, wtrades, lambda t: str(t.get("day") or "")[:7]),
            "by_direction": grouped_trade_metrics(p22a, wtrades, lambda t: str(t.get("direction") or "NA")),
            "by_regime": grouped_trade_metrics(
                p22a,
                wtrades,
                lambda t: regime_bucket(str(t.get("regime") or "")),
            ),
        }

    oos_intended = [t for t in oos_trades if is_intended_trade(t, key)]
    oos_non = [t for t in oos_trades if not is_intended_trade(t, key)]
    oos_splits = {
        "intended_session": trade_metrics(p22a, oos_intended),
        "non_intended_session": trade_metrics(p22a, oos_non),
        "by_month": grouped_trade_metrics(p22a, oos_trades, lambda t: str(t.get("day") or "")[:7]),
        "by_direction": grouped_trade_metrics(p22a, oos_trades, lambda t: str(t.get("direction") or "NA")),
        "by_regime": grouped_trade_metrics(
            p22a,
            oos_trades,
            lambda t: regime_bucket(str(t.get("regime") or "")),
        ),
    }

    concentration = concentration_analysis(oos_trades)
    cv = p23a.cost_variants(oos_trades)
    cost_metrics = {k: p22a.metrics_from_rs(v) for k, v in cv.items()}

    mc = p23a.monte_carlo(p22a, oos_trades, MC_SEED)
    mc_p05 = float(mc.get("bootstrap", {}).get("p05_pf") or 0.0)
    rs_oos = [float(t["final_R"]) for t in oos_trades]
    dsr = deflated_sharpe_ratio(rs_oos, int(p23a.TOTAL_TRIALS))

    pbo_val = pbo_doc.get("PBO")
    pbo_reliable = bool(pbo_doc.get("reliable"))
    gates, gate_notes = certification_gates(
        oos_m,
        window_metrics,
        concentration,
        float(cost_metrics["realistic_slip"]["profit_factor"]),
        mc_p05,
        pbo_val is not None,
    )
    status = specialized_status(gates, pbo_val if isinstance(pbo_val, (int, float)) else None, pbo_reliable)
    risk = overfit_risk_label(pbo_val if isinstance(pbo_val, (int, float)) else None)

    return {
        "label": label,
        "key": key,
        "specialized_status": status,
        "overfit_risk": risk,
        "oos": oos_m,
        "oos_splits": oos_splits,
        "windows": {str(d) + "d": window_metrics[d] for d in WINDOW_DAYS},
        "window_splits": window_splits,
        "concentration": concentration,
        "cost_stress_oos": cost_metrics,
        "monte_carlo": mc,
        "dsr": dsr,
        "gates": gates,
        "gates_pass": all(gates.values()),
        "gate_notes": gate_notes,
        "walk_forward": {
            "pooled_oos": wf["pooled_oos"][key],
            "folds": wf["folds"],
            "slices": wf["slices"],
        },
        "rolling_stability": {
            "rolling_30d": rolling_stability(p22a, oos_trades, 30),
            "rolling_60d": rolling_stability(p22a, oos_trades, 60),
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p23a = load_p23a()
    p22a = p23a.load_phase22a()

    df = p22a.load_df()
    n = len(df)
    emit("DF bars=%s %s -> %s" % (n, df.index.min(), df.index.max()))
    ctx = p23a.build_ctx(p22a, df)

    emit("Collect frozen PA (hour 15 UTC) ...")
    raw_a = p23a.collect_model_a(p22a, ctx)
    orb_cfg = next(c for c in p23a.ORB_CONFIGS if str(c["strategy_id"]) == "ORB_30M_CONT")
    emit("Collect frozen ORB_30M_CONT ...")
    raw_b = p23a.collect_orb_variant(p22a, ctx, orb_cfg)

    raw_map = {"A": raw_a, "B": raw_b}
    model_names = {"A": "MODEL_A_LONDON_SWEEP", "B": "ORB_30M_CONT"}

    emit("Anchored walk-forward ...")
    wf = p23a.walk_forward(p22a, raw_map, n)

    emit("PBO/CSCV (2 strategies) ...")
    pbo = cscv_pbo(raw_map, n, p22a, p23a, model_names)

    pa = analyze_strategy("A", "PA", raw_a, wf, p22a, p23a, df, n, pbo)
    orb = analyze_strategy("B", "ORB", raw_b, wf, p22a, p23a, df, n, pbo)

    matrix = {
        "phase": "24A",
        "live_files_modified": False,
        "live_patch_applied": "NO",
        "research_only": True,
        "bars": n,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "strategies": {
            "PA": {"strategy_id": model_names["A"], **{k: v for k, v in pa.items() if k != "rolling_stability"}},
            "ORB": {"strategy_id": model_names["B"], **{k: v for k, v in orb.items() if k != "rolling_stability"}},
        },
        "acceptance": {
            "min_oos_trades": MIN_TRADES,
            "min_pf": MIN_PF,
            "min_exp_R": MIN_EXP,
            "max_dd_R": MAX_DD,
            "min_cost_realistic_pf": MIN_COST_PF,
            "min_mc_p05_pf": MIN_MC_P05_PF,
            "positive_windows_required": 3,
            "window_days": list(WINDOW_DAYS),
        },
        "pbo_summary": pbo,
    }

    rolling_out = {"phase": "24A", "PA": pa["rolling_stability"], "ORB": orb["rolling_stability"]}
    concentration_out = {"phase": "24A", "PA": pa["concentration"], "ORB": orb["concentration"]}
    mc_out = {"phase": "24A", "MC_BOOT": p23a.MC_BOOT, "seed": MC_SEED, "PA": pa["monte_carlo"], "ORB": orb["monte_carlo"]}
    dsr_out = {"phase": "24A", "n_trials": int(p23a.TOTAL_TRIALS), "PA": pa["dsr"], "ORB": orb["dsr"]}

    write_json(OUT / "specialized_certification_matrix.json", matrix)
    write_json(OUT / "rolling_stability.json", rolling_out)
    write_json(OUT / "concentration_analysis.json", concentration_out)
    write_json(OUT / "monte_carlo.json", mc_out)
    write_json(OUT / "pbo.json", pbo)
    write_json(OUT / "dsr.json", dsr_out)

    specialized = []
    conditional = []
    for name, pack in (("PA", pa), ("ORB", orb)):
        st = pack["specialized_status"]
        if st == "SPECIALIZED_CERTIFIED":
            specialized.append(name)
        elif st == "CONDITIONAL":
            conditional.append(name)

    pbo_shared = fmt(pbo.get("PBO"))
    result = "\n".join(
        [
            "PHASE_24A_RESULT",
            "PA_SPECIALIZED_STATUS=%s" % pa["specialized_status"],
            "PA_OOS_TRADES=%s" % pa["oos"]["trades"],
            "PA_OOS_PF=%s" % pa["oos"]["profit_factor"],
            "PA_OOS_EXP_R=%s" % pa["oos"]["expectancy_R"],
            "PA_COST_STRESS_PF=%s" % pa["cost_stress_oos"]["realistic_slip"]["profit_factor"],
            "PA_MC_P05_PF=%s" % pa["monte_carlo"]["bootstrap"]["p05_pf"],
            "PA_PBO=%s" % pbo_shared,
            "PA_DSR=%s" % fmt(pa["dsr"].get("DSR")),
            "",
            "ORB_SPECIALIZED_STATUS=%s" % orb["specialized_status"],
            "ORB_OOS_TRADES=%s" % orb["oos"]["trades"],
            "ORB_OOS_PF=%s" % orb["oos"]["profit_factor"],
            "ORB_OOS_EXP_R=%s" % orb["oos"]["expectancy_R"],
            "ORB_COST_STRESS_PF=%s" % orb["cost_stress_oos"]["realistic_slip"]["profit_factor"],
            "ORB_MC_P05_PF=%s" % orb["monte_carlo"]["bootstrap"]["p05_pf"],
            "ORB_PBO=%s" % pbo_shared,
            "ORB_DSR=%s" % fmt(orb["dsr"].get("DSR")),
            "",
            "PA_MONTH_CONCENTRATION=%s" % pa["concentration"]["top_month_profit_share"],
            "ORB_MONTH_CONCENTRATION=%s" % orb["concentration"]["top_month_profit_share"],
            "",
            "PA_DIRECTION_CONCENTRATION=%s" % pa["concentration"]["top_direction_profit_share"],
            "ORB_DIRECTION_CONCENTRATION=%s" % orb["concentration"]["top_direction_profit_share"],
            "",
            "SPECIALIZED_CANDIDATES=%s" % (",".join(specialized) if specialized else "NONE"),
            "CONDITIONAL_CANDIDATES=%s" % (",".join(conditional) if conditional else "NONE"),
            "",
            "LIVE_PATCH_APPLIED=NO",
            "",
        ]
    )
    write_text(OUT / "phase24a_result.txt", result)
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
