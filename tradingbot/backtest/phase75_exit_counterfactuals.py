"""Phase 75 — predeclared structural exit counterfactuals.

RESEARCH ONLY. Theoretical path walks. Not optimization. SL/TP in production unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    UNKNOWN,
    _dd,
    _git_head,
    _mean,
    _median,
    _parse_ts,
    _pf,
    _utc_now,
    load_setups,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import (
    BAR_MINUTES,
    TAPE_END_FALLBACK,
    _entry_index,
    load_frozen_ohlc,
    split_views,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74

PHASE = "75"
PHASE75_JSON = "logs/phase75_exit_counterfactuals.json"
PHASE75_MD = "docs/PHASE75_EXIT_COUNTERFACTUALS.md"
BLOCKED = "BLOCKED"
# Predeclared from Phase 68 median MFE-to-SL = 25 min on M5.
STAGNATION_BARS = 5
MEANINGFUL_PULLBACK_R = 0.25
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "counterfactuals",
    "oos_used_for_selection",
    "final_gate",
    "production_safety",
    "artifacts",
)


def walk_lock(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    trigger_r: float,
    lock_r: float,
) -> dict[str, Any]:
    """COUNTERFACTUAL: after MFE>=trigger_r, stop becomes entry +/- lock_r * risk. SL-before-TP."""
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return {"ok": False, "r": None, "reason": "invalid"}
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    lock_price = entry + lock_r * risk if buy else entry - lock_r * risk
    mfe = 0.0
    armed = False
    dyn_sl = sl
    for j in range(entry_idx + 1, len(df)):
        high = float(highs[j])
        low = float(lows[j])
        if buy:
            mfe = max(mfe, (high - entry) / risk)
            if (not armed) and mfe >= trigger_r:
                armed = True
                dyn_sl = lock_price
            hit_sl = low <= dyn_sl
            hit_tp = high >= tp
            if hit_sl:
                r = (dyn_sl - entry) / risk
                return {"ok": True, "r": float(r), "armed": armed, "exit": "lock" if armed else "sl", "bar": j}
            if hit_tp:
                r = (tp - entry) / risk
                return {"ok": True, "r": float(r), "armed": armed, "exit": "tp", "bar": j}
        else:
            mfe = max(mfe, (entry - low) / risk)
            if (not armed) and mfe >= trigger_r:
                armed = True
                dyn_sl = lock_price
            hit_sl = high >= dyn_sl
            hit_tp = low <= tp
            if hit_sl:
                r = (entry - dyn_sl) / risk
                return {"ok": True, "r": float(r), "armed": armed, "exit": "lock" if armed else "sl", "bar": j}
            if hit_tp:
                r = (entry - tp) / risk
                return {"ok": True, "r": float(r), "armed": armed, "exit": "tp", "bar": j}
    return {"ok": True, "r": None, "armed": armed, "exit": "open", "bar": None}


def walk_time_exit(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """COUNTERFACTUAL: after MFE>=0.5R, if STAGNATION_BARS pass with no new MFE and pullback>=0.25R, exit close."""
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return {"ok": False, "r": None, "reason": "invalid"}
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    mfe = 0.0
    seen_half = False
    bars_since = 0
    for j in range(entry_idx + 1, len(df)):
        high = float(highs[j])
        low = float(lows[j])
        close = float(closes[j])
        if buy:
            fav = (high - entry) / risk
            cur = (close - entry) / risk
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            fav = (entry - low) / risk
            cur = (entry - close) / risk
            hit_sl = high >= sl
            hit_tp = low <= tp
        new_mfe = fav > mfe + 1e-12
        if new_mfe:
            mfe = fav
            bars_since = 0
        else:
            bars_since += 1
        if mfe >= 0.5:
            seen_half = True
        if hit_sl:
            return {"ok": True, "r": -1.0, "armed": seen_half, "exit": "sl", "bar": j}
        if hit_tp:
            r = (tp - entry) / risk if buy else (entry - tp) / risk
            return {"ok": True, "r": float(r), "armed": seen_half, "exit": "tp", "bar": j}
        if seen_half and bars_since >= STAGNATION_BARS and (mfe - cur) >= MEANINGFUL_PULLBACK_R:
            return {"ok": True, "r": float(cur), "armed": True, "exit": "time", "bar": j}
    return {"ok": True, "r": None, "armed": seen_half, "exit": "open", "bar": None}


def classify_status(base_tr: float | None, cf_tr: float | None, base_va: float | None, cf_va: float | None) -> str:
    if cf_tr is None or base_tr is None:
        return "DATA_LIMITED"
    d_tr = cf_tr - base_tr
    d_va = (cf_va - base_va) if (cf_va is not None and base_va is not None) else 0.0
    if d_tr > 0 and d_va > 0:
        return "HELPFUL"
    if d_tr < 0 and d_va < 0:
        return "HARMFUL"
    return "NEUTRAL"


def subgroup(events: list[dict[str, Any]], cfs: list[float | None], key: str) -> dict[str, Any]:
    g: dict[str, list[tuple[float, float]]] = {}
    for e, r in zip(events, cfs):
        if r is None or e.get("r_result") is None:
            continue
        k = str(e.get(key) or UNKNOWN)
        g.setdefault(k, []).append((float(e["r_result"]), float(r)))
    out = {}
    for k, pairs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        orig = [a for a, _ in pairs]
        cf = [b for _, b in pairs]
        out[k] = {
            "n": len(pairs),
            "small_n": len(pairs) < 8,
            "orig_exp": _mean(orig),
            "cf_exp": _mean(cf),
            "delta_exp": None if not pairs else _mean(cf) - _mean(orig),
        }
    return out


def summarize_cf(
    name: str,
    events: list[dict[str, Any]],
    results: list[dict[str, Any]],
    views: dict[str, list[dict[str, Any]]],
    kind: str,
) -> dict[str, Any]:
    if kind == "DATA_LIMITED":
        return {
            "name": name,
            "kind": "COUNTERFACTUAL_THEORETICAL",
            "status": "DATA_LIMITED",
            "reason": results[0] if results else "insufficient",
            "n_affected": 0,
        }
    cf_r = [x.get("r") for x in results]
    orig = [_f(e.get("r_result")) for e in events]
    pairs = [(o, c) for o, c in zip(orig, cf_r) if o is not None and c is not None]
    orig_xs = [a for a, _ in pairs]
    cf_xs = [b for _, b in pairs]
    affected = sum(1 for x in results if x.get("armed") or x.get("exit") in {"lock", "time"})
    rescued = sum(1 for o, c in pairs if o < 0 and c > o)
    harmed = sum(1 for o, c in pairs if o > 0 and c < o)
    by_idx = {id(e): r for e, r in zip(events, cf_r)}

    def view_pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
        o = [_f(e.get("r_result")) for e in rows]
        c = [by_idx.get(id(e)) for e in rows]
        pr = [(a, b) for a, b in zip(o, c) if a is not None and b is not None]
        ox = [a for a, _ in pr]
        cx = [b for _, b in pr]
        return {
            "n": len(pr),
            "orig": pack_stats(ox),
            "cf": pack_stats(cx),
            "delta_expectancy": None if not pr else _mean(cx) - _mean(ox),
            "delta_median": None if not pr else (_median(cx) or 0) - (_median(ox) or 0),
            "delta_PF": None if not pr else ((_pf(cx) or 0) - (_pf(ox) or 0) if _pf(ox) is not None else None),
            "delta_DD": None if not pr else ((_dd(cx) or 0) - (_dd(ox) or 0) if _dd(ox) is not None else None),
        }

    full = view_pack(events)
    tr = view_pack(views["TRAIN"])
    va = view_pack(views["VALIDATION"])
    status = classify_status(
        (tr.get("orig") or {}).get("expectancy_R"),
        (tr.get("cf") or {}).get("expectancy_R"),
        (va.get("orig") or {}).get("expectancy_R"),
        (va.get("cf") or {}).get("expectancy_R"),
    )
    return {
        "name": name,
        "kind": "COUNTERFACTUAL_THEORETICAL",
        "status": status,
        "not_optimal": True,
        "n_events": len(pairs),
        "n_affected": affected,
        "original_expectancy": _mean(orig_xs),
        "counterfactual_expectancy": _mean(cf_xs),
        "delta_R_total": None if not pairs else float(sum(cf_xs) - sum(orig_xs)),
        "rescued_losers": rescued,
        "harmed_winners": harmed,
        "orig_median_R": _median(orig_xs),
        "cf_median_R": _median(cf_xs),
        "orig_PF": _pf(orig_xs),
        "cf_PF": _pf(cf_xs),
        "orig_DD": _dd(orig_xs),
        "cf_DD": _dd(cf_xs),
        "FULL": full,
        "TRAIN": tr,
        "VALIDATION": va,
        "OOS": view_pack(views["OOS"]),
        "RECENT_180D": view_pack(views["RECENT_180D"]),
        "by_side": subgroup(events, cf_r, "side"),
        "by_regime": subgroup(events, cf_r, "regime"),
        "by_session": subgroup(events, cf_r, "session"),
        "by_year": subgroup(events, cf_r, "year"),
        "oos_used_for_selection": False,
        "production_sl_moved": False,
    }


def run_phase75_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    ts_bar = {s.get("timestamp"): s.get("closed_bar_index") for s in signals}
    for e in events:
        e["closed_bar_index"] = ts_bar.get(e.get("timestamp"))
    df, _fp = load_frozen_ohlc(root)
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    specs = [
        ("A_BREAKEVEN_AFTER_0_5R", 0.5, 0.0),
        ("B_BREAKEVEN_AFTER_1R", 1.0, 0.0),
        ("C_LOCK_0_25R_AFTER_1R", 1.0, 0.25),
        ("D_LOCK_0_5R_AFTER_1R", 1.0, 0.5),
    ]
    cfs: dict[str, Any] = {}
    if df is None:
        for name, _a, _b in specs:
            cfs[name] = summarize_cf(name, events, ["parquet missing"], views, "DATA_LIMITED")
        cfs["E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION"] = summarize_cf(
            "E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION", events, ["parquet missing"], views, "DATA_LIMITED"
        )
    else:
        walks = {name: [] for name, _a, _b in specs}
        walks["E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION"] = []
        for e in events:
            entry, sl, tp = _f(e.get("entry")), _f(e.get("SL")), _f(e.get("TP"))
            idx = _entry_index(df, e)
            if entry is None or sl is None or tp is None or idx is None:
                miss = {"ok": False, "r": _f(e.get("r_result")), "armed": False, "exit": "fallback"}
                for name, _a, _b in specs:
                    walks[name].append(miss)
                walks["E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION"].append(miss)
                continue
            side = str(e.get("side"))
            for name, trig, lock in specs:
                walks[name].append(walk_lock(df, idx, side, entry, sl, tp, trig, lock))
            walks["E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION"].append(
                walk_time_exit(df, idx, side, entry, sl, tp)
            )
        for name, _a, _b in specs:
            cfs[name] = summarize_cf(name, events, walks[name], views, "OK")
        cfs["E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION"] = summarize_cf(
            "E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION",
            events,
            walks["E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION"],
            views,
            "OK",
        )
    cfs["F_REGIME_INVALIDATION_EXIT"] = summarize_cf(
        "F_REGIME_INVALIDATION_EXIT",
        events,
        [
            "INSUFFICIENT_DATA: jsonl stores regime at entry only; no causal timestamped regime path. "
            "Recomputing infer_regime_from_ohlcv would invent a new label series."
        ],
        views,
        "DATA_LIMITED",
    )
    cfs["G_SIGNAL_INVALIDATION_EXIT"] = summarize_cf(
        "G_SIGNAL_INVALIDATION_EXIT",
        events,
        [
            "INSUFFICIENT_DATA: asian_high/asian_low not persisted; checking later-bar sweep/reclaim "
            "requires rerunning evaluate_m5_london_sweep. Forbidden."
        ],
        views,
        "DATA_LIMITED",
    )
    helpful = [v for v in cfs.values() if v.get("status") == "HELPFUL"]
    helpful.sort(key=lambda x: -((x.get("TRAIN") or {}).get("delta_expectancy") or -1e9))
    best = helpful[0] if helpful else max(
        [v for v in cfs.values() if v.get("status") != "DATA_LIMITED"],
        key=lambda x: (x.get("TRAIN") or {}).get("delta_expectancy") or -1e9,
        default={},
    )
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "grid_search": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "predeclared": {
            "STAGNATION_BARS": STAGNATION_BARS,
            "STAGNATION_SOURCE": "Phase68 MEDIAN_TIME_TO_REVERSAL=25 min / M5",
            "MEANINGFUL_PULLBACK_R": MEANINGFUL_PULLBACK_R,
        },
        "counterfactuals": cfs,
        "BEST_STRUCTURAL_COUNTERFACTUAL": best.get("name"),
        "BEST_STRUCTURAL_COUNTERFACTUAL_STATUS": best.get("status"),
        "best_is_not_optimal": True,
        "selection_fold": "TRAIN_delta then VAL confirmation; OOS not used",
        "oos_used_for_selection": False,
        "hypotheses": [
            {
                "id": "H75-A",
                "claim": "Predeclared BE/lock/time-exit families can be classified HELPFUL/NEUTRAL/HARMFUL on TRAIN+VAL.",
                "result": best.get("status"),
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 7,
        "diagnostics_run": list(cfs.keys()),
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "SL_TP": "NOT_CHANGED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
            "theoretical_only": True,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE75_JSON, "md": PHASE75_MD},
    }
    (root / PHASE75_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE75_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 75 — Exit Mechanism Counterfactuals",
        "",
        "THEORETICAL / RESEARCH-ONLY. Production SL/TP were not moved. Not an optimum.",
        "",
        f"**BEST_STRUCTURAL_COUNTERFACTUAL (TRAIN-ranked among HELPFUL):** `{best.get('name')}` "
        f"status=`{best.get('status')}`",
        "",
        f"Time-exit uses predeclared {STAGNATION_BARS} M5 bars (Phase 68 median reversal 25 min) "
        f"and {MEANINGFUL_PULLBACK_R}R pullback from MFE.",
        "",
        "F/G = DATA_LIMITED (no timestamped regime path; no persisted Asian range / no strategy rerun).",
        "",
    ]
    for name, row in cfs.items():
        lines.append(
            f"- `{name}`: status=`{row.get('status')}` delta_TRAIN=`{(row.get('TRAIN') or {}).get('delta_expectancy')}` "
            f"rescued=`{row.get('rescued_losers')}` harmed_winners=`{row.get('harmed_winners')}`"
        )
    (root / PHASE75_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase75_collection(Path("."))
    print(p["BEST_STRUCTURAL_COUNTERFACTUAL"], p["BEST_STRUCTURAL_COUNTERFACTUAL_STATUS"])
