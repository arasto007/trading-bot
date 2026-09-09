"""Phase 90 — profit-giveback path-shape forensics.

RESEARCH ONLY. Reuses Phase 68 walk_path SL-before-TP. No production change.
Path classes A-G use predeclared Phase 68/74 thresholds. Not searched.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _parse_ts,
    _utc_now,
    load_setups,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import (
    BAR_MINUTES,
    EXTREME_R,
    PROFIT_EPS,
    TAPE_END_FALLBACK,
    _entry_index,
    load_frozen_ohlc,
    split_views,
    walk_path,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase75_exit_counterfactuals import MEANINGFUL_PULLBACK_R
from tradingbot.backtest.phase82_profit_protection_design import MEANINGFUL_MFE_R, REVERSAL_BARS

PHASE = "90"
PHASE90_JSON = "logs/phase90_profit_giveback_path_forensics.json"
PHASE90_MD = "docs/PHASE90_PROFIT_GIVEBACK_PATH_FORENSICS.md"
BLOCKED = "BLOCKED"
# Predeclared from Phase 74 CROSS_LEVELS (user-requested subset). Not searched.
BAR_LEVELS = (0.25, 0.50, 0.75, 1.00, 1.50, 2.00)
DEEP_MFE_R = 2.0  # Phase 74 L5
FAST_MIN = float(REVERSAL_BARS) * BAR_MINUTES  # 25 min / 5 M5 bars
PATH_CLASSES = ("A", "B", "C", "D", "E", "F", "G")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "path_classes",
    "final_gate",
    "production_safety",
    "artifacts",
)


def prepare_events(root: Path, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    ts_bar = {s.get("timestamp"): s.get("closed_bar_index") for s in signals}
    for e in events:
        e["closed_bar_index"] = ts_bar.get(e.get("timestamp"))
    return events


def walk_shape(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """Extra path anatomy on the same frozen walk as Phase 68. Conservative SL-before-TP."""
    base = walk_path(df, entry_idx, side, entry, sl, tp)
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    empty_cross = {
        str(lv): {
            "bars": 0,
            "first_bar": None,
            "revisited_entry": False,
            "higher_before_revisit": False,
            "ambiguous_revisit": False,
            "time_to_level_min": None,
            "time_level_to_mfe_min": None,
            "time_level_to_revisit_min": None,
            "time_level_to_exit_min": None,
            "max_mfe_after": None,
            "then_sl": False,
            "then_tp": False,
        }
        for lv in BAR_LEVELS
    }
    if risk <= 0 or not base.get("valid") or base.get("exit_bar") is None:
        return {**base, "cross": empty_cross, "first_rev_bar": None, "rev_mag": None, "rev_speed": None, "shape": "AMBIGUOUS"}
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    exit_j = int(base["exit_bar"])
    mfe_bar = int(base["mfe_bar"] or entry_idx)
    cross = empty_cross
    mfe = 0.0
    min_after_mfe = None
    first_rev_bar = None
    for j in range(entry_idx + 1, exit_j + 1):
        high = float(highs[j])
        low = float(lows[j])
        if buy:
            fav = (high - entry) / risk
            cur_from_adverse = (low - entry) / risk
            cur_adv_from_entry = low <= entry
        else:
            fav = (entry - low) / risk
            cur_from_adverse = (entry - high) / risk
            cur_adv_from_entry = high >= entry
        grew = fav > mfe + 1e-12
        mfe = max(mfe, fav)
        if j >= mfe_bar:
            min_after_mfe = cur_from_adverse if min_after_mfe is None else min(min_after_mfe, cur_from_adverse)
        if first_rev_bar is None and mfe >= MEANINGFUL_MFE_R and (mfe - cur_from_adverse) >= MEANINGFUL_PULLBACK_R:
            first_rev_bar = j
        for lv in BAR_LEVELS:
            key = str(lv)
            row = cross[key]
            if fav >= lv:
                row["bars"] += 1
                if row["first_bar"] is None:
                    row["first_bar"] = j
                    row["time_to_level_min"] = float(j - entry_idx) * BAR_MINUTES
                    row["max_mfe_after"] = mfe
            if row["first_bar"] is not None:
                row["max_mfe_after"] = max(row["max_mfe_after"] or mfe, mfe)
                nxt = next((x for x in BAR_LEVELS if x > lv), None)
                if nxt is not None and mfe >= nxt and not row["revisited_entry"]:
                    row["higher_before_revisit"] = True
                if cur_adv_from_entry and not row["revisited_entry"]:
                    if grew:
                        row["ambiguous_revisit"] = True
                    row["revisited_entry"] = True
                    row["time_level_to_revisit_min"] = float(j - int(row["first_bar"])) * BAR_MINUTES
    for lv in BAR_LEVELS:
        row = cross[str(lv)]
        if row["first_bar"] is not None:
            row["time_level_to_mfe_min"] = float(mfe_bar - int(row["first_bar"])) * BAR_MINUTES
            row["time_level_to_exit_min"] = float(exit_j - int(row["first_bar"])) * BAR_MINUTES
            row["then_sl"] = base.get("outcome_walk") == "loss"
            row["then_tp"] = base.get("outcome_walk") == "win"
    rev_mag = None if min_after_mfe is None else float(mfe - min_after_mfe)
    bars_rev = max(1, exit_j - mfe_bar)
    rev_speed = None if rev_mag is None else float(rev_mag) / float(bars_rev)
    t_mfe = _f(base.get("time_to_mfe_min"))
    t_rev = _f(base.get("mins_mfe_to_exit"))
    revisited_half = bool((cross[str(MEANINGFUL_MFE_R)] or {}).get("revisited_entry"))
    if base.get("same_bar_sl_tp"):
        shape = "AMBIGUOUS"
    elif t_mfe is not None and t_rev is not None and t_mfe <= FAST_MIN and t_rev <= FAST_MIN and mfe >= MEANINGFUL_MFE_R:
        shape = "SPIKE_AND_REVERT"
    elif base.get("outcome_walk") == "win" and mfe >= DEEP_MFE_R:
        shape = "TREND_EXTENSION"
    elif base.get("outcome_walk") == "win" and not revisited_half:
        shape = "MONOTONIC"
    elif revisited_half:
        shape = "WHIPSAW"
    elif (cross[str(MEANINGFUL_MFE_R)]["bars"] >= REVERSAL_BARS) and (cross["1.0"]["bars"] >= 1):
        shape = "STAIR_STEP"
    elif mfe < MEANINGFUL_MFE_R:
        shape = "BRIEF"
    else:
        shape = "OTHER"
    return {
        **base,
        "cross": cross,
        "first_rev_bar": first_rev_bar,
        "mfe_before_first_rev": None if first_rev_bar is None else mfe,
        "rev_mag": None if rev_mag is None else round(rev_mag, 6),
        "rev_speed": None if rev_speed is None else round(rev_speed, 6),
        "shape": shape,
    }


def path_class(event: dict[str, Any], shape_row: dict[str, Any]) -> str:
    if not shape_row.get("valid"):
        return "G"
    mfe = _f(event.get("mfe_R"))
    if mfe is None:
        mfe = _f(shape_row.get("mfe_walk"))
    r = _f(event.get("r_result"))
    exit_class = event.get("exit_class")
    if r is not None and r >= EXTREME_R:
        return "F"
    if mfe is None:
        return "G"
    if mfe <= PROFIT_EPS:
        return "A"
    if exit_class == "LOSS_SL":
        if mfe < MEANINGFUL_MFE_R:
            return "B"
        if mfe < DEEP_MFE_R:
            return "C"
        return "D"
    if exit_class == "WIN_TP":
        return "E"
    return "G"


def compact_row(event: dict[str, Any], shape_row: dict[str, Any], klass: str) -> dict[str, Any]:
    return {
        "ts": event.get("timestamp"),
        "side": event.get("side"),
        "orig": event.get("r_result"),
        "mfe": event.get("mfe_R"),
        "mae": event.get("mae_R"),
        "t_mfe": event.get("time_to_mfe_min"),
        "t_rev": event.get("mins_mfe_to_exit"),
        "hold": event.get("duration_minutes"),
        "cls": event.get("exit_class"),
        "fold": event.get("fold"),
        "year": event.get("year"),
        "reg": event.get("regime"),
        "sess": event.get("session"),
        "rr": event.get("planned_rr"),
        "n_sig": event.get("signal_count"),
        "path_class": klass,
        "shape": shape_row.get("shape"),
        "cross": shape_row.get("cross"),
        "rev_mag": shape_row.get("rev_mag"),
        "rev_speed": shape_row.get("rev_speed"),
        "same_bar": shape_row.get("same_bar_sl_tp"),
        "valid": shape_row.get("valid"),
        "mfe_walk": shape_row.get("mfe_walk"),
        "mae_walk": shape_row.get("mae_walk"),
        "bars_above": {k: (v or {}).get("bars") for k, v in (shape_row.get("cross") or {}).items()},
    }


def class_pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [_f(r.get("orig")) for r in rows]
    xs = [x for x in xs if x is not None]
    mfes = [_f(r.get("mfe")) for r in rows]
    t_rev = [_f(r.get("t_rev")) for r in rows]
    n = len(rows)
    return {
        "n": n,
        "pct": None,
        **pack_stats(xs),
        "median_MFE": _median([x for x in mfes if x is not None]),
        "median_reversal_min": _median([x for x in t_rev if x is not None]),
        "sum_R": float(sum(xs)) if xs else 0.0,
        "n_LOSS": sum(1 for r in rows if r.get("cls") == "LOSS_SL"),
        "n_WIN": sum(1 for r in rows if r.get("cls") == "WIN_TP"),
        "shapes": dict(Counter(str(r.get("shape")) for r in rows)),
    }


def run_phase90_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    events = prepare_events(root, expand74(p74.get("compact_events") or []))
    df, _fp = load_frozen_ohlc(root)
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    compact: list[dict[str, Any]] = []
    n_amb = 0
    if df is None:
        for e in events:
            compact.append(compact_row(e, {"valid": False, "shape": "AMBIGUOUS"}, "G"))
    else:
        for e in events:
            entry, sl, tp = _f(e.get("entry")), _f(e.get("SL")), _f(e.get("TP"))
            idx = _entry_index(df, e)
            if entry is None or sl is None or tp is None or idx is None:
                row = compact_row(e, {"valid": False, "shape": "AMBIGUOUS"}, "G")
            else:
                shp = walk_shape(df, idx, str(e.get("side")), entry, sl, tp)
                klass = path_class(e, shp)
                row = compact_row(e, shp, klass)
                if shp.get("same_bar_sl_tp") or any(
                    (v or {}).get("ambiguous_revisit") for v in (shp.get("cross") or {}).values()
                ):
                    n_amb += 1
            compact.append(row)
    by_ts = {r["ts"]: r for r in compact}
    classes = {}
    n_all = len(compact) or 1
    for name in PATH_CLASSES:
        rows = [r for r in compact if r.get("path_class") == name]
        pack = class_pack(rows)
        pack["pct"] = len(rows) / n_all
        classes[name] = pack

    def view_classes(rows: list[dict[str, Any]]) -> dict[str, Any]:
        mapped = [by_ts[e["timestamp"]] for e in rows if e.get("timestamp") in by_ts]
        out = {}
        for name in PATH_CLASSES:
            hit = [r for r in mapped if r.get("path_class") == name]
            out[name] = {"n": len(hit), "exp": _mean([_f(x.get("orig")) for x in hit if _f(x.get("orig")) is not None])}
        return out

    view_break = {k: view_classes(v) for k, v in views.items()}
    recoverable = ["C", "D"]
    winner_classes = ["E", "F"]
    n_rec_loss = sum(classes[c]["n_LOSS"] for c in recoverable)
    n_win = sum(classes[c]["n_WIN"] for c in winner_classes)
    outlier = max(compact, key=lambda r: float(r.get("orig") or -1e9), default={})
    # Signature: recoverable losers (C/D) vs winners (E/F) — compare median MFE hold vs reversal time.
    rec_rows = [r for r in compact if r.get("path_class") in recoverable]
    win_rows = [r for r in compact if r.get("path_class") in winner_classes]
    rec_t = _median([_f(r.get("t_rev")) for r in rec_rows if _f(r.get("t_rev")) is not None])
    win_t = _median([_f(r.get("t_rev")) for r in win_rows if _f(r.get("t_rev")) is not None])
    rec_mfe = _median([_f(r.get("mfe")) for r in rec_rows if _f(r.get("mfe")) is not None])
    win_mfe = _median([_f(r.get("mfe")) for r in win_rows if _f(r.get("mfe")) is not None])
    # Overlap of MFE: if winner median MFE is inside loser C/D range, no clean separator.
    signature = "NOT_ESTABLISHED"
    if rec_rows and win_rows and rec_mfe is not None and win_mfe is not None:
        if win_mfe > DEEP_MFE_R and rec_mfe < DEEP_MFE_R:
            signature = "PARTIAL_MFE_SEPARATION"
        else:
            signature = "OVERLAP_MFE_NOT_A_CLEAN_SEPARATOR"
    q = {
        "1_majority_recoverable_losses": "C_AND_D" if n_rec_loss >= 0.5 * sum(classes[c]["n_LOSS"] for c in PATH_CLASSES) else "MIXED",
        "2_legitimate_winners": "E_AND_F",
        "3_common_signature_losers_vs_winners": signature,
        "4_outlier_class": outlier.get("path_class"),
        "5_path_classification_vs_trailing_distance": (
            "PATH_CLASS_NEEDED_BUT_SEPARATOR_NOT_ESTABLISHED"
            if signature == "OVERLAP_MFE_NOT_A_CLEAN_SEPARATOR"
            else (
                "PATH_CLASSIFICATION_PROBLEM"
                if signature == "PARTIAL_MFE_SEPARATION"
                else "INSUFFICIENT_TO_PREFER_PATH_OVER_DISTANCE"
            )
        ),
    }
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
            "BAR_LEVELS": BAR_LEVELS,
            "source": "Phase74 CROSS_LEVELS",
            "A_immediate": f"MFE<=PROFIT_EPS ({PROFIT_EPS})",
            "B_brief": f"LOSS and PROFIT_EPS<MFE<{MEANINGFUL_MFE_R}",
            "C_moderate_giveback": f"LOSS and {MEANINGFUL_MFE_R}<=MFE<{DEEP_MFE_R}",
            "D_deep_giveback": f"LOSS and MFE>={DEEP_MFE_R} (L5)",
            "E_sustained_win": "WIN_TP and realized_R<10",
            "F_extreme": f"realized_R>={EXTREME_R}",
            "G_ambiguous": "invalid path / other exit",
            "FAST_MIN": FAST_MIN,
            "REVERSAL_BARS": REVERSAL_BARS,
            "MEANINGFUL_PULLBACK_R": MEANINGFUL_PULLBACK_R,
        },
        "n_events": len(compact),
        "n_ambiguous_path_ordering": n_amb,
        "path_classes": classes,
        "views": view_break,
        "outlier": {
            "timestamp": outlier.get("ts"),
            "path_class": outlier.get("path_class"),
            "shape": outlier.get("shape"),
            "orig": outlier.get("orig"),
            "mfe": outlier.get("mfe"),
        },
        "recoverable_loss_n": n_rec_loss,
        "winner_n": n_win,
        "median_reversal_min_recoverable_losers": rec_t,
        "median_reversal_min_winners": win_t,
        "median_MFE_recoverable_losers": rec_mfe,
        "median_MFE_winners": win_mfe,
        "questions": q,
        "compact": compact,
        "hypotheses": [
            {
                "id": "H90-01",
                "claim": "Predeclared A-G path classes can locate recoverable giveback vs legitimate tails without searching thresholds.",
                "result": q,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["path_class_A_G", "shape", "bars_above_levels"],
        "oos_used_for_selection": False,
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
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE90_JSON, "md": PHASE90_MD},
    }
    (root / PHASE90_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE90_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 90 — Profit Giveback Path Forensics",
        "",
        "RESEARCH ONLY. Path classes A-G use Phase 68/74 predeclared thresholds. Not searched. Not optimal.",
        "",
        f"Ambiguous path-ordering events: `{n_amb}`.",
        f"Outlier class: `{outlier.get('path_class')}` shape=`{outlier.get('shape')}` R=`{outlier.get('orig')}`.",
        f"Signature losers vs winners: `{signature}`.",
        "",
    ]
    for name in PATH_CLASSES:
        row = classes[name]
        lines.append(
            f"- `{name}`: n=`{row['n']}` pct=`{row['pct']}` exp=`{row.get('expectancy_R')}` "
            f"sum_R=`{row.get('sum_R')}` LOSS=`{row.get('n_LOSS')}` WIN=`{row.get('n_WIN')}`"
        )
    (root / PHASE90_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase90_collection(Path("."))
    print({k: v.get("n") for k, v in p["path_classes"].items()}, p["questions"])
