"""Phase 83 — predeclared structural profit-protection counterfactuals.

THEORETICAL path walks. Not optimization. Stop known at bar open; trail updates at bar close.
Same-bar new-MFE vs new-floor is AMBIGUOUS: do not assume favorable price first.
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
    _git_head,
    _parse_ts,
    _utc_now,
    load_setups,
)
from tradingbot.backtest.phase68_exit_forensics import (
    EXTREME_R,
    TAPE_END_FALLBACK,
    _entry_index,
    load_frozen_ohlc,
    split_views,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase75_exit_counterfactuals import summarize_cf
from tradingbot.backtest.phase82_profit_protection_design import (
    MEANINGFUL_MFE_R,
    PHASE82_JSON,
    STRUCTURAL_FRACTION,
)

PHASE = "83"
PHASE83_JSON = "logs/phase83_profit_protection_counterfactuals.json"
PHASE83_MD = "docs/PHASE83_PROFIT_PROTECTION_COUNTERFACTUALS.md"
BLOCKED = "BLOCKED"
TESTABLE_FAMILIES = ("PEAK_RETRACE_EXIT", "MFE_FRACTION_FLOOR", "SWING_PROTECTION")
MODE_BY_FAMILY = {
    "PEAK_RETRACE_EXIT": "peak_retrace",
    "MFE_FRACTION_FLOOR": "mfe_oneshot",
    "SWING_PROTECTION": "swing",
    "HYBRID": "hybrid",
}
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "counterfactuals",
    "oos_used_for_selection",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _empty(reason: str) -> dict[str, Any]:
    return {"ok": False, "r": None, "armed": False, "exit": reason, "ambiguous": False, "bar": None}


def walk_protection(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    mode: str,
) -> dict[str, Any]:
    """Causal trail: dyn SL known at bar open; MFE/swing/floor update at bar close."""
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return _empty("invalid")
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    mfe = 0.0
    armed = False
    lock_r: float | None = None
    pending_sl = float(sl)
    swing_sl: float | None = None
    amb = False
    orig_sl = float(sl)
    for j in range(entry_idx + 1, len(df)):
        dyn_sl = pending_sl
        high = float(highs[j])
        low = float(lows[j])
        if buy:
            hit_sl = low <= dyn_sl
            hit_tp = high >= tp
            fav = (high - entry) / risk
        else:
            hit_sl = high >= dyn_sl
            hit_tp = low <= tp
            fav = (entry - low) / risk
        grew = fav > mfe + 1e-12
        hypo_mfe = max(mfe, fav)
        hypo_armed = armed or hypo_mfe >= MEANINGFUL_MFE_R
        hypo_floor = dyn_sl
        if hypo_armed and mode in {"peak_retrace", "hybrid"}:
            fr = STRUCTURAL_FRACTION * hypo_mfe
            hypo_floor = entry + fr * risk if buy else entry - fr * risk
        elif hypo_armed and mode == "mfe_oneshot":
            lr = lock_r if lock_r is not None else STRUCTURAL_FRACTION * hypo_mfe
            hypo_floor = entry + lr * risk if buy else entry - lr * risk
        if buy:
            hit_hypo = low <= hypo_floor
        else:
            hit_hypo = high >= hypo_floor
        if grew and hypo_armed and hit_hypo:
            amb = True
        if hit_sl:
            r = (dyn_sl - entry) / risk if buy else (entry - dyn_sl) / risk
            kind = "sl"
            if armed and abs(dyn_sl - orig_sl) > 1e-12:
                kind = {"peak_retrace": "retrace", "mfe_oneshot": "lock", "swing": "swing", "hybrid": "hybrid"}.get(
                    mode, "protect"
                )
            return {"ok": True, "r": float(r), "armed": armed, "exit": kind, "ambiguous": amb, "bar": j}
        if hit_tp:
            r = (tp - entry) / risk if buy else (entry - tp) / risk
            return {"ok": True, "r": float(r), "armed": armed, "exit": "tp", "ambiguous": amb, "bar": j}
        mfe = hypo_mfe
        if mfe >= MEANINGFUL_MFE_R:
            armed = True
            if mode == "mfe_oneshot" and lock_r is None:
                lock_r = STRUCTURAL_FRACTION * mfe
        if armed and mode in {"swing", "hybrid"} and j >= entry_idx + 3:
            mid = j - 1
            left = j - 2
            if buy:
                if float(lows[mid]) < float(lows[left]) and float(lows[mid]) < float(lows[j]):
                    sw = float(lows[mid])
                    if sw > entry:
                        swing_sl = sw if swing_sl is None else max(swing_sl, sw)
            else:
                if float(highs[mid]) > float(highs[left]) and float(highs[mid]) > float(highs[j]):
                    sw = float(highs[mid])
                    if sw < entry:
                        swing_sl = sw if swing_sl is None else min(swing_sl, sw)
        pending_sl = orig_sl
        if armed:
            if mode == "peak_retrace":
                fr = STRUCTURAL_FRACTION * mfe
                pending_sl = entry + fr * risk if buy else entry - fr * risk
            elif mode == "mfe_oneshot" and lock_r is not None:
                pending_sl = entry + lock_r * risk if buy else entry - lock_r * risk
            elif mode == "swing":
                pending_sl = swing_sl if swing_sl is not None else orig_sl
            elif mode == "hybrid":
                fr = STRUCTURAL_FRACTION * mfe
                peak_p = entry + fr * risk if buy else entry - fr * risk
                pending_sl = peak_p
                if swing_sl is not None:
                    pending_sl = max(pending_sl, swing_sl) if buy else min(pending_sl, swing_sl)
        if buy:
            pending_sl = max(pending_sl, orig_sl)
        else:
            pending_sl = min(pending_sl, orig_sl)
    return {"ok": True, "r": None, "armed": armed, "exit": "open", "ambiguous": amb, "bar": None}


def walk_peak_retrace(df, entry_idx, side, entry, sl, tp) -> dict[str, Any]:
    return walk_protection(df, entry_idx, side, entry, sl, tp, "peak_retrace")


def walk_mfe_fraction_oneshot(df, entry_idx, side, entry, sl, tp) -> dict[str, Any]:
    return walk_protection(df, entry_idx, side, entry, sl, tp, "mfe_oneshot")


def walk_swing(df, entry_idx, side, entry, sl, tp) -> dict[str, Any]:
    return walk_protection(df, entry_idx, side, entry, sl, tp, "swing")


def walk_hybrid_peak_swing(df, entry_idx, side, entry, sl, tp) -> dict[str, Any]:
    return walk_protection(df, entry_idx, side, entry, sl, tp, "hybrid")


def _run_family(df: pd.DataFrame, events: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    out = []
    for e in events:
        entry, sl, tp = _f(e.get("entry")), _f(e.get("SL")), _f(e.get("TP"))
        idx = _entry_index(df, e)
        if entry is None or sl is None or tp is None or idx is None:
            out.append({"ok": False, "r": _f(e.get("r_result")), "armed": False, "exit": "fallback", "ambiguous": False})
            continue
        out.append(walk_protection(df, idx, str(e.get("side")), entry, sl, tp, mode))
    return out


def compact_walks(events: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for e, r in zip(events, results):
        rows.append(
            {
                "ts": e.get("timestamp"),
                "side": e.get("side"),
                "orig": e.get("r_result"),
                "cf": r.get("r"),
                "exit": r.get("exit"),
                "armed": r.get("armed"),
                "amb": r.get("ambiguous"),
                "rr": e.get("planned_rr"),
                "fold": e.get("fold"),
                "reg": e.get("regime"),
                "sess": e.get("session"),
                "year": e.get("year"),
                "hour": e.get("hour_utc"),
                "mfe": e.get("mfe_R"),
                "cls": e.get("exit_class"),
            }
        )
    return rows


def decorate_cf(summary: dict[str, Any], events: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    if summary.get("status") == "DATA_LIMITED":
        summary["destroyed_extreme_winners"] = None
        summary["giveback_rate_cf"] = None
        summary["n_ambiguous"] = 0
        return summary
    destroyed = 0
    n_ext = 0
    gb_den = 0
    gb_num_cf = 0
    gb_num_orig = 0
    for e, r in zip(events, results):
        o = _f(e.get("r_result"))
        c = r.get("r")
        if o is not None and o >= EXTREME_R:
            n_ext += 1
            if c is not None and c < EXTREME_R:
                destroyed += 1
        if e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) > 0:
            gb_den += 1
            gb_num_orig += 1
            if c is not None and c < 0:
                gb_num_cf += 1
    summary["destroyed_extreme_winners"] = destroyed
    summary["n_extreme_orig"] = n_ext
    summary["giveback_rate_orig"] = 1.0 if gb_den else None
    summary["giveback_rate_cf"] = (gb_num_cf / gb_den) if gb_den else None
    summary["n_ambiguous"] = sum(1 for x in results if x.get("ambiguous"))
    summary["win_rate_orig"] = ((summary.get("FULL") or {}).get("orig") or {}).get("WR")
    summary["win_rate_cf"] = ((summary.get("FULL") or {}).get("cf") or {}).get("WR")
    summary["predeclared"] = {"trigger_MFE_R": MEANINGFUL_MFE_R, "fraction": STRUCTURAL_FRACTION}
    return summary


def run_phase83_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p82 = _safe_load_json(root / PHASE82_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    ts_bar = {s.get("timestamp"): s.get("closed_bar_index") for s in signals}
    for e in events:
        e["closed_bar_index"] = ts_bar.get(e.get("timestamp"))
    df, _fp = load_frozen_ohlc(root)
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    cfs: dict[str, Any] = {}
    walks: dict[str, list] = {}
    if df is None:
        for name in TESTABLE_FAMILIES:
            cfs[name] = decorate_cf(
                summarize_cf(name, events, ["parquet missing"], views, "DATA_LIMITED"), events, []
            )
    else:
        for name in TESTABLE_FAMILIES:
            walks[name] = _run_family(df, events, MODE_BY_FAMILY[name])
            cfs[name] = decorate_cf(summarize_cf(name, events, walks[name], views, "OK"), events, walks[name])
    cfs["ATR_NORMALIZED_RETRACE"] = decorate_cf(
        summarize_cf(
            "ATR_NORMALIZED_RETRACE",
            events,
            [
                "INSUFFICIENT_DATA: frozen parquet has no ATR; computing ATR would add ATR_PERIOD "
                "(PARAMETER_UNRESOLVED). Forbidden."
            ],
            views,
            "DATA_LIMITED",
        ),
        events,
        [],
    )
    helpful = [n for n in TESTABLE_FAMILIES if (cfs.get(n) or {}).get("status") == "HELPFUL"]
    hybrid_ok = len(helpful) >= 2
    if hybrid_ok and df is not None:
        walks["HYBRID"] = _run_family(df, events, "hybrid")
        cfs["HYBRID"] = decorate_cf(summarize_cf("HYBRID", events, walks["HYBRID"], views, "OK"), events, walks["HYBRID"])
        cfs["HYBRID"]["justified_by"] = helpful
    else:
        cfs["HYBRID"] = decorate_cf(
            summarize_cf(
                "HYBRID",
                events,
                [f"Not created: independent HELPFUL families={helpful}. Need two causal parents."],
                views,
                "DATA_LIMITED",
            ),
            events,
            [],
        )
    compact = {k: compact_walks(events, walks[k]) for k in walks}
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "predeclared": {
            "trigger_MFE_R": MEANINGFUL_MFE_R,
            "fraction": STRUCTURAL_FRACTION,
            "source": (p82.get("taxonomy") or {}).get("A_MFE_PERCENTAGE_PROTECTION", {}).get("predeclared"),
            "stop_update": "bar_close",
            "same_bar_rule": "do_not_assume_favorable_first; mark AMBIGUOUS",
        },
        "counterfactuals": cfs,
        "walks": compact,
        "helpful_families": helpful,
        "hybrid_created": bool(hybrid_ok),
        "oos_used_for_selection": False,
        "hypotheses": [
            {
                "id": "H83-01",
                "claim": "Predeclared half-of-MFE / swing families can be classified without searching thresholds.",
                "result": {n: cfs[n].get("status") for n in cfs},
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 5,
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
            "theoretical_only": True,
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE83_JSON, "md": PHASE83_MD},
    }
    (root / PHASE83_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE83_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 83 — Structural Protection Counterfactuals",
        "",
        "THEORETICAL. Stop known at bar open; trail updates at bar close. "
        "Same-bar new-MFE vs new-floor = AMBIGUOUS (do not assume favorable first). Not optimal.",
        "",
        f"Predeclared: MFE>={MEANINGFUL_MFE_R}R then unique half {STRUCTURAL_FRACTION}. No search.",
        f"HELPFUL families (TRAIN and VAL expectancy both rise): `{helpful}`. Hybrid created=`{hybrid_ok}`.",
        "",
    ]
    for name, row in cfs.items():
        lines.append(
            f"- `{name}`: status=`{row.get('status')}` TRAIN_delta=`{(row.get('TRAIN') or {}).get('delta_expectancy')}` "
            f"VAL_delta=`{(row.get('VALIDATION') or {}).get('delta_expectancy')}` rescued=`{row.get('rescued_losers')}` "
            f"harmed_winners=`{row.get('harmed_winners')}` destroyed_extreme=`{row.get('destroyed_extreme_winners')}` "
            f"giveback_cf=`{row.get('giveback_rate_cf')}` ambiguous=`{row.get('n_ambiguous')}`"
        )
    (root / PHASE83_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase83_collection(Path("."))
    print(p["helpful_families"], p["hybrid_created"])
