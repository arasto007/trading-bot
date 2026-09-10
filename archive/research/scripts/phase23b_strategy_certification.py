#!/usr/bin/env python3
"""PHASE 23B ? Alpha candidate certification (research-only, no live patches).

Certifies only explicit Phase 23A candidates. No parameter search. Live files untouched.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = ROOT / "logs" / "phase23b"
P23A_OUT = ROOT / "logs" / "phase23a"
CSCV_S = 8
FAMILY_KEYS = ("A", "B", "C")
MIN_OOS_TRADES = 50
MIN_PF = 1.30
MIN_EXP = 0.15
MAX_DD = 10.0
MIN_COST_PF = 1.05
MIN_MC_P05_PF = 0.95
ALLOW_SPECIALIZED_SHADOW = os.environ.get("PHASE23B_ALLOW_SPECIALIZED_SHADOW", "").strip().upper() in (
    "1",
    "YES",
    "TRUE",
)
MC_SEED = 20260818


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


def parse_phase23a_result(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_candidates(raw: str, selected_orb: str, selected_mom: str) -> list[dict[str, str]]:
    if not raw or raw.upper() == "NONE":
        return []
    items: list[dict[str, str]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token == "MODEL_B_ORB" or token.startswith("ORB_"):
            sid = token if token.startswith("ORB_") else selected_orb
            items.append({"key": "B", "strategy_id": sid, "label": "MODEL_B_ORB"})
        elif token in ("MODEL_A", "MODEL_A_LONDON_SWEEP", "A"):
            items.append({"key": "A", "strategy_id": "MODEL_A_LONDON_SWEEP", "label": "MODEL_A_LONDON_SWEEP"})
        elif token.startswith("MOM_") or token == "MODEL_C_MOM":
            sid = token if token.startswith("MOM_") else selected_mom
            items.append({"key": "C", "strategy_id": sid, "label": "MODEL_C_MOM"})
        else:
            items.append({"key": "?", "strategy_id": token, "label": token})
    return items


def sharpe_rs(rs: list[float]) -> float:
    if len(rs) < 2:
        return float(np.mean(rs)) if rs else -1e9
    arr = np.asarray(rs, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd <= 1e-12:
        return float(arr.mean()) * 10.0
    return float(arr.mean() / sd * math.sqrt(len(arr)))


def metrics_pack(p22a, rs: list[float]) -> dict[str, Any]:
    return p22a.metrics_from_rs(rs)


def regime_bucket(reg: str) -> str:
    r = str(reg)
    if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return "trend"
    if r in ("VOLATILE", "CRISIS"):
        return "expansion"
    return "ranging"


def grouped_metrics(p22a, trades: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    groups: defaultdict[str, list] = defaultdict(list)
    for t in trades:
        groups[str(key_fn(t))].append(t)
    out: dict[str, dict[str, Any]] = {}
    for k, rows in sorted(groups.items()):
        rs = [float(x["final_R"]) for x in rows]
        m = metrics_pack(p22a, rs)
        m["n"] = len(rows)
        out[k] = m
    return out


def catastrophic_buckets(bucket_metrics: dict[str, dict[str, Any]], min_n: int = 8) -> bool:
    for m in bucket_metrics.values():
        n = int(m.get("n") or m.get("trades") or 0)
        if n < min_n:
            continue
        pf = float(m["profit_factor"])
        exp = float(m["expectancy_R"])
        if pf < 0.50 or exp < -0.50:
            return True
    return False


def direction_collapse(bucket_metrics: dict[str, dict[str, Any]], min_n: int = 8) -> bool:
    for m in bucket_metrics.values():
        n = int(m.get("n") or 0)
        if n < min_n:
            continue
        pf = float(m["profit_factor"])
        exp = float(m["expectancy_R"])
        if pf < 0.50 and exp < -0.50:
            return True
    return False


def hour_dependency_class(trades: list[dict[str, Any]], min_n: int = 8, threshold: float = 0.55) -> tuple[str, dict[str, Any]]:
    groups: defaultdict[str, list[float]] = defaultdict(list)
    for t in trades:
        h = t.get("hour")
        if h is None:
            continue
        groups[str(int(h))].append(float(t["final_R"]))
    gross_by_hour: dict[str, float] = {}
    total_gross = 0.0
    for h, rs in groups.items():
        g = sum(r for r in rs if r > 0)
        gross_by_hour[h] = g
        total_gross += g
    dominant_hour = None
    dominant_share = 0.0
    dominant_n = 0
    if total_gross > 0:
        for h, g in gross_by_hour.items():
            share = g / total_gross
            if share > dominant_share:
                dominant_share = share
                dominant_hour = h
                dominant_n = len(groups[h])
    specialized = dominant_share > threshold and dominant_n >= min_n
    detail = {
        "total_gross_profit_R": round(total_gross, 4),
        "dominant_hour": dominant_hour,
        "dominant_hour_gross_share": round(dominant_share, 4),
        "dominant_hour_n": dominant_n,
        "threshold": threshold,
        "by_hour_gross": {k: round(v, 4) for k, v in sorted(gross_by_hour.items())},
    }
    cls = "SPECIALIZED" if specialized else "UNIVERSALLY_ROBUST"
    return cls, detail


def cscv_pbo(raw_map: dict[str, list[dict[str, Any]]], n: int, p22a, names: dict[str, str]) -> dict[str, Any]:
    edges = p23a_slice_edges(n, CSCV_S)
    blocks = {k: [] for k in FAMILY_KEYS}
    for s in range(CSCV_S):
        lo, hi = int(edges[s]), int(edges[s + 1])
        for k in FAMILY_KEYS:
            sub = p23a_filter_range(raw_map[k], lo, hi)
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
        "PBO estimated on n_models=%s (A/B/C families). With only 3 models CSCV power is low; "
        "treat PBO as indicative, not definitive."
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
        "note_unreliable_n_models_3": n_models == 3,
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


def overfit_risk_label(
    pbo_val: float | None,
    pbo_reliable: bool,
    is_pf: float,
    oos_pf: float,
    pcv_min: float,
) -> str:
    if pbo_reliable and pbo_val is not None and float(pbo_val) >= 0.45:
        return "HIGH"
    if pbo_reliable and pbo_val is not None and float(pbo_val) >= 0.25:
        return "MEDIUM"
    if is_pf > 0 and oos_pf < is_pf * 0.65:
        return "HIGH"
    if pcv_min < 0.85 or oos_pf < 1.0:
        return "MEDIUM"
    return "LOW"


def certification_gates(
    oos: dict[str, Any],
    cost_realistic_pf: float,
    mc_p05_pf: float,
    cat_reg: bool,
    cat_sess: bool,
    dir_bad: bool,
) -> dict[str, bool]:
    ntr = int(oos.get("trades") or 0)
    pf = float(oos.get("profit_factor") or 0.0)
    exp = float(oos.get("expectancy_R") or 0.0)
    dd = float(oos.get("max_dd_R") or 0.0)
    return {
        "oos_trades_ge_50": ntr >= MIN_OOS_TRADES,
        "oos_pf_ge_1_30": pf >= MIN_PF,
        "oos_exp_ge_0_15": exp >= MIN_EXP,
        "oos_maxdd_le_10R": dd <= MAX_DD,
        "cost_realistic_slip_pf_ge_1_05": cost_realistic_pf >= MIN_COST_PF,
        "mc_p05_pf_ge_0_95": mc_p05_pf >= MIN_MC_P05_PF,
        "no_catastrophic_regime": not cat_reg,
        "no_catastrophic_session": not cat_sess,
        "direction_stability": not dir_bad,
    }


def fmt(v: Any) -> str:
    if v is None:
        return "NA"
    return str(v)


# late-bound helpers from p23a module
p23a_filter_range = None
p23a_slice_edges = None


def main() -> int:
    global p23a_filter_range, p23a_slice_edges
    OUT.mkdir(parents=True, exist_ok=True)
    p23a = load_p23a()
    p23a_filter_range = p23a.filter_range
    p23a_slice_edges = p23a.slice_edges
    p22a = p23a.load_phase22a()

    matrix_path = P23A_OUT / "strategy_matrix.json"
    selected_orb = "ORB_30M_CONT"
    selected_mom = "MOM_30M"
    if matrix_path.is_file():
        matrix23a = json.loads(matrix_path.read_text(encoding="utf-8"))
        selected_orb = str(matrix23a.get("selected_orb") or selected_orb)
        selected_mom = str(matrix23a.get("selected_momentum") or selected_mom)

    p23a_lines = parse_phase23a_result(P23A_OUT / "phase23a_result.txt")
    cand_raw = p23a_lines.get("CANDIDATES_FOR_PHASE23B", "NONE")
    candidates = parse_candidates(cand_raw, selected_orb, selected_mom)
    emit("Phase 23A candidates: %s -> %s" % (cand_raw, [c["label"] for c in candidates]))

    df = p22a.load_df()
    n = len(df)
    emit("DF bars=%s %s -> %s" % (n, df.index.min(), df.index.max()))
    ctx = p23a.build_ctx(p22a, df)

    emit("Rebuild MODEL A ...")
    raw_a = p23a.collect_model_a(p22a, ctx)
    orb_variants: dict[str, list[dict[str, Any]]] = {}
    for cfg in p23a.ORB_CONFIGS:
        sid = str(cfg["strategy_id"])
        emit("  ORB variant %s ..." % sid)
        orb_variants[sid] = p23a.collect_orb_variant(p22a, ctx, cfg)
    mom_variants: dict[str, list[dict[str, Any]]] = {}
    for cfg in p23a.MOM_CONFIGS:
        sid = str(cfg["strategy_id"])
        emit("  MOM variant %s ..." % sid)
        mom_variants[sid] = p23a.collect_mom_variant(p22a, ctx, cfg)

    edges = p23a.slice_edges(n, p23a.N_SLICES)
    research_hi = int(edges[2])
    pick_mom = p23a.pick_variant(p22a, mom_variants, 0, research_hi)
    frozen_orb = selected_orb
    if frozen_orb not in orb_variants:
        frozen_orb = p23a.pick_variant(p22a, orb_variants, 0, research_hi)
    emit("frozen ORB=%s picked MOM=%s research [0,%s)" % (frozen_orb, pick_mom, research_hi))

    raw_map = {
        "A": raw_a,
        "B": orb_variants[frozen_orb],
        "C": mom_variants[pick_mom],
    }
    model_names = {
        "A": "MODEL_A_LONDON_SWEEP",
        "B": frozen_orb,
        "C": pick_mom,
    }

    emit("walk-forward OOS ...")
    wf = p23a.walk_forward(p22a, raw_map, n)

    family_ref: dict[str, Any] = {}
    for key in FAMILY_KEYS:
        oos_m = wf["pooled_oos"][key]
        family_ref[key] = {
            "model": model_names[key],
            "pooled_oos": oos_m,
            "reference_only": True,
        }

    emit("PBO/CSCV on A/B/C families ...")
    pbo = cscv_pbo(raw_map, n, p22a, model_names)

    certified_models: list[str] = []
    best_certified = "NONE"
    result_pack: dict[str, Any] = {}
    cert_matrix_candidates: dict[str, Any] = {}

    if not candidates:
        emit("No 23A candidates ? reference metrics only.")
    else:
        for cand in candidates:
            key = cand["key"]
            if key not in raw_map:
                emit("Skip unknown candidate key %s" % key)
                continue
            label = cand["label"]
            emit("Certifying %s (%s / %s) ..." % (label, key, cand["strategy_id"]))
            raw = raw_map[key]
            oos_trades = wf["pooled_oos_trades"][key]
            oos_m = wf["pooled_oos"][key]

            pcv = p23a.purged_cv(p22a, raw, n)
            cv = p23a.cost_variants(oos_trades)
            cost_metrics = {k: metrics_pack(p22a, v) for k, v in cv.items()}
            mc = p23a.monte_carlo(p22a, oos_trades, MC_SEED)
            mc_p05 = float(mc.get("bootstrap", {}).get("p05_pf") or 0.0)

            rs_oos = [float(t["final_R"]) for t in oos_trades]
            dsr = deflated_sharpe_ratio(rs_oos, int(p23a.TOTAL_TRIALS))

            by_regime = grouped_metrics(p22a, oos_trades, lambda t: regime_bucket(str(t.get("regime") or "")))
            by_session = grouped_metrics(p22a, oos_trades, lambda t: str(t.get("session") or "NA"))
            by_direction = grouped_metrics(p22a, oos_trades, lambda t: str(t.get("direction") or "NA"))
            by_hour = grouped_metrics(p22a, oos_trades, lambda t: str(t.get("hour") or "NA"))

            cat_reg = catastrophic_buckets(by_regime)
            cat_sess = catastrophic_buckets(by_session)
            dir_bad = direction_collapse(by_direction)
            robustness, hour_detail = hour_dependency_class(oos_trades)

            gates = certification_gates(
                oos_m,
                float(cost_metrics["realistic_slip"]["profit_factor"]),
                mc_p05,
                cat_reg,
                cat_sess,
                dir_bad,
            )
            gates_pass = all(gates.values())
            universally = gates_pass and robustness == "UNIVERSALLY_ROBUST"
            certified = universally
            shadow = bool(certified or (ALLOW_SPECIALIZED_SHADOW and gates_pass and robustness == "SPECIALIZED"))

            is_m = wf["folds"][0]["models"][key]["research"] if wf["folds"] else oos_m
            risk = overfit_risk_label(
                pbo.get("PBO"),
                bool(pbo.get("reliable")),
                float(is_m.get("profit_factor") or 0),
                float(oos_m.get("profit_factor") or 0),
                float(pcv["aggregate"]["min_test_pf"]),
            )

            if certified:
                certified_models.append(label)
                best_certified = label

            cert_matrix_candidates[label] = {
                "key": key,
                "strategy_id": model_names[key],
                "certified": certified,
                "robustness_class": robustness,
                "gates": gates,
                "gates_pass": gates_pass,
                "walk_forward": wf,
                "purged_cv": pcv,
                "cost_stress_oos": cost_metrics,
                "stability": {
                    "by_regime": by_regime,
                    "by_session": by_session,
                    "by_direction": by_direction,
                    "by_hour": by_hour,
                    "catastrophic_regime": cat_reg,
                    "catastrophic_session": cat_sess,
                    "direction_collapse": dir_bad,
                    "hour_dependency": hour_detail,
                },
                "monte_carlo": mc,
                "dsr": dsr,
                "overfit_risk": risk,
                "certified_for_shadow": shadow,
            }

            result_pack = {
                "label": label,
                "oos_m": oos_m,
                "cost_pf": cost_metrics["realistic_slip"]["profit_factor"],
                "mc_p05": mc_p05,
                "pbo": pbo.get("PBO"),
                "dsr": dsr.get("DSR"),
                "risk": risk,
                "shadow": shadow,
                "certified_models": certified_models,
            }

    mc_out = {
        "phase": "23B",
        "MC_BOOT": p23a.MC_BOOT,
        "seed": MC_SEED,
        "candidates": {k: v.get("monte_carlo") for k, v in cert_matrix_candidates.items()},
        "family_reference_pooled_oos_trades": {
            k: p23a.monte_carlo(p22a, wf["pooled_oos_trades"][k], MC_SEED) for k in FAMILY_KEYS
        },
    }

    matrix_out = {
        "phase": "23B",
        "live_files_modified": False,
        "meta_used": False,
        "bars": n,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "phase23a_candidates_raw": cand_raw,
        "frozen_orb": frozen_orb,
        "frozen_momentum": pick_mom,
        "model_names": model_names,
        "family_reference": family_ref,
        "candidates": cert_matrix_candidates,
        "acceptance": {
            "min_oos_trades": MIN_OOS_TRADES,
            "min_pf": MIN_PF,
            "min_exp_R": MIN_EXP,
            "max_dd_R": MAX_DD,
            "min_cost_realistic_pf": MIN_COST_PF,
            "min_mc_p05_pf": MIN_MC_P05_PF,
        },
    }

    (OUT / "certification_matrix.json").write_text(json.dumps(matrix_out, indent=2, default=str), encoding="utf-8")
    (OUT / "pbo.json").write_text(json.dumps(pbo, indent=2, default=str), encoding="utf-8")
    (OUT / "monte_carlo.json").write_text(json.dumps(mc_out, indent=2, default=str), encoding="utf-8")

    dsr_doc = {
        "phase": "23B",
        "n_trials": int(p23a.TOTAL_TRIALS),
        "by_candidate": {k: v.get("dsr") for k, v in cert_matrix_candidates.items()},
        "family_reference": {
            k: deflated_sharpe_ratio(
                [float(t["final_R"]) for t in wf["pooled_oos_trades"][k]],
                int(p23a.TOTAL_TRIALS),
            )
            for k in FAMILY_KEYS
        },
    }
    (OUT / "dsr.json").write_text(json.dumps(dsr_doc, indent=2, default=str), encoding="utf-8")

    if result_pack:
        rp = result_pack
        oos_m = rp["oos_m"]
        result = "\n".join(
            [
                "PHASE_23B_RESULT",
                "CERTIFIED_MODELS=%s" % (",".join(rp["certified_models"]) if rp["certified_models"] else "NONE"),
                "BEST_MODEL=%s" % (rp["certified_models"][0] if rp["certified_models"] else rp["label"]),
                "OOS_TRADES=%s" % oos_m.get("trades"),
                "OOS_PF=%s" % oos_m.get("profit_factor"),
                "OOS_EXP_R=%s" % oos_m.get("expectancy_R"),
                "OOS_MAX_DD=%s" % oos_m.get("max_dd_R"),
                "COST_STRESS_PF=%s" % rp["cost_pf"],
                "MC_P05_PF=%s" % rp["mc_p05"],
                "PBO=%s" % fmt(rp["pbo"]),
                "DSR=%s" % fmt(rp["dsr"]),
                "OVERFIT_RISK=%s" % rp["risk"],
                "CERTIFIED_FOR_SHADOW=%s" % ("YES" if rp["shadow"] else "NO"),
                "LIVE_PATCH_APPLIED=NO",
                "",
            ]
        )
    else:
        result = "\n".join(
            [
                "PHASE_23B_RESULT",
                "CERTIFIED_MODELS=NONE",
                "BEST_MODEL=NONE",
                "OOS_TRADES=0",
                "OOS_PF=0",
                "OOS_EXP_R=0",
                "OOS_MAX_DD=0",
                "COST_STRESS_PF=0",
                "MC_P05_PF=0",
                "PBO=%s" % fmt(pbo.get("PBO")),
                "DSR=NA",
                "OVERFIT_RISK=HIGH",
                "CERTIFIED_FOR_SHADOW=NO",
                "LIVE_PATCH_APPLIED=NO",
                "",
            ]
        )

    (OUT / "phase23b_result.txt").write_text(result, encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
