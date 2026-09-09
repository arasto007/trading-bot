"""Phase 95 — predeclared protection families v2.

Rules are defined from Phase 90-94 BEFORE walks. Max 4 families. No search.
THEORETICAL. Production unchanged.
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
from tradingbot.backtest.phase75_exit_counterfactuals import MEANINGFUL_PULLBACK_R, STAGNATION_BARS, summarize_cf
from tradingbot.backtest.phase82_profit_protection_design import MEANINGFUL_MFE_R, REVERSAL_BARS, STRUCTURAL_FRACTION
from tradingbot.backtest.phase83_profit_protection_counterfactuals import compact_walks, decorate_cf
from tradingbot.backtest.phase90_profit_giveback_path_forensics import DEEP_MFE_R, PHASE90_JSON
from tradingbot.backtest.phase91_reversal_timing_forensics import PHASE91_JSON
from tradingbot.backtest.phase92_mfe_mae_conditional_forensics import PHASE92_JSON
from tradingbot.backtest.phase93_tail_preservation_forensics import PHASE93_JSON

PHASE = "95"
PHASE95_JSON = "logs/phase95_protection_family_v2.json"
PHASE95_MD = "docs/PHASE95_PROTECTION_FAMILY_V2.md"
BLOCKED = "BLOCKED"
# Production MIN_RR from Phase 69 inspection — not searched.
MIN_RR_MFE = 1.5
FAMILIES = (
    "A_MFE_STATE_MIN_RR_LOCK",
    "B_FAST_SPIKE_REVERSAL",
    "C_SUSTAINED_THEN_SWING",
    "D_DEEP_MFE_ONESHOT",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "rules",
    "counterfactuals",
    "final_gate",
    "production_safety",
    "artifacts",
)


def rules_from_evidence(p90: dict, p91: dict, p92: dict, p93: dict) -> dict[str, Any]:
    """Declare rules BEFORE walks. Justification is Phase 90-94 only."""
    return {
        "A_MFE_STATE_MIN_RR_LOCK": {
            "justification": (
                "Phase 92: after first-cross of 1.5R (strategy MIN_RR / CROSS_LEVELS), p_TP rises vs 0.5R. "
                "Phase 74 L3 at 0.5R is where naive locks were HARMFUL. Trigger is MIN_RR, not searched."
            ),
            "activation": f"closed-bar MFE>={MIN_RR_MFE}R",
            "protection_level": f"oneshot floor = {STRUCTURAL_FRACTION} * MFE at first arm (unique half)",
            "update_condition": "no trail; floor fixed at arming close; applies next bar",
            "exit_condition": "hit floor or original TP/SL",
            "information_availability": "OHLC known at bar close",
            "same_bar_ordering": "stop known at bar open; do not assume favorable first",
            "ambiguous_bar_handling": "AMBIGUOUS if new MFE and new floor would both print; do not raise intra-bar",
        },
        "B_FAST_SPIKE_REVERSAL": {
            "justification": (
                f"Phase 91: FAST_SPIKE concentrated in losers vs winners. Restricts Phase 75 E "
                f"(NEUTRAL on all 0.5R trades) to first 0.5R within {REVERSAL_BARS} bars. Not a new timeout."
            ),
            "activation": f"first MFE>={MEANINGFUL_MFE_R}R occurs within {REVERSAL_BARS} bars of entry",
            "protection_level": "no floor move; time-reversal exit at close",
            "update_condition": f"after arm, {STAGNATION_BARS} bars without new MFE",
            "exit_condition": f"pullback>={MEANINGFUL_PULLBACK_R}R from MFE at close, else original SL/TP",
            "information_availability": "bars since entry and running MFE at close",
            "same_bar_ordering": "SL-before-TP; time exit only if neither SL nor TP",
            "ambiguous_bar_handling": "time exit uses close, not intra-bar order",
        },
        "C_SUSTAINED_THEN_SWING": {
            "justification": (
                "Phase 91: winners are mostly SUSTAINED_FAVORABLE; Phase 90 outlier is TREND_EXTENSION. "
                "Do not arm swing on spikes. Enable confirmed in-trade swing only after "
                f"{REVERSAL_BARS} closed bars with excursion>={MEANINGFUL_MFE_R}R."
            ),
            "activation": f"count of closed bars with fav>={MEANINGFUL_MFE_R}R reaches {REVERSAL_BARS}",
            "protection_level": "BUY below confirmed swing low in profit; SELL above confirmed swing high in profit",
            "update_condition": "ratchet only; 1 closed bar each side of pivot; applies next bar",
            "exit_condition": "hit swing floor or original TP/SL",
            "information_availability": "already-closed OHLC only; no persisted jsonl swings",
            "same_bar_ordering": "stop known at bar open",
            "ambiguous_bar_handling": "pivot confirmation uses the just-closed bar; stop next bar",
        },
        "D_DEEP_MFE_ONESHOT": {
            "justification": (
                f"Phase 90 class D is LOSS after MFE>={DEEP_MFE_R} (L5). Phase 80: outlier retraced after +1R, "
                "so late arming is the only predeclared way to possibly preserve F while touching D."
            ),
            "activation": f"closed-bar MFE>={DEEP_MFE_R}R (Phase 74 L5)",
            "protection_level": f"oneshot floor = {STRUCTURAL_FRACTION} * MFE at first arm",
            "update_condition": "no trail; applies next bar",
            "exit_condition": "hit floor or original TP/SL",
            "information_availability": "OHLC at close",
            "same_bar_ordering": "stop known at bar open; do not assume favorable first",
            "ambiguous_bar_handling": "AMBIGUOUS if new MFE and new floor would both print",
        },
    }


def _empty(reason: str) -> dict[str, Any]:
    return {"ok": False, "r": None, "armed": False, "exit": reason, "ambiguous": False, "bar": None}


def walk_oneshot_trigger(
    df: pd.DataFrame, entry_idx: int, side: str, entry: float, sl: float, tp: float, trigger_r: float
) -> dict[str, Any]:
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return _empty("invalid")
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    mfe = 0.0
    armed = False
    lock_r = None
    pending = float(sl)
    orig = float(sl)
    amb = False
    for j in range(entry_idx + 1, len(df)):
        dyn = pending
        high, low = float(highs[j]), float(lows[j])
        if buy:
            hit_sl, hit_tp, fav = low <= dyn, high >= tp, (high - entry) / risk
        else:
            hit_sl, hit_tp, fav = high >= dyn, low <= tp, (entry - low) / risk
        grew = fav > mfe + 1e-12
        hypo = max(mfe, fav)
        if (armed or hypo >= trigger_r) and lock_r is None and hypo >= trigger_r:
            hypo_lock = STRUCTURAL_FRACTION * hypo
            hypo_floor = entry + hypo_lock * risk if buy else entry - hypo_lock * risk
            hit_hypo = (low <= hypo_floor) if buy else (high >= hypo_floor)
            if grew and hit_hypo:
                amb = True
        if hit_sl:
            r = (dyn - entry) / risk if buy else (entry - dyn) / risk
            return {"ok": True, "r": float(r), "armed": armed, "exit": "lock" if armed else "sl", "ambiguous": amb, "bar": j}
        if hit_tp:
            r = (tp - entry) / risk if buy else (entry - tp) / risk
            return {"ok": True, "r": float(r), "armed": armed, "exit": "tp", "ambiguous": amb, "bar": j}
        mfe = hypo
        if (not armed) and mfe >= trigger_r:
            armed = True
            lock_r = STRUCTURAL_FRACTION * mfe
        pending = orig
        if armed and lock_r is not None:
            pending = entry + lock_r * risk if buy else entry - lock_r * risk
            pending = max(pending, orig) if buy else min(pending, orig)
    return {"ok": True, "r": None, "armed": armed, "exit": "open", "ambiguous": amb, "bar": None}


def walk_spike_rev(df, entry_idx, side, entry, sl, tp) -> dict[str, Any]:
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return _empty("invalid")
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    mfe = 0.0
    spike_ok = False
    seen = False
    bars_since = 0
    for j in range(entry_idx + 1, len(df)):
        high, low, close = float(highs[j]), float(lows[j]), float(closes[j])
        if buy:
            fav, cur, hit_sl, hit_tp = (high - entry) / risk, (close - entry) / risk, low <= sl, high >= tp
        else:
            fav, cur, hit_sl, hit_tp = (entry - low) / risk, (entry - close) / risk, high >= sl, low <= tp
        new_mfe = fav > mfe + 1e-12
        if new_mfe:
            mfe = fav
            bars_since = 0
        else:
            bars_since += 1
        if (not seen) and mfe >= MEANINGFUL_MFE_R:
            seen = True
            spike_ok = (j - entry_idx) <= REVERSAL_BARS
        if hit_sl:
            return {"ok": True, "r": -1.0, "armed": spike_ok, "exit": "sl", "ambiguous": False, "bar": j}
        if hit_tp:
            r = (tp - entry) / risk if buy else (entry - tp) / risk
            return {"ok": True, "r": float(r), "armed": spike_ok, "exit": "tp", "ambiguous": False, "bar": j}
        if spike_ok and bars_since >= STAGNATION_BARS and (mfe - cur) >= MEANINGFUL_PULLBACK_R:
            return {"ok": True, "r": float(cur), "armed": True, "exit": "time", "ambiguous": False, "bar": j}
    return {"ok": True, "r": None, "armed": spike_ok, "exit": "open", "ambiguous": False, "bar": None}


def walk_sustained_swing(df, entry_idx, side, entry, sl, tp) -> dict[str, Any]:
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return _empty("invalid")
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    orig = float(sl)
    pending = orig
    swing_sl = None
    armed = False
    n_sust = 0
    for j in range(entry_idx + 1, len(df)):
        dyn = pending
        high, low = float(highs[j]), float(lows[j])
        if buy:
            hit_sl, hit_tp, fav = low <= dyn, high >= tp, (high - entry) / risk
        else:
            hit_sl, hit_tp, fav = high >= dyn, low <= tp, (entry - low) / risk
        if hit_sl:
            r = (dyn - entry) / risk if buy else (entry - dyn) / risk
            return {"ok": True, "r": float(r), "armed": armed, "exit": "swing" if armed else "sl", "ambiguous": False, "bar": j}
        if hit_tp:
            r = (tp - entry) / risk if buy else (entry - tp) / risk
            return {"ok": True, "r": float(r), "armed": armed, "exit": "tp", "ambiguous": False, "bar": j}
        if fav >= MEANINGFUL_MFE_R:
            n_sust += 1
        if n_sust >= REVERSAL_BARS:
            armed = True
        if armed and j >= entry_idx + 3:
            mid, left = j - 1, j - 2
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
        pending = orig
        if armed and swing_sl is not None:
            pending = max(swing_sl, orig) if buy else min(swing_sl, orig)
    return {"ok": True, "r": None, "armed": armed, "exit": "open", "ambiguous": False, "bar": None}


WALKERS = {
    "A_MFE_STATE_MIN_RR_LOCK": lambda df, i, s, e, sl, tp: walk_oneshot_trigger(df, i, s, e, sl, tp, MIN_RR_MFE),
    "B_FAST_SPIKE_REVERSAL": walk_spike_rev,
    "C_SUSTAINED_THEN_SWING": walk_sustained_swing,
    "D_DEEP_MFE_ONESHOT": lambda df, i, s, e, sl, tp: walk_oneshot_trigger(df, i, s, e, sl, tp, DEEP_MFE_R),
}


def _run(df, events, fn) -> list[dict[str, Any]]:
    out = []
    for e in events:
        entry, sl, tp = _f(e.get("entry")), _f(e.get("SL")), _f(e.get("TP"))
        idx = _entry_index(df, e)
        if entry is None or sl is None or tp is None or idx is None:
            out.append({"ok": False, "r": _f(e.get("r_result")), "armed": False, "exit": "fallback", "ambiguous": False})
            continue
        out.append(fn(df, idx, str(e.get("side")), entry, sl, tp))
    return out


def _tail_label(orig: float | None, cf: float | None) -> str:
    if orig is None or cf is None:
        return "DATA_LIMITED"
    if orig >= EXTREME_R:
        if cf >= EXTREME_R:
            return "PRESERVED"
        if cf >= 0.5 * orig and cf > 0:
            return "PARTIALLY_PRESERVED"
        return "DESTROYED"
    return "N_A"


def run_phase95_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    p91 = _safe_load_json(root / PHASE91_JSON) or {}
    p92 = _safe_load_json(root / PHASE92_JSON) or {}
    p93 = _safe_load_json(root / PHASE93_JSON) or {}
    rules = rules_from_evidence(p90, p91, p92, p93)
    events = expand74(p74.get("compact_events") or [])
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    ts_bar = {s.get("timestamp"): s.get("closed_bar_index") for s in signals}
    for e in events:
        e["closed_bar_index"] = ts_bar.get(e.get("timestamp"))
    df, _fp = load_frozen_ohlc(root)
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    top5_ts = {e.get("timestamp") for e in ranked[:5]}
    cfs: dict[str, Any] = {}
    walks: dict[str, list] = {}
    tails: dict[str, Any] = {}
    if df is None:
        for name in FAMILIES:
            cfs[name] = decorate_cf(summarize_cf(name, events, ["parquet missing"], views, "DATA_LIMITED"), events, [])
    else:
        for name in FAMILIES:
            walks[name] = _run(df, events, WALKERS[name])
            cfs[name] = decorate_cf(summarize_cf(name, events, walks[name], views, "OK"), events, walks[name])
            w_top = next((x for x, e in zip(walks[name], events) if e.get("timestamp") == top1.get("timestamp")), {})
            tails[name] = {
                "TAIL_PRESERVATION": _tail_label(_f(top1.get("r_result")), w_top.get("r")),
                "outlier_cf_R": w_top.get("r"),
                "outlier_exit": w_top.get("exit"),
                "outlier_armed": w_top.get("armed"),
                "outlier_ambiguous": w_top.get("ambiguous"),
            }
            # rescue / destruction
            pairs = []
            without1 = []
            without5 = []
            for e, w in zip(events, walks[name]):
                o, c = _f(e.get("r_result")), w.get("r")
                if o is None or c is None:
                    continue
                pairs.append((o, c))
                if e.get("timestamp") != top1.get("timestamp"):
                    without1.append((o, c))
                if e.get("timestamp") not in top5_ts:
                    without5.append((o, c))
            cfs[name]["loser_rescue_ge_0"] = sum(1 for o, c in pairs if o < 0 and c >= 0)
            cfs[name]["winner_lt_original"] = sum(1 for o, c in pairs if o > 0 and c < o)
            cfs[name]["winner_le_0"] = sum(1 for o, c in pairs if o > 0 and c <= 0)
            def dexp(ps):
                if not ps:
                    return None
                return sum(c for _, c in ps) / len(ps) - sum(o for o, _ in ps) / len(ps)
            cfs[name]["top1_sensitivity_delta"] = dexp(without1)
            cfs[name]["top5_sensitivity_delta"] = dexp(without5)
            cfs[name]["full_delta"] = dexp(pairs)
    compact = {k: compact_walks(events, walks[k]) for k in walks}
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "n_families": len(FAMILIES),
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "rules": rules,
        "rules_declared_before_walks": True,
        "counterfactuals": cfs,
        "tails": tails,
        "walks": compact,
        "helpful_families": [n for n, v in cfs.items() if v.get("status") == "HELPFUL"],
        "oos_used_for_selection": False,
        "hypotheses": [
            {
                "id": "H95-01",
                "claim": "At most four Phase90-94-justified families can be classified without searching parameters.",
                "result": {n: cfs[n].get("status") for n in cfs},
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 4,
        "diagnostics_run": list(FAMILIES),
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
        "artifacts": {"json": PHASE95_JSON, "md": PHASE95_MD},
    }
    (root / PHASE95_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE95_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 95 — Protection Families v2",
        "",
        "THEORETICAL. Rules declared from Phase 90-94 before walks. Max 4. Not searched. Not optimal.",
        "",
    ]
    for name in FAMILIES:
        row = cfs.get(name) or {}
        t = tails.get(name) or {}
        lines.append(
            f"- `{name}`: status=`{row.get('status')}` TRAIN_d=`{(row.get('TRAIN') or {}).get('delta_expectancy')}` "
            f"VAL_d=`{(row.get('VALIDATION') or {}).get('delta_expectancy')}` "
            f"tail=`{t.get('TAIL_PRESERVATION')}` outlier_cf=`{t.get('outlier_cf_R')}` "
            f"rescue>=0=`{row.get('loser_rescue_ge_0')}` winners_cut=`{row.get('winner_lt_original')}`"
        )
    (root / PHASE95_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase95_collection(Path("."))
    print(p["helpful_families"], {k: v.get("TAIL_PRESERVATION") for k, v in p["tails"].items()})
