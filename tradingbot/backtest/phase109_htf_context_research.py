"""Phase 109 — higher-timeframe forensic context (M15 canonical XAUUSD_i).

Does not redesign the strategy. Last CLOSED M15 bar only. No ATR (not in source).
Logical XAUUSD HTF files are not used (EV-EQ-01 NOT_PROVEN).
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
from tradingbot.backtest.phase68_exit_forensics import TAPE_END_FALLBACK
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f
from tradingbot.backtest.phase82_profit_protection_design import REVERSAL_BARS, STRUCTURAL_FRACTION
from tradingbot.backtest.phase98_first_favorable_state import (
    CD,
    EF,
    PHASE98_JSON,
    _rate,
    confirmed_sep,
    majority_sep,
)

PHASE = "109"
PHASE109_JSON = "logs/phase109_htf_context_research.json"
PHASE109_MD = "docs/PHASE109_HTF_CONTEXT_RESEARCH.md"
BLOCKED = "BLOCKED"
M15_PATH = "data/XAUUSD_i_m15_phase38.parquet"
H4_PATH = "data/XAUUSD_i_4h.parquet"
M15_MINUTES = 15
H4_MINUTES = 240
PREDECLARED = (
    "htf_aligned",
    "htf_range_expand",
    "htf_close_fav_half",
    "htf_consec_fav_ge_2",
    "htf_near_fav_extreme",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "HTF_DISCRIMINATOR_STATUS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _load_ohlc(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], utc=True))
        else:
            return None
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index()


def last_closed_idx(index: pd.DatetimeIndex, ts: pd.Timestamp, bar_minutes: int) -> int | None:
    """Bar `time` is MT5 copy_rates open. Closed iff open + duration <= event ts."""
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    i = int(index.searchsorted(ts, side="right")) - 1
    delta = pd.Timedelta(minutes=bar_minutes)
    while i >= 0:
        if index[i] + delta <= ts:
            return i
        i -= 1
    return None


def m15_features(df: pd.DataFrame, idx: int, buy: bool) -> dict[str, Any]:
    row = df.iloc[idx]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    brange = h - l
    bull = c > o
    aligned = bull if buy else (not bull)
    loc = None if brange <= 0 else (c - l) / brange
    close_fav = None if loc is None else (loc >= STRUCTURAL_FRACTION if buy else loc <= (1.0 - STRUCTURAL_FRACTION))
    expand = False
    if idx >= 1:
        prev = df.iloc[idx - 1]
        pr = float(prev["high"]) - float(prev["low"])
        expand = bool(pr > 0 and brange > pr)
    consec = 0
    for k in range(idx, max(-1, idx - 8), -1):
        ck = float(df.iloc[k]["close"])
        ok = float(df.iloc[k]["open"])
        fav_close = (ck > ok) if buy else (ck < ok)
        if fav_close:
            consec += 1
        else:
            break
    lo = max(0, idx - REVERSAL_BARS + 1)
    window = df.iloc[lo : idx + 1]
    wh, wl = float(window["high"].max()), float(window["low"].min())
    wr = wh - wl
    if wr <= 0:
        near = False
    elif buy:
        near = (wh - c) / wr <= STRUCTURAL_FRACTION
    else:
        near = (c - wl) / wr <= STRUCTURAL_FRACTION
    return {
        "htf_aligned": bool(aligned),
        "htf_range_expand": bool(expand),
        "htf_close_fav_half": bool(close_fav) if close_fav is not None else None,
        "htf_consec_fav_ge_2": consec >= 2,
        "htf_near_fav_extreme": bool(near),
        "m15_open": o,
        "m15_close": c,
    }


def run_phase109_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    cut = tape_end - timedelta(days=180)
    m15 = _load_ohlc(root / M15_PATH)
    h4 = _load_ohlc(root / H4_PATH)
    compact = p98.get("compact") or []
    rows = []
    n_cover = 0
    n_h4 = 0
    if m15 is not None:
        for r in compact:
            ts = _parse_ts(r.get("ts"))
            if ts is None:
                continue
            pts = pd.Timestamp(ts)
            idx = last_closed_idx(m15.index, pts, M15_MINUTES)
            if idx is None:
                continue
            n_cover += 1
            buy = str(r.get("side") or "").upper() in {"BUY", "1", "LONG"}
            feat = m15_features(m15, idx, buy)
            h4_aligned = None
            if h4 is not None:
                hi = last_closed_idx(h4.index, pts, H4_MINUTES)
                if hi is not None:
                    n_h4 += 1
                    bar = h4.iloc[hi]
                    h4_bull = float(bar["close"]) > float(bar["open"])
                    h4_aligned = h4_bull if buy else (not h4_bull)
            rows.append(
                {
                    **feat,
                    "h4_aligned": h4_aligned,
                    "ts": r.get("ts"),
                    "path_class": r.get("path_class"),
                    "fold": r.get("fold"),
                    "side": r.get("side"),
                    "reg": r.get("reg"),
                    "year": r.get("year"),
                    "orig": r.get("orig"),
                    "n_sig": r.get("n_sig"),
                    "is_CD": r.get("path_class") in CD,
                    "is_EF": r.get("path_class") in EF,
                    "recent180": bool(pts >= pd.Timestamp(cut)),
                }
            )
    cd = [x for x in rows if x.get("is_CD")]
    ef = [x for x in rows if x.get("is_EF")]
    feat_rows = {}
    separators = []
    survivors = []

    def fold_rate(group: list[dict[str, Any]], fold: str, feat: str) -> float | None:
        return _rate([x for x in group if x.get("fold") == fold], feat).get("rate")

    for feat in PREDECLARED:
        cd_r, ef_r = _rate(cd, feat), _rate(ef, feat)
        tr = majority_sep(fold_rate(cd, "TRAIN", feat), fold_rate(ef, "TRAIN", feat))
        va = majority_sep(fold_rate(cd, "VALIDATION", feat), fold_rate(ef, "VALIDATION", feat))
        oos = majority_sep(fold_rate(cd, "OOS", feat), fold_rate(ef, "OOS", feat))
        rec_cd = _rate([x for x in cd if x.get("recent180")], feat).get("rate")
        rec_ef = _rate([x for x in ef if x.get("recent180")], feat).get("rate")
        rec = majority_sep(rec_cd, rec_ef)
        confirmed = confirmed_sep(
            fold_rate(cd, "TRAIN", feat),
            fold_rate(ef, "TRAIN", feat),
            fold_rate(cd, "VALIDATION", feat),
            fold_rate(ef, "VALIDATION", feat),
        )
        oos_same = confirmed_sep(
            fold_rate(cd, "TRAIN", feat),
            fold_rate(ef, "TRAIN", feat),
            fold_rate(cd, "OOS", feat),
            fold_rate(ef, "OOS", feat),
        )
        rec_same = confirmed_sep(
            fold_rate(cd, "TRAIN", feat),
            fold_rate(ef, "TRAIN", feat),
            rec_cd,
            rec_ef,
        )
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
        }
        if confirmed:
            separators.append(feat)
        if confirmed and oos_same and rec_same:
            survivors.append(feat)
    n_all = len(compact) or 1
    cover_frac = n_cover / n_all
    if m15 is None:
        status = "DATA_MISSING"
    elif cover_frac < STRUCTURAL_FRACTION and not separators:
        status = "DATA_LIMITED"
    elif survivors:
        status = "PARTIALLY_SUPPORTED"
    elif separators:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "UNSUPPORTED"
    ranked = sorted(compact, key=lambda r: float(r.get("orig") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    tail_covered = any(x.get("ts") == top1.get("ts") for x in rows)
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
        "predeclared_features": PREDECLARED,
        "m15_path": M15_PATH,
        "h4_path": H4_PATH,
        "logical_xauusd_used": False,
        "n_events": len(compact),
        "n_m15_covered": n_cover,
        "n_h4_covered": n_h4,
        "coverage_frac": cover_frac,
        "n_CD_covered": len(cd),
        "n_EF_covered": len(ef),
        "features": feat_rows,
        "separators_train_val": separators,
        "survivors_all_splits": survivors,
        "HTF_DISCRIMINATOR_STATUS": status,
        "tail_event_m15_covered": tail_covered,
        "outlier_ts": top1.get("ts"),
        "strategy_redesigned": False,
        "evidence_kind": "NON-OHLC-DATA-EVIDENCE" if m15 is not None else "DATA_MISSING",
        "hypotheses": [
            {
                "id": "H109-01",
                "claim": "Canonical M15 context known before entry separates C/D from E/F on TRAIN and VAL.",
                "result": status,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["m15_asof_closed_bar"],
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
        "artifacts": {"json": PHASE109_JSON, "md": PHASE109_MD},
    }
    (root / PHASE109_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE109_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE109_MD).write_text(
        "\n".join(
            [
                "# Phase 109 — Higher-Timeframe Context",
                "",
                "NON-OHLC-DATA-EVIDENCE from canonical `XAUUSD_i` M15. Last closed bar only. Strategy not redesigned.",
                f"**HTF_DISCRIMINATOR_STATUS:** `{status}`",
                f"M15 coverage `{n_cover}/{len(compact)}` H4 coverage `{n_h4}` (H4 tape is short).",
                f"TRAIN+VAL separators: `{separators}` survivors: `{survivors}`",
                "Logical XAUUSD HTF files were not used (EV-EQ-01 NOT_PROVEN).",
                f"Tail event M15-covered: `{tail_covered}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase109_collection(Path("."))
    print(p["HTF_DISCRIMINATOR_STATUS"], p["n_m15_covered"], p["separators_train_val"])
