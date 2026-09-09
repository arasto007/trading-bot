"""Phase 103 — structural information available at first material retracement.

Predeclared candle/swing definitions. Causal bars only. No threshold mining.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    _git_head,
    _parse_ts,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import TAPE_END_FALLBACK, _entry_index, load_frozen_ohlc
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase82_profit_protection_design import REVERSAL_BARS, STRUCTURAL_FRACTION
from tradingbot.backtest.phase90_profit_giveback_path_forensics import prepare_events
from tradingbot.backtest.phase98_first_favorable_state import CD, EF, PHASE98_JSON, _rate, confirmed_sep, majority_sep

PHASE = "103"
PHASE103_JSON = "logs/phase103_structure_at_retracement.json"
PHASE103_MD = "docs/PHASE103_STRUCTURE_AT_RETRACEMENT.md"
BLOCKED = "BLOCKED"
# Consecutive opposite closes: minimum two closed bars. Not searched.
CONSEC_OPP_MIN = 2
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "STRUCTURAL_DISCRIMINATOR",
    "final_gate",
    "production_safety",
    "artifacts",
)
PREDECLARED_CONCEPTS = (
    "close_unfav_half",
    "rejection_wick",
    "engulfing_reversal",
    "consec_opp_closes",
    "break_fav_swing",
    "failed_new_extreme",
    "range_expand",
    "reversal_persist",
)


def _close_loc(high: float, low: float, close: float) -> float | None:
    brange = high - low
    if brange <= 0:
        return None
    return (close - low) / brange


def last_confirmed_swing(
    highs: Any,
    lows: Any,
    entry_idx: int,
    j: int,
    buy: bool,
) -> float | None:
    """Most recent 3-bar swing confirmed by one closed bar each side, at or before j."""
    lo = entry_idx + 2
    hi = j - 1
    for mid in range(hi, lo - 1, -1):
        left = mid - 1
        right = mid + 1
        if right > j or left < entry_idx + 1:
            continue
        if buy:
            if float(lows[mid]) < float(lows[left]) and float(lows[mid]) < float(lows[right]):
                return float(lows[mid])
        else:
            if float(highs[mid]) > float(highs[left]) and float(highs[mid]) > float(highs[right]):
                return float(highs[mid])
    return None


def structure_at_retrace(
    df: pd.DataFrame,
    entry_idx: int,
    j: int,
    buy: bool,
    retrace: dict[str, Any],
) -> dict[str, Any]:
    if j <= 0 or j >= len(df):
        return {k: None for k in PREDECLARED_CONCEPTS}
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    high, low, opn, close = float(highs[j]), float(lows[j]), float(opens[j]), float(closes[j])
    loc = _close_loc(high, low, close)
    brange = high - low
    close_unfav = None if loc is None else (loc < STRUCTURAL_FRACTION if buy else loc > (1.0 - STRUCTURAL_FRACTION))
    if brange <= 0:
        rejection = False
    elif buy:
        rejection = ((high - close) / brange) >= STRUCTURAL_FRACTION
    else:
        rejection = ((close - low) / brange) >= STRUCTURAL_FRACTION
    engulfing = False
    if j - 1 >= 0:
        ph, pl = float(highs[j - 1]), float(lows[j - 1])
        engulfing = high >= ph and low <= pl and ((close < opn) if buy else (close > opn))
    consec = 0
    for k in range(j, entry_idx, -1):
        ck = float(closes[k])
        ok = float(opens[k])
        against = (ck < ok) if buy else (ck > ok)
        if against:
            consec += 1
        else:
            break
    swing = last_confirmed_swing(highs, lows, entry_idx, j, buy)
    if swing is None:
        broke = False
    else:
        broke = (close < swing) if buy else (close > swing)
    return {
        "close_unfav_half": close_unfav,
        "rejection_wick": bool(rejection),
        "engulfing_reversal": bool(engulfing),
        "consec_opp_closes": consec >= CONSEC_OPP_MIN,
        "break_fav_swing": bool(broke),
        "failed_new_extreme": bool(retrace.get("failed_new_extreme")),
        "range_expand": bool(retrace.get("range_expand")),
        "reversal_persist": consec >= REVERSAL_BARS,
        "consec_count": consec,
        "close_loc": None if loc is None else round(loc, 6),
    }


def _fold_rates(rows: list[dict[str, Any]], feat: str, fold: str, cd_flag: bool) -> float | None:
    sub = [x for x in rows if x.get("fold") == fold and (x.get("is_CD") if cd_flag else x.get("is_EF"))]
    return _rate(sub, feat).get("rate")


def run_phase103_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    events = prepare_events(root, expand74(p74.get("compact_events") or []))
    by_ts_ev = {e.get("timestamp"): e for e in events}
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    cut = tape_end - timedelta(days=180)
    df, _fp = load_frozen_ohlc(root)
    rows = []
    if df is not None:
        for r in p98.get("compact") or []:
            ret = (r.get("anatomy") or {}).get("retrace")
            if not ret:
                continue
            e = by_ts_ev.get(r.get("ts")) or {}
            idx = _entry_index(df, e) if e else None
            j = ret.get("bar")
            if idx is None or j is None:
                continue
            buy = str(r.get("side") or "").upper() in {"BUY", "1", "LONG"}
            st = structure_at_retrace(df, idx, int(j), buy, ret)
            ts = _parse_ts(r.get("ts"))
            rows.append(
                {
                    **st,
                    "ts": r.get("ts"),
                    "path_class": r.get("path_class"),
                    "fold": r.get("fold"),
                    "side": r.get("side"),
                    "reg": r.get("reg"),
                    "orig": r.get("orig"),
                    "is_CD": r.get("path_class") in CD,
                    "is_EF": r.get("path_class") in EF,
                    "recent180": bool(ts is not None and ts >= cut),
                }
            )
    cd = [x for x in rows if x.get("is_CD")]
    ef = [x for x in rows if x.get("is_EF")]
    feat_rows = {}
    separators = []
    survivors = []
    for feat in PREDECLARED_CONCEPTS:
        cd_r, ef_r = _rate(cd, feat), _rate(ef, feat)

        def split_sep(pred, f=feat) -> str:
            return majority_sep(
                _rate([x for x in cd if pred(x)], f).get("rate"),
                _rate([x for x in ef if pred(x)], f).get("rate"),
            )

        tr = split_sep(lambda x: x.get("fold") == "TRAIN")
        va = split_sep(lambda x: x.get("fold") == "VALIDATION")
        oos = split_sep(lambda x: x.get("fold") == "OOS")
        rec = split_sep(lambda x: x.get("recent180"))
        confirmed = confirmed_sep(
            _fold_rates(rows, feat, "TRAIN", True),
            _fold_rates(rows, feat, "TRAIN", False),
            _fold_rates(rows, feat, "VALIDATION", True),
            _fold_rates(rows, feat, "VALIDATION", False),
        )
        oos_same = confirmed_sep(
            _fold_rates(rows, feat, "TRAIN", True),
            _fold_rates(rows, feat, "TRAIN", False),
            _fold_rates(rows, feat, "OOS", True),
            _fold_rates(rows, feat, "OOS", False),
        )
        rec_cd = _rate([x for x in cd if x.get("recent180")], feat).get("rate")
        rec_ef = _rate([x for x in ef if x.get("recent180")], feat).get("rate")
        rec_same = confirmed_sep(
            _fold_rates(rows, feat, "TRAIN", True),
            _fold_rates(rows, feat, "TRAIN", False),
            rec_cd,
            rec_ef,
        )
        survives = bool(confirmed and oos_same and rec_same)
        feat_rows[feat] = {
            "CD": cd_r,
            "EF": ef_r,
            "FULL_sep": majority_sep(cd_r.get("rate"), ef_r.get("rate")),
            "TRAIN_sep": tr,
            "VAL_sep": va,
            "OOS_sep": oos,
            "RECENT180_sep": rec,
            "TRAIN_VAL_confirmed": confirmed,
            "survives_OOS": oos_same,
            "survives_recent180": rec_same,
            "survives_all_splits": survives,
        }
        if confirmed:
            separators.append(feat)
        if survives:
            survivors.append(feat)
    if survivors:
        disc = "SPLIT_SURVIVOR"
        overlap = "REDUCED"
    elif separators:
        disc = "TRAIN_VAL_ONLY"
        overlap = "LARGE"
    else:
        disc = "NOT_ESTABLISHED"
        overlap = "LARGE"
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
        "predeclared_concepts": PREDECLARED_CONCEPTS,
        "predeclared": {
            "STRUCTURAL_FRACTION": STRUCTURAL_FRACTION,
            "REVERSAL_BARS": REVERSAL_BARS,
            "CONSEC_OPP_MIN": CONSEC_OPP_MIN,
            "swing": "3-bar confirmed, one closed bar each side",
        },
        "n_with_retrace": len(rows),
        "n_CD": len(cd),
        "n_EF": len(ef),
        "features": feat_rows,
        "separators_train_val": separators,
        "survivors_all_splits": survivors,
        "STRUCTURAL_DISCRIMINATOR": disc,
        "OVERLAP": overlap,
        "structure_genuinely_different": bool(separators),
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H103-01",
                "claim": "Predeclared OHLC structure at first retrace separates C/D from E/F on TRAIN and VAL.",
                "result": disc,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["structure_at_retrace"],
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
        "artifacts": {"json": PHASE103_JSON, "md": PHASE103_MD},
    }
    (root / PHASE103_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE103_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE103_MD).write_text(
        "\n".join(
            [
                "# Phase 103 — Structure at Retracement",
                "",
                "FROZEN-DATA-EVIDENCE. Concepts predeclared. Unique-half wick / 3-bar swing / two opposite closes.",
                f"**STRUCTURAL_DISCRIMINATOR:** `{disc}`",
                f"**OVERLAP:** `{overlap}`",
                f"TRAIN+VAL separators: `{separators}`",
                f"TRAIN/VAL/OOS/recent180 survivors: `{survivors}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase103_collection(Path("."))
    print(p["STRUCTURAL_DISCRIMINATOR"], p["separators_train_val"], p["survivors_all_splits"])
