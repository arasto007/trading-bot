#!/usr/bin/env python3
"""PHASE 22D multi-strategy portfolio router backtest. Research only. No live patches."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_DRY_RUN": "1",
})

from tradingbot.config.dotenv_loader import load_dotenv
load_dotenv()

from tradingbot.research.portfolio_router import (
    CANDIDATE_ENGINES,
    ENGINE_HTF_LIQUIDITY,
    ENGINE_NONE,
    ENGINE_PA_CURRENT,
    ENGINE_SWEEP_MSS_FVG,
    MODEL_TO_ENGINE,
    PortfolioRouter,
    ResearchEngine,
    RouterLimits,
)

OUT = ROOT / "logs" / "phase22d"
LOG_JSONL = ROOT / "logs" / "engines" / "portfolio_router_decisions.jsonl"
CERT_22B = ROOT / "logs" / "phase22b" / "certification_matrix.json"
TEL_DIR = OUT / "engine_telemetry"


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_phase22a():
    path = ROOT / "scripts" / "phase22a_strategy_discovery.py"
    spec = importlib.util.spec_from_file_location("phase22a_strategy_discovery", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_certified() -> set[str]:
    if not CERT_22B.is_file():
        return set()
    blob = json.loads(CERT_22B.read_text(encoding="utf-8"))
    names: set[str] = set()
    if blob.get("certified") is True:
        for x in blob.get("candidates_from_22a") or []:
            names.add(MODEL_TO_ENGINE.get(str(x), str(x)))
    for line in str(blob.get("result_block") or "").splitlines():
        if line.startswith("CERTIFIED_MODELS="):
            val = line.split("=", 1)[1].strip()
            if val and val != "NONE":
                for part in val.split(","):
                    p = part.strip()
                    names.add(MODEL_TO_ENGINE.get(p, p))
    names.discard("NONE")
    names.discard("")
    return names


def oos_quality_map(blob: dict[str, Any]) -> dict[str, dict[str, float]]:
    pooled = ((blob.get("walk_forward") or {}).get("pooled_oos")) or {}
    out = {}
    mapping = {
        "MODEL_A_CURRENT_PA": ENGINE_PA_CURRENT,
        "MODEL_B_SWEEP_MSS_FVG": ENGINE_SWEEP_MSS_FVG,
        "MODEL_C_HTF_LIQUIDITY": ENGINE_HTF_LIQUIDITY,
    }
    for src, eng in mapping.items():
        m = pooled.get(src) or {}
        pf = float(m.get("profit_factor") or 0.0)
        exp = float(m.get("expectancy_R") or 0.0)
        quality = 0.5 * min(max(pf, 0.0), 3.0) / 3.0 + 0.5 * (max(min(exp, 0.5), -0.5) + 0.5)
        out[eng] = {"pf": pf, "exp": exp, "quality": round(quality, 4), "trades": int(m.get("trades") or 0)}
    return out


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
    raw_a = p22a.collect_a(ctx, ny_s, ny_e, asian_end)
    raw_b, fun_b = p22a.collect_structural(ctx, session=p22a.B_SESSION, use_htf_levels=False, require_pd=False)
    raw_c, fun_c = p22a.collect_structural(ctx, session=p22a.C_SESSION, use_htf_levels=True, require_pd=True)
    return df, {
        ENGINE_PA_CURRENT: raw_a,
        ENGINE_SWEEP_MSS_FVG: raw_b,
        ENGINE_HTF_LIQUIDITY: raw_c,
    }, {"B": fun_b, "C": fun_c}

def summarize_rs(p22a, rs: list[float]) -> dict[str, Any]:
    return p22a.metrics_from_rs(rs)


def daily_series(signals, field: str = "realized_r") -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for s in signals:
        acc[s.day] += float(getattr(s, field))
    return dict(acc)


def corr_map(series: dict[str, dict[str, float]]) -> dict[str, float]:
    keys = list(series.keys())
    out = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            days = sorted(set(series[a]) | set(series[b]))
            if len(days) < 8:
                out["%s__%s" % (a, b)] = None
                continue
            xa = np.array([series[a].get(d, 0.0) for d in days], dtype=float)
            xb = np.array([series[b].get(d, 0.0) for d in days], dtype=float)
            if xa.std() < 1e-12 or xb.std() < 1e-12:
                out["%s__%s" % (a, b)] = 0.0
            else:
                out["%s__%s" % (a, b)] = round(float(np.corrcoef(xa, xb)[0, 1]), 4)
    return out


def overlap_stats(engines: dict[str, ResearchEngine], cluster: int = 6) -> dict[str, Any]:
    buckets: dict[tuple[str, str, int], set[str]] = defaultdict(set)
    for mid, eng in engines.items():
        for sig in eng.all_signals():
            buckets[(sig.day, sig.direction, sig.bar_index // cluster)].add(mid)
    n = len(buckets)
    multi = sum(1 for v in buckets.values() if len(v) >= 2)
    pair_counts: dict[str, int] = defaultdict(int)
    for v in buckets.values():
        names = sorted(v)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                pair_counts["%s__%s" % (a, b)] += 1
    return {
        "clusters": n,
        "multi_engine_clusters": multi,
        "overlap_rate": round(multi / n, 4) if n else 0.0,
        "pair_counts": dict(pair_counts),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write_engine_telemetry(engines: dict[str, ResearchEngine], selected_ids: set[str]) -> None:
    TEL_DIR.mkdir(parents=True, exist_ok=True)
    for mid, eng in engines.items():
        rows = []
        for sig in eng.all_signals():
            rows.append({
                "timestamp": sig.timestamp,
                "model_id": sig.model_id,
                "setup_id": sig.setup_id,
                "direction": sig.direction,
                "confidence": sig.confidence,
                "expected_edge": sig.expected_edge,
                "regime": sig.regime,
                "session": sig.session,
                "reason": sig.reason,
                "certified": sig.certified,
                "selected": sig.setup_id in selected_ids,
                "duplicate_key": sig.duplicate_key,
            })
        (TEL_DIR / ("%s.jsonl" % mid.lower())).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p22a = load_phase22a()
    certified = load_certified()
    blob = json.loads(CERT_22B.read_text(encoding="utf-8")) if CERT_22B.is_file() else {}
    qmap = oos_quality_map(blob)
    emit("certified engines=%s" % (sorted(certified) or ["NONE"]))
    emit("collect A/B/C research setups (not live) ...")
    df, raw_map, funnels = collect_family(p22a)
    emit("bars=%s A=%s B=%s C=%s" % (
        len(df), len(raw_map[ENGINE_PA_CURRENT]), len(raw_map[ENGINE_SWEEP_MSS_FVG]), len(raw_map[ENGINE_HTF_LIQUIDITY])
    ))

    engines = {}
    for mid, raw in raw_map.items():
        q = qmap.get(mid) or {"quality": 0.0, "exp": 0.0}
        engines[mid] = ResearchEngine(
            mid,
            certified=mid in certified,
            oos_quality=float(q.get("quality") or 0.0),
            expected_edge=float(q.get("exp") or 0.0),
            setups=raw,
        )
    limits = RouterLimits(max_trades_day=3, cooldown_bars=18, open_hold_bars=12, max_daily_risk_r=3.0)
    router = PortfolioRouter(engines.values(), limits=limits)

    bars = sorted({sig.bar_index for eng in engines.values() for sig in eng.all_signals()})
    decisions = []
    selected = []
    selected_ids: set[str] = set()
    for i in bars:
        cands = router.collect(i)
        if not cands:
            continue
        dec = router.decide(cands)
        decisions.append(dec.to_log())
        if dec.selected is not None:
            selected.append(dec.selected)
            selected_ids.add(dec.selected.setup_id)

    write_jsonl(LOG_JSONL, decisions)
    write_engine_telemetry(engines, selected_ids)
    emit("router events=%s selected=%s jsonl=%s" % (len(decisions), len(selected), LOG_JSONL))

    pa_cd = p22a.apply_cd(raw_map[ENGINE_PA_CURRENT])
    pa_rs = [float(t["final_R"]) for t in pa_cd]
    pa_sp = [float(t.get("final_R_spread") or 0.0) for t in pa_cd]
    pa_st = [float(t.get("final_R_stress") or 0.0) for t in pa_cd]
    port_rs = [s.realized_r for s in selected]
    port_sp = [s.final_R_spread for s in selected]
    port_st = [s.final_R_stress for s in selected]
    pa_m = summarize_rs(p22a, pa_rs)
    port_m = summarize_rs(p22a, port_rs)
    pa_cost = {"spread": summarize_rs(p22a, pa_sp), "stress": summarize_rs(p22a, pa_st)}
    port_cost = {"spread": summarize_rs(p22a, port_sp), "stress": summarize_rs(p22a, port_st)}

    contrib: dict[str, float] = defaultdict(float)
    contrib_n: dict[str, int] = defaultdict(int)
    for s in selected:
        contrib[s.model_id] += s.realized_r
        contrib_n[s.model_id] += 1
    raw_daily = {}
    for mid, eng in engines.items():
        cd = p22a.apply_cd(raw_map[mid])
        acc: dict[str, float] = defaultdict(float)
        for t in cd:
            acc[str(t.get("day") or "")] += float(t.get("final_R") or 0.0)
        raw_daily[mid] = dict(acc)

    ov = overlap_stats(engines)
    block_counts: dict[str, int] = defaultdict(int)
    for d in decisions:
        for b in d.get("blocked_engines") or []:
            block_counts["%s:%s" % (b.get("engine"), b.get("reason"))] += 1

    production_enabled = False
    live_patch = False
    result_lines = [
        "PHASE_22D_RESULT",
        "",
        "CERTIFIED_ENGINES=%s" % (",".join(sorted(certified)) if certified else "NONE"),
        "PRODUCTION_ENABLED=NO",
        "LIVE_PATCH_APPLIED=NO",
        "",
        "PA_ONLY_TRADES=%s" % pa_m["trades"],
        "PA_ONLY_PF=%s" % pa_m["profit_factor"],
        "PA_ONLY_EXPR=%s" % pa_m["expectancy_R"],
        "PA_ONLY_DD=%s" % pa_m["max_dd_R"],
        "PA_ONLY_STREAK=%s" % pa_m["longest_losing_streak"],
        "",
        "PORTFOLIO_TRADES=%s" % port_m["trades"],
        "PORTFOLIO_PF=%s" % port_m["profit_factor"],
        "PORTFOLIO_EXPR=%s" % port_m["expectancy_R"],
        "PORTFOLIO_DD=%s" % port_m["max_dd_R"],
        "PORTFOLIO_STREAK=%s" % port_m["longest_losing_streak"],
        "",
        "PA_COST_STRESS_PF=%s" % pa_cost["stress"]["profit_factor"],
        "PORTFOLIO_COST_STRESS_PF=%s" % port_cost["stress"]["profit_factor"],
        "ENGINE_OVERLAP_RATE=%s" % ov["overlap_rate"],
        "ROUTER_EVENTS=%s" % len(decisions),
        "SELECTED_ENGINE_NONE_RATE=%s" % round(
            sum(1 for d in decisions if d["selected_engine"] == ENGINE_NONE) / len(decisions), 4
        ) if decisions else 0.0,
        "",
    ]
    result = "\n".join(result_lines)
    matrix = {
        "phase": "22D",
        "live_files_modified": live_patch,
        "production_enabled": production_enabled,
        "certified_engines": sorted(certified),
        "candidate_engines": list(CANDIDATE_ENGINES),
        "oos_quality": qmap,
        "funnels": funnels,
        "limits": {
            "max_trades_day": limits.max_trades_day,
            "cooldown_bars": limits.cooldown_bars,
            "max_daily_risk_r": limits.max_daily_risk_r,
            "open_hold_bars": limits.open_hold_bars,
        },
        "router_rule": "never_select_uncertified",
        "comparison": {
            "pa_only": {**pa_m, "cost": pa_cost},
            "portfolio": {
                **port_m,
                "cost": port_cost,
                "engine_contribution_R": {k: round(v, 4) for k, v in contrib.items()},
                "engine_contribution_n": dict(contrib_n),
            },
        },
        "engine_overlap": ov,
        "engine_correlation_raw_daily": corr_map(raw_daily),
        "block_counts": dict(block_counts),
        "decision_log": str(LOG_JSONL),
        "n_router_events": len(decisions),
        "result_block": result,
    }
    (OUT / "router_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    extra = result + "NOTES\n" + json.dumps({
        "block_counts": dict(block_counts),
        "overlap": ov,
        "correlation": corr_map(raw_daily),
        "contribution": dict(contrib),
        "live_multi_engine_router_modified": False,
    }, indent=2) + "\nLIVE_PATCH_APPLIED=NO\n"
    (OUT / "phase22d_result.txt").write_text(extra, encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())