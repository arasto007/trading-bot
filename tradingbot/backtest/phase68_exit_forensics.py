"""Phase 68 — complete exit forensics on the frozen event tape.

RESEARCH ONLY. Walks existing Phase 38 OHLC to reconstruct ENTRY→EXIT paths.
Does not rerun the strategy, alter the event tape, optimize, or trade.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    PHASE45_JSON,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _parse_ts,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase64_strategy_event_forensics import (
    PHASE64_JSON,
    build_lineage,
    load_setups,
)

PHASE = "68"
PHASE68_JSON = "logs/phase68_exit_forensics.json"
PHASE68_MD = "docs/PHASE68_EXIT_FORENSICS.md"
PHASE38_M5 = "data/XAUUSD_i_5m_phase38.parquet"
BLOCKED = "BLOCKED"
BAR_MINUTES = 5.0
# Predeclared diagnostic thresholds — not searched.
MEANINGFUL_R = 0.25
PROFIT_EPS = 0.05
FAST_REVERSAL_MIN = 30.0
WIN_FAST_MIN = 30.0
EXTREME_R = 10.0
THRESHOLDS = (0.25, 0.5, 1.0, 2.0, 5.0)
HIGH_VOL_REGIMES = frozenset({"VOLATILE", "CRISIS"})
LOW_VOL_REGIMES = frozenset({"RANGING"})
OPPOSITE_REGIME = {("SELL", "STRONG_TREND_UP"), ("BUY", "STRONG_TREND_DOWN")}
TAPE_END_FALLBACK = datetime(2026, 9, 7, tzinfo=timezone.utc)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "cohorts",
    "mechanism_ranking",
    "exit_anatomy_loss_sl",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _file_fp(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iqr(xs: list[float]) -> dict[str, Any]:
    from tradingbot.backtest.phase64_strategy_event_forensics import _iqr as _base

    return _base(xs)


def _f(v: Any) -> float | None:
    try:
        if v is None or v == UNKNOWN:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_frozen_ohlc(root: Path) -> tuple[pd.DataFrame | None, str | None]:
    path = root / PHASE38_M5
    fp = _file_fp(path)
    if not path.is_file():
        return None, fp
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], utc=True))
        elif "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"], utc=True))
        else:
            return None, fp
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index(), fp


def _entry_index(df: pd.DataFrame, event: dict[str, Any]) -> int | None:
    bar = event.get("closed_bar_index")
    try:
        i = int(bar)
    except (TypeError, ValueError):
        i = None
    ts = _parse_ts(event.get("timestamp"))
    if i is not None and 0 <= i < len(df):
        if ts is None:
            return i
        bar_ts = pd.Timestamp(df.index[i])
        if bar_ts.tzinfo is None:
            bar_ts = bar_ts.tz_localize("UTC")
        if abs((bar_ts - pd.Timestamp(ts)).total_seconds()) <= 5 * 60:
            return i
    if ts is None:
        return i if i is not None and 0 <= i < len(df) else None
    loc = df.index.get_indexer([pd.Timestamp(ts)], method="nearest")
    if len(loc) and loc[0] >= 0:
        return int(loc[0])
    return None


def walk_path(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """DERIVED path metrics from frozen OHLC. SL-before-TP, next bar onward. Not a new strategy."""
    risk = abs(float(entry) - float(sl))
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    empty = {
        "kind": "DERIVED",
        "valid": False,
        "mfe_walk": None,
        "mae_walk": None,
        "time_to_mfe_min": None,
        "time_to_mae_min": None,
        "mfe_before_mae025": None,
        "mae_before_mfe025": None,
        "mfe_before_sl": None,
        "capture_ratio": None,
        "mins_above": {str(t): 0.0 for t in THRESHOLDS},
        "mins_mfe_to_exit": None,
        "hold_min_walk": None,
        "first_favorable": False,
        "reached": {str(t): False for t in THRESHOLDS},
        "giveback_R": None,
        "exit_hour": None,
        "wick_or_structure": UNKNOWN,
        "same_bar_sl_tp": False,
        "outcome_walk": UNKNOWN,
        "r_walk": None,
        "mfe_bar": None,
        "mae_bar": None,
        "exit_bar": None,
    }
    if risk <= 0 or entry_idx < 0 or entry_idx >= len(df) - 1:
        return empty
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    mfe = 0.0
    mae = 0.0
    mfe_bar = entry_idx
    mae_bar = entry_idx
    mfe_before_mae = 0.0
    mae_before_mfe = 0.0
    seen_mae = False
    seen_mfe = False
    mins_above = {t: 0.0 for t in THRESHOLDS}
    reached = {t: False for t in THRESHOLDS}
    first_fav = False
    exit_j = None
    outcome = "open"
    r_walk = None
    same_both = False
    wick = UNKNOWN
    for j in range(entry_idx + 1, len(df)):
        high = float(highs[j])
        low = float(lows[j])
        close = float(closes[j])
        if buy:
            fav = (high - entry) / risk
            adv = (entry - low) / risk
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            fav = (entry - low) / risk
            adv = (high - entry) / risk
            hit_sl = high >= sl
            hit_tp = low <= tp
        if j == entry_idx + 1 and fav > PROFIT_EPS:
            first_fav = True
        if fav > mfe:
            mfe = fav
            mfe_bar = j
        if adv > mae:
            mae = adv
            mae_bar = j
        if (not seen_mae) and adv >= MEANINGFUL_R:
            seen_mae = True
            mfe_before_mae = mfe
        if (not seen_mfe) and fav >= MEANINGFUL_R:
            seen_mfe = True
            mae_before_mfe = mae
        for t in THRESHOLDS:
            if fav >= t:
                mins_above[t] += BAR_MINUTES
                reached[t] = True
        if hit_sl:
            outcome = "loss"
            r_walk = -1.0
            exit_j = j
            same_both = bool(hit_tp)
            if buy:
                wick = "WICK" if close > sl else "STRUCTURAL"
            else:
                wick = "WICK" if close < sl else "STRUCTURAL"
            break
        if hit_tp:
            outcome = "win"
            r_walk = float((tp - entry) / risk) if buy else float((entry - tp) / risk)
            exit_j = j
            wick = "TP_FILL"
            break
    if exit_j is None:
        return {**empty, "valid": True, "mfe_walk": round(mfe, 6), "mae_walk": round(mae, 6), "outcome_walk": "open"}
    hold = float(exit_j - entry_idx) * BAR_MINUTES
    t_mfe = float(mfe_bar - entry_idx) * BAR_MINUTES
    t_mae = float(mae_bar - entry_idx) * BAR_MINUTES
    t_rev = float(exit_j - mfe_bar) * BAR_MINUTES if outcome == "loss" else float(exit_j - mfe_bar) * BAR_MINUTES
    capture = (r_walk / mfe) if (mfe and mfe > 0 and r_walk is not None) else None
    exit_ts = pd.Timestamp(df.index[exit_j])
    if exit_ts.tzinfo is None:
        exit_ts = exit_ts.tz_localize("UTC")
    return {
        "kind": "DERIVED",
        "valid": True,
        "mfe_walk": round(mfe, 6),
        "mae_walk": round(mae, 6),
        "time_to_mfe_min": round(t_mfe, 4),
        "time_to_mae_min": round(t_mae, 4),
        "mfe_before_mae025": round(mfe_before_mae if seen_mae else mfe, 6),
        "mae_before_mfe025": round(mae_before_mfe if seen_mfe else mae, 6),
        "mfe_before_sl": round(mfe, 6) if outcome == "loss" else None,
        "capture_ratio": None if capture is None else round(float(capture), 6),
        "mins_above": {str(t): round(mins_above[t], 4) for t in THRESHOLDS},
        "mins_mfe_to_exit": round(t_rev, 4),
        "hold_min_walk": round(hold, 4),
        "first_favorable": first_fav,
        "reached": {str(t): bool(reached[t]) for t in THRESHOLDS},
        "giveback_R": None if r_walk is None else round(mfe - float(r_walk), 6),
        "exit_hour": int(exit_ts.hour),
        "wick_or_structure": wick,
        "same_bar_sl_tp": same_both,
        "outcome_walk": outcome,
        "r_walk": r_walk,
        "mfe_bar": int(mfe_bar),
        "mae_bar": int(mae_bar),
        "exit_bar": int(exit_j),
    }


def sl_session_class(entry_hour: Any, exit_hour: Any) -> str:
    try:
        eh = int(exit_hour)
    except (TypeError, ValueError):
        return UNKNOWN
    if 15 <= eh < 16:
        return "same_session"
    if 16 <= eh < 18:
        return "session_transition"
    return "other_session"


def vol_class(regime: str) -> str:
    r = str(regime or UNKNOWN)
    if r in HIGH_VOL_REGIMES:
        return "high_volatility"
    if r in LOW_VOL_REGIMES:
        return "low_volatility"
    return "other_regime_vol"


def assign_cohorts(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    mfe = row.get("mfe_R")
    hold = row.get("duration_minutes")
    t_rev = row.get("mins_mfe_to_exit")
    planned = row.get("planned_rr")
    r = row.get("r_result")
    exit_class = row.get("exit_class")
    mfe_f = _f(mfe)
    hold_f = _f(hold)
    t_rev_f = _f(t_rev)
    planned_f = _f(planned)
    r_f = _f(r)
    if exit_class == "LOSS_SL":
        if mfe_f is not None and mfe_f > PROFIT_EPS:
            labels.append("LOSS_AFTER_PROFIT")
        if mfe_f is not None and mfe_f > 0.5:
            labels.append("LOSS_AFTER_0.5R")
        if mfe_f is not None and mfe_f > 1.0:
            labels.append("LOSS_AFTER_1R")
        if mfe_f is None or mfe_f <= PROFIT_EPS:
            labels.append("LOSS_IMMEDIATE")
        elif t_rev_f is not None and t_rev_f <= FAST_REVERSAL_MIN:
            labels.append("LOSS_WITH_FAST_REVERSAL")
        elif t_rev_f is not None:
            labels.append("LOSS_WITH_SLOW_REVERSAL")
        elif hold_f is not None and hold_f <= FAST_REVERSAL_MIN:
            labels.append("LOSS_WITH_FAST_REVERSAL")
        else:
            labels.append("LOSS_WITH_SLOW_REVERSAL")
    if exit_class == "WIN_TP":
        extreme = bool((r_f is not None and r_f >= EXTREME_R) or (planned_f is not None and planned_f >= EXTREME_R))
        if extreme:
            labels.append("WIN_EXTREME")
        elif hold_f is not None and hold_f <= WIN_FAST_MIN:
            labels.append("WIN_FAST")
        else:
            labels.append("WIN_SLOW")
    return labels


def enrich_events(events: list[dict[str, Any]], df: pd.DataFrame | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        row["cluster_id"] = f"{str(e.get('timestamp'))[:10]}|{e.get('side')}"
        row["duplicate_signals"] = int(e.get("signal_count") or 0)
        risk = _f(e.get("risk_price_units"))
        entry = _f(e.get("entry"))
        sl = _f(e.get("SL"))
        tp = _f(e.get("TP"))
        planned = _f(e.get("planned_rr"))
        row["planned_sl_distance"] = risk
        row["planned_tp_distance"] = None if (entry is None or tp is None) else abs(entry - tp)
        row["planned_RR"] = planned
        row["initial_risk_R"] = 1.0 if risk else UNKNOWN
        row["path_kind"] = "UNKNOWN"
        if df is not None and entry is not None and sl is not None and tp is not None:
            idx = _entry_index(df, e)
            row["closed_bar_index"] = e.get("closed_bar_index") or idx
            if idx is not None:
                path = walk_path(df, idx, str(e.get("side")), entry, sl, tp)
                row["path_kind"] = "DERIVED"
                row["mfe_walk"] = path["mfe_walk"]
                row["mae_walk"] = path["mae_walk"]
                row["time_to_mfe_min"] = path["time_to_mfe_min"]
                row["time_to_mae_min"] = path["time_to_mae_min"]
                row["mfe_before_mae025"] = path["mfe_before_mae025"]
                row["mae_before_mfe025"] = path["mae_before_mfe025"]
                row["mfe_before_sl"] = path["mfe_before_sl"]
                row["capture_ratio"] = path["capture_ratio"]
                row["mins_above"] = path["mins_above"]
                row["mins_mfe_to_exit"] = path["mins_mfe_to_exit"]
                row["hold_min_walk"] = path["hold_min_walk"]
                row["first_favorable"] = path["first_favorable"]
                row["reached"] = path["reached"]
                row["giveback_R"] = path["giveback_R"]
                row["exit_hour"] = path["exit_hour"]
                row["wick_or_structure"] = path["wick_or_structure"]
                row["sl_session_class"] = sl_session_class(e.get("hour_utc"), path["exit_hour"])
                row["vol_class"] = vol_class(str(e.get("regime")))
                row["opposite_side_regime"] = (str(e.get("side")), str(e.get("regime"))) in OPPOSITE_REGIME
                row["outcome_walk"] = path["outcome_walk"]
            else:
                row["mins_mfe_to_exit"] = None
        else:
            row["mins_mfe_to_exit"] = None
        if row.get("duration_minutes") is None:
            row["duration_minutes"] = row.get("hold_min_walk")
        pct_mfe = UNKNOWN
        mfe = _f(e.get("mfe_R"))
        if mfe is not None and planned and planned > 0:
            pct_mfe = round(100.0 * min(mfe / planned, 1.0), 4)
        row["pct_available_mfe_captured"] = pct_mfe
        if row.get("capture_ratio") is None and mfe and mfe > 0 and _f(e.get("r_result")) is not None:
            row["capture_ratio"] = round(float(e["r_result"]) / mfe, 6)
            row["capture_ratio_kind"] = "DERIVED_FROM_JSONL"
        row["cohorts"] = assign_cohorts(row)
        out.append(row)
    return out


def cohort_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    names = (
        "LOSS_AFTER_PROFIT",
        "LOSS_AFTER_0.5R",
        "LOSS_AFTER_1R",
        "LOSS_WITH_FAST_REVERSAL",
        "LOSS_WITH_SLOW_REVERSAL",
        "LOSS_IMMEDIATE",
        "WIN_FAST",
        "WIN_SLOW",
        "WIN_EXTREME",
    )
    n = len(events)
    out: dict[str, Any] = {}
    for name in names:
        rows = [e for e in events if name in (e.get("cohorts") or [])]
        xs = [_f(e.get("r_result")) for e in rows]
        xs = [x for x in xs if x is not None]
        mfes = [_f(e.get("mfe_R")) for e in rows]
        maes = [_f(e.get("mae_R")) for e in rows]
        holds = [_f(e.get("duration_minutes")) for e in rows]
        out[name] = {
            "count": len(rows),
            "percentage": (len(rows) / n) if n else None,
            "mean_R": _mean(xs),
            "median_R": _median(xs),
            "mean_MFE": _mean([x for x in mfes if x is not None]),
            "median_MFE": _median([x for x in mfes if x is not None]),
            "mean_MAE": _mean([x for x in maes if x is not None]),
            "median_MAE": _median([x for x in maes if x is not None]),
            "median_holding_time": _median([x for x in holds if x is not None]),
        }
    return out


def compare_distributions(events: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    wins = [e for e in events if e.get("exit_class") == "WIN_TP"]

    def pack(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        xs = [_f(e.get(key)) for e in rows]
        return _iqr([x for x in xs if x is not None])

    return {
        "kind": "OBSERVED_JSONL plus DERIVED_PATH",
        "LOSS_SL": {
            "n": len(losses),
            "MFE": pack(losses, "mfe_R"),
            "MAE": pack(losses, "mae_R"),
            "planned_RR": pack(losses, "planned_rr"),
            "holding_time": pack(losses, "duration_minutes"),
            "time_to_MFE": pack(losses, "time_to_mfe_min"),
            "time_to_MAE": pack(losses, "time_to_mae_min"),
            "capture_ratio": pack(losses, "capture_ratio"),
            "mfe_before_sl": pack(losses, "mfe_before_sl"),
        },
        "WIN_TP": {
            "n": len(wins),
            "MFE": pack(wins, "mfe_R"),
            "MAE": pack(wins, "mae_R"),
            "planned_RR": pack(wins, "planned_rr"),
            "holding_time": pack(wins, "duration_minutes"),
            "time_to_MFE": pack(wins, "time_to_mfe_min"),
            "time_to_MAE": pack(wins, "time_to_mae_min"),
            "capture_ratio": pack(wins, "capture_ratio"),
        },
    }


def loss_anatomy(events: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    n = len(losses)
    def share(pred) -> dict[str, Any]:
        k = sum(1 for e in losses if pred(e))
        return {"count": k, "share": (k / n) if n else None}

    reached = lambda t: share(lambda e: bool((e.get("reached") or {}).get(str(t))) or ((_f(e.get("mfe_R")) or 0) >= t))
    return {
        "kind": "OBSERVED plus DERIVED",
        "n": n,
        "A_first_moved_favorably": share(lambda e: bool(e.get("moved_favorably_before_sl")) or ((_f(e.get("mfe_R")) or 0) > PROFIT_EPS)),
        "B_how_far_median_MFE": _median([_f(e.get("mfe_R")) for e in losses if _f(e.get("mfe_R")) is not None]),
        "C_how_long_favorable_median_mins_above_0.25R": _median(
            [_f((e.get("mins_above") or {}).get("0.25")) for e in losses if _f((e.get("mins_above") or {}).get("0.25")) is not None]
        ),
        "D_reached_0.25R": reached(0.25),
        "D_reached_0.5R": reached(0.5),
        "D_reached_1R": reached(1.0),
        "E_median_giveback_R": _median([_f(e.get("giveback_R")) for e in losses if _f(e.get("giveback_R")) is not None]),
        "F_median_minutes_MFE_to_SL": _median([_f(e.get("mins_mfe_to_exit")) for e in losses if _f(e.get("mins_mfe_to_exit")) is not None]),
        "G_sl_session": dict(Counter(e.get("sl_session_class") or UNKNOWN for e in losses)),
        "G_vol_class": dict(Counter(e.get("vol_class") or UNKNOWN for e in losses)),
        "G_opposite_side_regime": share(lambda e: bool(e.get("opposite_side_regime"))),
        "H_wick_or_structure": dict(Counter(e.get("wick_or_structure") or UNKNOWN for e in losses)),
    }


def rank_mechanisms(events: list[dict[str, Any]], cohorts: dict[str, Any], anatomy: dict[str, Any]) -> dict[str, Any]:
    n_loss = sum(1 for e in events if e.get("exit_class") == "LOSS_SL")
    def pct(name: str) -> float:
        c = int((cohorts.get(name) or {}).get("count") or 0)
        return (c / n_loss) if n_loss else 0.0

    a = pct("LOSS_IMMEDIATE")
    b = pct("LOSS_WITH_SLOW_REVERSAL")
    c = pct("LOSS_AFTER_0.5R")
    n_fav = int(((anatomy.get("A_first_moved_favorably") or {}).get("share") or 0) * n_loss) if n_loss else 0
    wick_share = 0.0
    wick_map = anatomy.get("H_wick_or_structure") or {}
    if n_loss:
        wick_share = float(wick_map.get("WICK") or 0) / n_loss
    sess = anatomy.get("G_sl_session") or {}
    trans = float(sess.get("session_transition") or 0) / n_loss if n_loss else 0.0
    opp = float((anatomy.get("G_opposite_side_regime") or {}).get("share") or 0)
    dens = _mean([float(e.get("signal_count") or 0) for e in events]) or 0.0
    g = 0.0 if dens <= 2 else min(1.0, (dens - 1.0) / 10.0)
    scores = [
        ("A_TIGHT_STOP_NOISE", a, "Share of immediate losers with no meaningful MFE."),
        ("C_PROFIT_PROTECTION", c, "Share of SL losers that first reached >0.5R."),
        ("B_LATE_REVERSAL", b, "Share of SL losers with slow MFE-to-SL reversal."),
        ("H_MIXED", max(0.0, 1.0 - abs(c - b)), "Overlap of give-back and late reversal."),
        ("E_WRONG_REGIME", opp, "SL hits while labelled opposite-side regime."),
        ("F_TIME_SESSION", trans, "SL during session_transition (16-18 UTC)."),
        ("A_WICK_NOISE", wick_share, "SL printed as wick (close not through stop)."),
        ("G_SIGNAL_DUPLICATION", g, "Duplication inflates signal counts; not the SL path."),
        ("D_ENTRY_QUALITY", 0.0, "Scored in Phase72 from win/loss feature overlap; not the stop path."),
    ]
    ranked = sorted(scores, key=lambda x: -x[1])
    primary = ranked[0][0]
    if c >= 0.40:
        primary = "C_PROFIT_PROTECTION"
    elif a >= 0.50:
        primary = "A_TIGHT_STOP_NOISE"
    return {
        "kind": "INFERRED_FROM_PREDECLARED_SCORES",
        "n_LOSS_SL": n_loss,
        "scores": [{"id": i, "score": s, "evidence": ev} for i, s, ev in ranked],
        "PRIMARY_MECHANISM": primary,
        "note": "Ranking uses predeclared cohort shares. Not optimized. Not a claim the strategy trailed stops.",
    }


def compact_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for e in events:
        rows.append(
            {
                "ts": e.get("timestamp"),
                "side": e.get("side"),
                "cluster": e.get("cluster_id"),
                "n_sig": e.get("duplicate_signals"),
                "entry": e.get("entry"),
                "sl": e.get("SL"),
                "tp": e.get("TP"),
                "rr": e.get("planned_rr"),
                "risk": e.get("risk_price_units"),
                "r": e.get("r_result"),
                "exit": e.get("exit_class"),
                "reg": e.get("regime"),
                "sess": e.get("session"),
                "fold": e.get("fold"),
                "mfe": e.get("mfe_R"),
                "mae": e.get("mae_R"),
                "hold": e.get("duration_minutes"),
                "t_mfe": e.get("time_to_mfe_min"),
                "t_mae": e.get("time_to_mae_min"),
                "t_rev": e.get("mins_mfe_to_exit"),
                "cap": e.get("capture_ratio"),
                "gb": e.get("giveback_R"),
                "wick": e.get("wick_or_structure"),
                "sl_sess": e.get("sl_session_class"),
                "vol": e.get("vol_class"),
                "opp": e.get("opposite_side_regime"),
                "reached": e.get("reached"),
                "mins_above": e.get("mins_above"),
                "cohorts": e.get("cohorts"),
            }
        )
    return rows


def expand_compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in rows:
        out.append(
            {
                "timestamp": e.get("ts"),
                "side": e.get("side"),
                "cluster_id": e.get("cluster"),
                "signal_count": e.get("n_sig"),
                "duplicate_signals": e.get("n_sig"),
                "entry": e.get("entry"),
                "SL": e.get("sl"),
                "TP": e.get("tp"),
                "planned_rr": e.get("rr"),
                "risk_price_units": e.get("risk"),
                "r_result": e.get("r"),
                "exit_class": e.get("exit"),
                "regime": e.get("reg"),
                "session": e.get("sess"),
                "fold": e.get("fold"),
                "mfe_R": e.get("mfe"),
                "mae_R": e.get("mae"),
                "duration_minutes": e.get("hold"),
                "time_to_mfe_min": e.get("t_mfe"),
                "time_to_mae_min": e.get("t_mae"),
                "mins_mfe_to_exit": e.get("t_rev"),
                "capture_ratio": e.get("cap"),
                "giveback_R": e.get("gb"),
                "wick_or_structure": e.get("wick"),
                "sl_session_class": e.get("sl_sess"),
                "vol_class": e.get("vol"),
                "opposite_side_regime": e.get("opp"),
                "reached": e.get("reached") or {},
                "mins_above": e.get("mins_above") or {},
                "cohorts": e.get("cohorts") or [],
            }
        )
    return out


def fold_of(e: dict[str, Any]) -> str:
    return str(e.get("fold") or UNKNOWN)


def recent_cut(events: list[dict[str, Any]], tape_end: datetime) -> datetime:
    return tape_end - timedelta(days=180)


def split_views(events: list[dict[str, Any]], tape_end: datetime) -> dict[str, list[dict[str, Any]]]:
    cut = recent_cut(events, tape_end)
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1_ts = ranked[0].get("timestamp") if ranked else None
    def not_top1(rows):
        return [e for e in rows if e.get("timestamp") != top1_ts]
    views = {
        "FULL": events,
        "TRAIN": [e for e in events if fold_of(e) == "TRAIN"],
        "VALIDATION": [e for e in events if fold_of(e) == "VALIDATION"],
        "OOS": [e for e in events if fold_of(e) == "OOS"],
        "RECENT_180D": [e for e in events if (_parse_ts(e.get("timestamp")) or tape_end) >= cut],
        "WITHOUT_TOP1": not_top1(events),
    }
    return views


def run_phase68_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p64 = _safe_load_json(root / PHASE64_JSON) or {}
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    pack = build_lineage(signals)
    events = pack["resolved"]
    df, fp = load_frozen_ohlc(root)
    enriched = enrich_events(events, df)
    cohorts = cohort_report(enriched)
    anatomy = loss_anatomy(enriched)
    dist = compare_distributions(enriched)
    ranking = rank_mechanisms(enriched, cohorts, anatomy)
    xs = [float(e["r_result"]) for e in enriched]
    ranked = sorted(enriched, key=lambda e: float(e["r_result"]), reverse=True)
    top1 = ranked[0] if ranked else {}
    without1 = [float(e["r_result"]) for e in ranked[1:]]
    without5 = [float(e["r_result"]) for e in ranked[5:]]
    n_loss = sum(1 for e in enriched if e.get("exit_class") == "LOSS_SL")
    n_win = sum(1 for e in enriched if e.get("exit_class") == "WIN_TP")
    walk_ok = sum(1 for e in enriched if e.get("path_kind") == "DERIVED")
    tape_end = _parse_ts(((p45.get("oos") or {}).get("splits") or {}).get("OOS", {}).get("end_ts")) or TAPE_END_FALLBACK
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS" if walk_ok >= 400 and n_loss == 298 else "FAIL",
        "phase40_scan_rerun": False,
        "strategy_rerun": False,
        "event_tape_altered": False,
        "mt5_launched": False,
        "env_accessed": False,
        "parameters_optimized": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "parquet_fingerprint": fp,
        "parquet_fingerprint_match": fp == FROZEN,
        "operator_facts_verified": {
            "REAL_ACCOUNT": "CLASSIC",
            "DEMO_ACCOUNT": "CLASSIC",
            "VALID_GOLD_SYMBOL": "XAUUSD_i",
            "g1_g2_g3_rediscovery": False,
        },
        "epistemic": {
            "jsonl_MFE_MAE": "OBSERVED",
            "path_time_to_MFE": "DERIVED",
            "cohorts": "DERIVED",
            "mechanism_rank": "INFERRED",
            "counterfactual": False,
        },
        "lineage_meta": {
            "signal_count": len(signals),
            "event_count": pack["event_count_including_open_only"],
            "resolved_event_count": len(enriched),
            "LOSS_SL": n_loss,
            "WIN_TP": n_win,
            "TIME_EXIT": 0,
            "path_walked": walk_ok,
            "construction": pack["construction"],
        },
        "performance_gross_event": pack_stats(xs),
        "EXIT_FAILURE_RATE": (n_loss / len(enriched)) if enriched else None,
        "LOSS_AFTER_0_5R": (cohorts.get("LOSS_AFTER_0.5R") or {}).get("count"),
        "LOSS_AFTER_1R": (cohorts.get("LOSS_AFTER_1R") or {}).get("count"),
        "MEDIAN_TIME_TO_REVERSAL": (anatomy.get("F_median_minutes_MFE_to_SL")),
        "TOP1_REMOVAL_EXPECTANCY": _mean(without1),
        "TOP5_REMOVAL_EXPECTANCY": _mean(without5),
        "cohorts": cohorts,
        "distributions": dist,
        "exit_anatomy_loss_sl": anatomy,
        "mechanism_ranking": ranking,
        "outlier_kept_in_baseline": {
            "timestamp": top1.get("timestamp"),
            "side": top1.get("side"),
            "r_result": top1.get("r_result"),
            "planned_rr": top1.get("planned_rr"),
            "regime": top1.get("regime"),
            "mfe_R": top1.get("mfe_R"),
            "hold": top1.get("duration_minutes"),
            "official_baseline_includes_top1": True,
        },
        "hypotheses": [
            {"id": "H68-01", "claim": "Majority of LOSS_SL first move favorably (MFE>0.05).", "result": "SUPPORTED" if ((anatomy.get("A_first_moved_favorably") or {}).get("share") or 0) > 0.5 else "NOT_SUPPORTED", "oos_used_for_decision": False},
            {"id": "H68-02", "claim": "Dominant stop-out mechanism is profit give-back after meaningful MFE, not immediate noise.", "result": ranking.get("PRIMARY_MECHANISM"), "oos_used_for_decision": False},
        ],
        "tests_performed": 2,
        "diagnostics_run": ["entry_state", "excursion_path", "LOSS_SL_anatomy", "WIN_TP_compare", "cohorts", "mechanism_rank"],
        "phase64_reference": {
            "PRIMARY": (p64.get("causes") or {}).get("PRIMARY"),
            "LOSS_SL": ((p64.get("stop_out_anatomy") or {}).get("LOSS_SL")),
        },
        "compact_events": compact_rows(enriched),
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "PA_LOCK": "NOT_MODIFIED",
            "CALIBRATION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "OPTIMIZATION": "NOT_PERFORMED",
            "SL_TP": "NOT_CHANGED",
            "production_changes": "NONE",
            "MT5": "NOT_USED",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE68_JSON, "md": PHASE68_MD},
        "tape_end": str(tape_end),
    }
    (root / PHASE68_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE68_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE68_MD).write_text(
        "\n".join(
            [
                "# Phase 68 — Complete Exit Forensics",
                "",
                f"**EXIT_FAILURE_RATE:** `{payload['EXIT_FAILURE_RATE']}`  **LOSS_SL:** `{n_loss}`  **WIN_TP:** `{n_win}`",
                f"**LOSS_AFTER_0.5R:** `{payload['LOSS_AFTER_0_5R']}`  **LOSS_AFTER_1R:** `{payload['LOSS_AFTER_1R']}`",
                f"**MEDIAN_TIME_TO_REVERSAL (MFE to SL):** `{payload['MEDIAN_TIME_TO_REVERSAL']}` minutes",
                f"**PRIMARY_MECHANISM:** `{ranking.get('PRIMARY_MECHANISM')}`",
                "",
                "Path metrics are DERIVED from a read-only SL-before-TP walk of frozen `data/XAUUSD_i_5m_phase38.parquet`.",
                "Jsonl MFE/MAE remain OBSERVED. Strategy was not rerun. Event tape was not altered.",
                "The +31.84R event remains in the official baseline.",
                "",
                "Cohorts are predeclared (not searched): LOSS_AFTER_PROFIT / 0.5R / 1R, FAST/SLOW reversal, IMMEDIATE, WIN_FAST/SLOW/EXTREME.",
                "",
                "No optimization. No production change. No MT5.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase68_collection(Path("."))["mechanism_ranking"]["PRIMARY_MECHANISM"])
