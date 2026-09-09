"""Phase 98 — causal state at first favorable-excursion levels.

RESEARCH ONLY. Snapshots use only bars up to first reach of a predeclared R level.
Do not assume favorable-before-adverse on the same bar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    MIN_BIN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _parse_ts,
    _utc_now,
    load_setups,
)
from tradingbot.backtest.phase68_exit_forensics import (
    BAR_MINUTES,
    TAPE_END_FALLBACK,
    _entry_index,
    load_frozen_ohlc,
    split_views,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase75_exit_counterfactuals import MEANINGFUL_PULLBACK_R
from tradingbot.backtest.phase82_profit_protection_design import MEANINGFUL_MFE_R, REVERSAL_BARS, STRUCTURAL_FRACTION
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON, prepare_events

PHASE = "98"
PHASE98_JSON = "logs/phase98_first_favorable_state.json"
PHASE98_MD = "docs/PHASE98_FIRST_FAVORABLE_STATE.md"
BLOCKED = "BLOCKED"
# Predeclared from Phase 74 CROSS_LEVELS / user A-E. Not searched.
STATE_LEVELS = (0.25, 0.50, 1.00, 1.50, 2.00)
# Velocity cut = 0.5R in 5 bars (L3 / reversal anatomy). Not searched.
VEL_CUT = MEANINGFUL_MFE_R / float(REVERSAL_BARS)
CD = ("C", "D")
EF = ("E", "F")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_level",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _snap(
    *,
    j: int,
    entry_idx: int,
    mfe: float,
    mae: float,
    close_r: float,
    fav: float,
    n_fav: int,
    n_adv: int,
    cons_fav: int,
    cons_adv: int,
    cons_fav_ext: int,
    range_ratio: float | None,
    wick_only: bool,
    close_fav: bool,
    side: str,
    ambiguous: bool,
) -> dict[str, Any]:
    bars = j - entry_idx
    return {
        "bar": j,
        "bars_elapsed": bars,
        "minutes": float(bars) * BAR_MINUTES,
        "mfe": round(mfe, 6),
        "mae": round(mae, 6),
        "close_R": round(close_r, 6),
        "extreme_R": round(fav, 6),
        "dist_entry_R": round(close_r, 6),
        "dist_sl_R": round(1.0 - mae, 6),
        "velocity_R_per_bar": None if bars <= 0 else round(mfe / float(bars), 6),
        "fav_per_bar": None if bars <= 0 else round(mfe / float(bars), 6),
        "n_fav_bars": n_fav,
        "n_adv_bars": n_adv,
        "cons_fav_close": cons_fav,
        "cons_adv_close": cons_adv,
        "cons_fav_extreme": cons_fav_ext,
        "wick_only": wick_only,
        "close_favorable": close_fav,
        "close_to_extreme": None if mfe <= 0 else round(close_r / mfe, 6),
        "range_ratio": None if range_ratio is None else round(range_ratio, 6),
        "fast": bars <= REVERSAL_BARS,
        "vel_ge_cut": (mfe / float(bars) >= VEL_CUT) if bars > 0 else False,
        "mae_lt_meaningful": mae < 0.25,
        "close_confirms_level": False,
        "ambiguous": ambiguous,
        "side": side,
    }


def walk_anatomy(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """Causal walk. SL-before-TP. Same-bar fav+SL = do not credit the level."""
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    empty = {
        "ok": False,
        "states": {str(lv): None for lv in STATE_LEVELS},
        "first_fav_bar": None,
        "first_adv_bar": None,
        "fav_before_adv": None,
        "same_bar_fav_adv": False,
        "retrace": None,
        "outcome": None,
        "exit_bar": None,
    }
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return empty
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    mfe = 0.0
    mae = 0.0
    n_fav = n_adv = 0
    cons_fav = cons_adv = cons_fav_ext = 0
    first_fav = first_adv = None
    same_both = False
    states: dict[str, Any] = {str(lv): None for lv in STATE_LEVELS}
    retrace = None
    armed_half = False
    exit_j = None
    outcome = "open"
    prev_range = None
    for j in range(entry_idx + 1, len(df)):
        high, low, opn, close = float(highs[j]), float(lows[j]), float(opens[j]), float(closes[j])
        brange = high - low
        if buy:
            fav = (high - entry) / risk
            adv = (entry - low) / risk
            close_r = (close - entry) / risk
            hit_sl = low <= sl
            hit_tp = high >= tp
            close_fav = close > entry
        else:
            fav = (entry - low) / risk
            adv = (high - entry) / risk
            close_r = (entry - close) / risk
            hit_sl = high >= sl
            hit_tp = low <= tp
            close_fav = close < entry
        ratio = None if (prev_range is None or prev_range <= 0) else brange / prev_range
        prev_range = brange if brange > 0 else prev_range
        grew = fav > mfe + 1e-12
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        if fav > 0:
            n_fav += 1
            cons_fav_ext += 1
        else:
            cons_fav_ext = 0
        if adv > 0:
            n_adv += 1
        if close_fav:
            cons_fav += 1
            cons_adv = 0
        else:
            cons_adv += 1
            cons_fav = 0
        if first_fav is None and fav > 0:
            first_fav = j
        if first_adv is None and adv > 0:
            first_adv = j
        if first_fav == j and first_adv == j:
            same_both = True
        if mfe >= MEANINGFUL_MFE_R:
            armed_half = True
        # Same-bar SL + new level: do not assume fav first.
        amb = bool(hit_sl and grew)
        if not hit_sl:
            for lv in STATE_LEVELS:
                key = str(lv)
                if states[key] is None and fav >= lv:
                    snap = _snap(
                        j=j,
                        entry_idx=entry_idx,
                        mfe=mfe,
                        mae=mae,
                        close_r=close_r,
                        fav=fav,
                        n_fav=n_fav,
                        n_adv=n_adv,
                        cons_fav=cons_fav,
                        cons_adv=cons_adv,
                        cons_fav_ext=cons_fav_ext,
                        range_ratio=ratio,
                        wick_only=bool(fav >= lv and close_r < lv),
                        close_fav=close_fav,
                        side=str(side).upper(),
                        ambiguous=amb,
                    )
                    snap["close_confirms_level"] = close_r >= lv
                    snap["level"] = lv
                    states[key] = snap
        if armed_half and retrace is None and (mfe - (close_r if close_r < mfe else fav)) >= MEANINGFUL_PULLBACK_R:
            # Pullback from MFE using adverse extreme this bar, not assuming close.
            cur_adv_from_peak = mfe - ((low - entry) / risk if buy else (entry - high) / risk)
            if cur_adv_from_peak >= MEANINGFUL_PULLBACK_R:
                retrace = {
                    "bar": j,
                    "bars_elapsed": j - entry_idx,
                    "mfe_at_retrace": round(mfe, 6),
                    "mae_at_retrace": round(mae, 6),
                    "close_R": round(close_r, 6),
                    "pullback_R": round(cur_adv_from_peak, 6),
                    "wick_reject": bool(
                        brange > 0
                        and (
                            ((high - close) / brange >= STRUCTURAL_FRACTION)
                            if buy
                            else ((close - low) / brange >= STRUCTURAL_FRACTION)
                        )
                    ),
                    "close_against": not close_fav,
                    "range_ratio": None if ratio is None else round(ratio, 6),
                    "range_expand": bool(ratio is not None and ratio > 1.0),
                    "cons_adv_close": cons_adv,
                    "failed_new_extreme": not grew,
                    "open": opn,
                    "high": high,
                    "low": low,
                    "close": close,
                    "ambiguous": amb,
                }
        if hit_sl:
            outcome = "loss"
            exit_j = j
            break
        if hit_tp:
            outcome = "win"
            exit_j = j
            break
    fav_before = None
    if first_fav is not None and first_adv is not None:
        if same_both:
            fav_before = "AMBIGUOUS"
        else:
            fav_before = bool(first_fav < first_adv)
    elif first_fav is not None:
        fav_before = True
    elif first_adv is not None:
        fav_before = False
    return {
        "ok": True,
        "states": states,
        "first_fav_bar": first_fav,
        "first_adv_bar": first_adv,
        "fav_before_adv": fav_before,
        "same_bar_fav_adv": same_both,
        "retrace": retrace,
        "outcome": outcome,
        "exit_bar": exit_j,
        "mfe": mfe,
        "mae": mae,
    }


def _group_rows(compact: list[dict[str, Any]], classes: tuple[str, ...]) -> list[dict[str, Any]]:
    return [r for r in compact if r.get("path_class") in classes]


def _rate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    xs = [bool(r.get(key)) for r in rows if r.get(key) is not None]
    if len(xs) < MIN_BIN:
        return {"n": len(xs), "rate": None, "small_n": True}
    return {"n": len(xs), "rate": sum(xs) / len(xs), "small_n": False}


def _cont(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    xs = [_f(r.get(key)) for r in rows]
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "median": _median(xs), "mean": _mean(xs), "small_n": len(xs) < MIN_BIN}


def majority_sep(cd_rate: float | None, ef_rate: float | None) -> str:
    if cd_rate is None or ef_rate is None:
        return "DATA_LIMITED"
    if (cd_rate >= STRUCTURAL_FRACTION and ef_rate < STRUCTURAL_FRACTION) or (
        ef_rate >= STRUCTURAL_FRACTION and cd_rate < STRUCTURAL_FRACTION
    ):
        return "DIRECTIONAL"
    return "OVERLAP"


def confirmed_sep(
    cd_tr: float | None,
    ef_tr: float | None,
    cd_va: float | None,
    ef_va: float | None,
) -> bool:
    """TRAIN and VAL both majority-directional, same which group is higher."""
    if majority_sep(cd_tr, ef_tr) != "DIRECTIONAL":
        return False
    if majority_sep(cd_va, ef_va) != "DIRECTIONAL":
        return False
    if None in (cd_tr, ef_tr, cd_va, ef_va):
        return False
    return (float(cd_tr) >= float(ef_tr)) == (float(cd_va) >= float(ef_va))


def run_phase98_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    events = prepare_events(root, expand74(p74.get("compact_events") or []))
    by_ts_class = {r.get("ts"): r.get("path_class") for r in (p90.get("compact") or [])}
    df, _fp = load_frozen_ohlc(root)
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    compact: list[dict[str, Any]] = []
    n_amb = 0
    if df is not None:
        for e in events:
            entry, sl, tp = _f(e.get("entry")), _f(e.get("SL")), _f(e.get("TP"))
            idx = _entry_index(df, e)
            klass = by_ts_class.get(e.get("timestamp")) or UNKNOWN
            row = {
                "ts": e.get("timestamp"),
                "side": e.get("side"),
                "path_class": klass,
                "fold": e.get("fold"),
                "year": e.get("year"),
                "reg": e.get("regime"),
                "n_sig": e.get("signal_count"),
                "orig": e.get("r_result"),
                "states": {},
                "anatomy": None,
            }
            if entry is None or sl is None or tp is None or idx is None:
                compact.append(row)
                continue
            anat = walk_anatomy(df, idx, str(e.get("side")), entry, sl, tp)
            row["anatomy"] = {
                "fav_before_adv": anat.get("fav_before_adv"),
                "same_bar_fav_adv": anat.get("same_bar_fav_adv"),
                "retrace": anat.get("retrace"),
                "first_fav_bar": anat.get("first_fav_bar"),
                "first_adv_bar": anat.get("first_adv_bar"),
                "ok": anat.get("ok"),
            }
            row["states"] = anat.get("states") or {}
            if anat.get("same_bar_fav_adv") or any((s or {}).get("ambiguous") for s in (anat.get("states") or {}).values()):
                n_amb += 1
            compact.append(row)
    by_level = {}
    separators: list[dict[str, Any]] = []
    for lv in STATE_LEVELS:
        key = str(lv)

        def at_level(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for r in rows:
                s = (r.get("states") or {}).get(key)
                if not s:
                    continue
                out.append({**s, "path_class": r.get("path_class"), "fold": r.get("fold"), "ts": r.get("ts")})
            return out

        all_s = at_level(compact)
        cd = [s for s in all_s if s.get("path_class") in CD]
        ef = [s for s in all_s if s.get("path_class") in EF]
        feats = ("fast", "wick_only", "close_confirms_level", "vel_ge_cut", "mae_lt_meaningful", "close_favorable")
        feat_rows = {}
        for feat in feats:
            cd_r = _rate(cd, feat)
            ef_r = _rate(ef, feat)
            sep = majority_sep(cd_r.get("rate"), ef_r.get("rate"))
            # TRAIN / VAL confirmation
            def fold_sep(fold: str) -> str:
                cds = [s for s in cd if s.get("fold") == fold]
                efs = [s for s in ef if s.get("fold") == fold]
                return majority_sep(_rate(cds, feat).get("rate"), _rate(efs, feat).get("rate"))

            tr, va = fold_sep("TRAIN"), fold_sep("VALIDATION")
            cd_tr = _rate([s for s in cd if s.get("fold") == "TRAIN"], feat).get("rate")
            ef_tr = _rate([s for s in ef if s.get("fold") == "TRAIN"], feat).get("rate")
            cd_va = _rate([s for s in cd if s.get("fold") == "VALIDATION"], feat).get("rate")
            ef_va = _rate([s for s in ef if s.get("fold") == "VALIDATION"], feat).get("rate")
            confirmed = confirmed_sep(cd_tr, ef_tr, cd_va, ef_va)
            feat_rows[feat] = {
                "CD": cd_r,
                "EF": ef_r,
                "FULL_sep": sep,
                "TRAIN_sep": tr,
                "VAL_sep": va,
                "TRAIN_VAL_confirmed": confirmed,
            }
            if confirmed:
                separators.append({"level": lv, "feature": feat, "kind": "BINARY_MAJORITY"})
        by_level[key] = {
            "n_reached": len(all_s),
            "n_CD": len(cd),
            "n_EF": len(ef),
            "bars_elapsed": {"CD": _cont(cd, "bars_elapsed"), "EF": _cont(ef, "bars_elapsed")},
            "velocity": {"CD": _cont(cd, "velocity_R_per_bar"), "EF": _cont(ef, "velocity_R_per_bar")},
            "mae": {"CD": _cont(cd, "mae"), "EF": _cont(ef, "mae")},
            "close_to_extreme": {"CD": _cont(cd, "close_to_extreme"), "EF": _cont(ef, "close_to_extreme")},
            "features": feat_rows,
        }
    disc = "NOT_ESTABLISHED" if not separators else "CANDIDATE_BINARY_FEATURES"
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
            "STATE_LEVELS": STATE_LEVELS,
            "VEL_CUT": VEL_CUT,
            "VEL_CUT_SOURCE": "MEANINGFUL_MFE_R / REVERSAL_BARS",
            "majority_cut": STRUCTURAL_FRACTION,
            "fast_bars": REVERSAL_BARS,
        },
        "n_events": len(compact),
        "n_ambiguous": n_amb,
        "by_level": by_level,
        "separators_train_val": separators,
        "DISCRIMINATOR_AT_FIRST_FAVORABLE": disc,
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "compact": compact,
        "hypotheses": [
            {
                "id": "H98-01",
                "claim": "A predeclared state at first +0.5R/+1.5R/+2R separates C/D from E/F on TRAIN and VAL.",
                "result": disc,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["states_A_E", "CD_vs_EF"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE98_JSON, "md": PHASE98_MD},
    }
    (root / PHASE98_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE98_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 98 — State at First Favorable Excursion",
        "",
        "FROZEN-DATA-EVIDENCE. Snapshots stop at first causal reach. Same-bar fav+SL is not credited.",
        f"**DISCRIMINATOR_AT_FIRST_FAVORABLE:** `{disc}`",
        f"TRAIN+VAL confirmed separators: `{separators}`",
        "",
    ]
    for lv, row in by_level.items():
        lines.append(
            f"- level {lv}R n=`{row['n_reached']}` CD=`{row['n_CD']}` EF=`{row['n_EF']}` "
            f"med_bars CD=`{(row['bars_elapsed']['CD'] or {}).get('median')}` "
            f"EF=`{(row['bars_elapsed']['EF'] or {}).get('median')}`"
        )
    (root / PHASE98_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase98_collection(Path("."))
    print(p["DISCRIMINATOR_AT_FIRST_FAVORABLE"], p["separators_train_val"])
