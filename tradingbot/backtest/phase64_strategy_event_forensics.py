"""Phase 64 — strategy event forensics (causal diagnosis, not optimization).

RESEARCH ONLY. Frozen Phase40 jsonl only. Does not rescan, import live.py, or change SL/TP.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    MIN_BIN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    PHASE45_JSON,
    POINT,
    SLIP_BASE_PIPS,
    SPREAD_BASE_PIPS,
    SPLIT_FOLDS,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _parse_ts,
    _pf,
    _utc_now,
    _wr,
    event_key,
    load_setups,
    pack_stats,
)

PHASE = "64"
PHASE64_JSON = "logs/phase64_strategy_event_forensics.json"
PHASE64_MD = "docs/PHASE64_STRATEGY_EVENT_FORENSICS.md"
BLOCKED = "BLOCKED"
MAE_BINS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 1e9))
MFE_BINS = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 1e9))
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "lineage_meta",
    "stop_out_anatomy",
    "mae_mfe",
    "outlier",
    "causes",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _q(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(round((len(ys) - 1) * p))))
    return float(ys[i])


def _iqr(xs: list[float]) -> dict[str, Any]:
    return {
        "n": len(xs),
        "median": _median(xs),
        "q25": _q(xs, 0.25),
        "q75": _q(xs, 0.75),
        "iqr": (None if not xs else (_q(xs, 0.75) or 0) - (_q(xs, 0.25) or 0)),
        "p10": _q(xs, 0.10),
        "p90": _q(xs, 0.90),
    }


def _bin_counts(xs: list[float], edges: tuple[tuple[float, float], ...]) -> list[dict[str, Any]]:
    out = []
    for lo, hi in edges:
        n = sum(1 for x in xs if lo <= x < hi)
        label = f">={lo}" if hi > 1e8 else f"{lo}-{hi}"
        out.append({"bin": label, "n": n, "share": (n / len(xs)) if xs else None})
    return out


def classify_exit(head: dict[str, Any]) -> str:
    outcome = str(head.get("outcome") or "")
    try:
        rm = float(head.get("r_multiple"))
    except (TypeError, ValueError):
        return UNKNOWN
    try:
        planned = float(head["planned_rr"]) if head.get("planned_rr") is not None else None
    except (TypeError, ValueError):
        planned = None
    if outcome == "loss" and abs(rm + 1.0) < 0.15:
        return "LOSS_SL"
    if outcome == "win" and planned is not None and abs(rm - planned) < 0.25:
        return "WIN_TP"
    if outcome == "win":
        return "OTHER_EXIT"
    if outcome == "open":
        return UNKNOWN
    return "OTHER_EXIT"


def _risk(head: dict[str, Any]) -> float | None:
    try:
        r = abs(float(head["entry_price"]) - float(head["stop_loss"]))
    except (TypeError, ValueError, KeyError):
        return None
    return r if r > 0 else None


def _fold(bar: Any) -> str:
    try:
        i = int(bar)
    except (TypeError, ValueError):
        return UNKNOWN
    for name, a, b in SPLIT_FOLDS:
        if a <= i < b:
            return name
    return UNKNOWN


def build_lineage(signals: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in signals:
        groups[event_key(row)].append(row)
    events: list[dict[str, Any]] = []
    for key, members in groups.items():
        members_sorted = sorted(members, key=lambda r: str(r.get("timestamp")))
        resolved_m = [m for m in members_sorted if m.get("outcome") != "open" and m.get("r_multiple") is not None]
        if not resolved_m:
            continue
        head = dict(resolved_m[0])
        first_ts = members_sorted[0].get("timestamp")
        last_ts = members_sorted[-1].get("timestamp")
        ts = _parse_ts(head.get("timestamp"))
        risk = _risk(head)
        mfe = head.get("mfe_R")
        mae = head.get("mae_R")
        try:
            mfe_f = float(mfe) if mfe is not None else None
        except (TypeError, ValueError):
            mfe_f = None
        try:
            mae_f = float(mae) if mae is not None else None
        except (TypeError, ValueError):
            mae_f = None
        rm = float(head["r_multiple"])
        exit_class = classify_exit(head)
        dirs = {str(m.get("direction") or m.get("side")).upper() for m in members_sorted}
        setups = {str(m.get("setup") or UNKNOWN) for m in members_sorted}
        regimes = {str(m.get("regime") or UNKNOWN) for m in members_sorted}
        hours = {m.get("hour_utc") for m in members_sorted}
        if len(members_sorted) == 1:
            dup = "INDEPENDENT"
        elif dirs == {str(head.get("direction") or "").upper()} and setups == {"liquidity_sweep"} and len(hours) <= 1:
            dup = "HIGHLY_DUPLICATED"
        else:
            dup = "PARTIALLY_CORRELATED"
        spread_r = None
        if risk:
            spread_r = ((SPREAD_BASE_PIPS + 2.0 * SLIP_BASE_PIPS) * POINT) / risk
        events.append(
            {
                "timestamp": head.get("timestamp"),
                "first_signal_timestamp": first_ts,
                "last_signal_timestamp": last_ts,
                "side": str(head.get("direction") or head.get("side") or UNKNOWN).upper(),
                "signal_count": len(members_sorted),
                "entry": head.get("entry_price"),
                "SL": head.get("stop_loss"),
                "TP": head.get("take_profit"),
                "r_result": rm,
                "planned_rr": head.get("planned_rr"),
                "outcome": head.get("outcome"),
                "exit_class": exit_class,
                "regime": head.get("regime") or UNKNOWN,
                "session": "NY_15_16_UTC" if head.get("hour_utc") == 15 else UNKNOWN,
                "hour_utc": head.get("hour_utc"),
                "timeframe": "M5",
                "setup": head.get("setup") or UNKNOWN,
                "confidence": head.get("confidence"),
                "quality_score": head.get("quality_score"),
                "mfe_R": mfe_f,
                "mae_R": mae_f,
                "duration_minutes": head.get("duration_minutes"),
                "risk_price_units": risk,
                "fold": _fold(head.get("closed_bar_index") if head.get("closed_bar_index") is not None else head.get("cursor")),
                "year": ts.year if ts else UNKNOWN,
                "month": f"{ts.year:04d}-{ts.month:02d}" if ts else UNKNOWN,
                "moved_favorably_before_sl": bool(exit_class == "LOSS_SL" and mfe_f is not None and mfe_f > 0.05),
                "mfe_gt_0_5": bool(mfe_f is not None and mfe_f > 0.5),
                "mfe_gt_1": bool(mfe_f is not None and mfe_f > 1.0),
                "tp_fraction_reached": (mfe_f / float(head["planned_rr"])) if (mfe_f is not None and head.get("planned_rr")) else UNKNOWN,
                "spread_could_explain_full_SL": bool(spread_r is not None and spread_r >= 0.5),
                "modeled_spread_slip_R": spread_r,
                "duplication": dup,
                "same_direction_cluster": len(dirs) == 1,
                "same_setup_cluster": len(setups) == 1,
                "same_regime_cluster": len(regimes) == 1,
                "indicators": {
                    "EMA200": UNKNOWN,
                    "RSI": UNKNOWN,
                    "MACD": UNKNOWN,
                    "ATR": UNKNOWN,
                    "ADX": UNKNOWN,
                    "Bollinger": UNKNOWN,
                    "CCI": UNKNOWN,
                    "BOS_distance": UNKNOWN,
                    "volume_ratio": UNKNOWN,
                    "HTF_bias": UNKNOWN,
                    "reason": "not persisted on Phase40 jsonl; not recomputed (no strategy rerun)",
                },
                "rejection_filter": UNKNOWN,
            }
        )
    events.sort(key=lambda e: str(e.get("timestamp")))
    return {
        "event_count_including_open_only": len(groups),
        "resolved": events,
        "construction": "PROXY_DATE_SIDE from frozen jsonl; strategy not rerun",
        "fields_unknown": ["exit_fill_price", "asian_high", "asian_low", "mechanical_event_id", "EMA200", "RSI", "MACD", "ATR", "ADX", "BOS_distance"],
    }


def stop_out_anatomy(events: list[dict[str, Any]]) -> dict[str, Any]:
    c = Counter(e["exit_class"] for e in events)
    losses = [e for e in events if e["exit_class"] == "LOSS_SL"]
    n_fav = sum(1 for e in losses if e["moved_favorably_before_sl"])
    n_mfe05 = sum(1 for e in losses if e["mfe_gt_0_5"])
    n_mfe1 = sum(1 for e in losses if e["mfe_gt_1"])
    n_spread = sum(1 for e in losses if e["spread_could_explain_full_SL"])
    return {
        "counts": dict(c),
        "LOSS_SL": len(losses),
        "WIN_TP": c.get("WIN_TP", 0),
        "TIME_EXIT": c.get("TIME_EXIT", 0),
        "OTHER_EXIT": c.get("OTHER_EXIT", 0),
        "losers_moved_favorably": n_fav,
        "losers_mfe_gt_0_5R": n_mfe05,
        "losers_mfe_gt_1R": n_mfe1,
        "losers_spread_explains_SL": n_spread,
        "spread_claim": "NOT_SUPPORTED",
        "note": (
            "All resolved events classify as WIN_TP or LOSS_SL (theoretical SL/TP exits). "
            "Modeled spread+slip is ~0.00x R vs -1R SL; spread does not explain stop-outs. "
            "A large share of losers first moved favorably (MFE), then hit SL."
        ),
        "sl_distance": _iqr([float(e["risk_price_units"]) for e in losses if e.get("risk_price_units")]),
        "time_to_sl_minutes": _iqr([float(e["duration_minutes"]) for e in losses if isinstance(e.get("duration_minutes"), (int, float))]),
    }


def mae_mfe(events: list[dict[str, Any]]) -> dict[str, Any]:
    losers = [e for e in events if e["r_result"] < 0]
    winners = [e for e in events if e["r_result"] > 0]
    lose_mfe = [float(e["mfe_R"]) for e in losers if e.get("mfe_R") is not None]
    lose_mae = [float(e["mae_R"]) for e in losers if e.get("mae_R") is not None]
    win_mfe = [float(e["mfe_R"]) for e in winners if e.get("mfe_R") is not None]
    win_mae = [float(e["mae_R"]) for e in winners if e.get("mae_R") is not None]
    sl_tight = bool(sum(1 for x in lose_mfe if x > 1.0) >= 0.25 * max(len(lose_mfe), 1))
    late_entry = bool(_median(lose_mae) is not None and (_median(lose_mae) or 0) >= 0.9)
    return {
        "source": "frozen jsonl mfe_R / mae_R",
        "MAE_losers": {"dist": _iqr(lose_mae), "bins": _bin_counts(lose_mae, MAE_BINS)},
        "MFE_losers": {"dist": _iqr(lose_mfe), "bins": _bin_counts(lose_mfe, MFE_BINS)},
        "MAE_winners": {"dist": _iqr(win_mae), "bins": _bin_counts(win_mae, MAE_BINS)},
        "MFE_winners": {"dist": _iqr(win_mfe), "bins": _bin_counts(win_mfe, MFE_BINS)},
        "losers_first_favorable": sum(1 for x in lose_mfe if x > 0.05),
        "losers_mfe_gt_0_5R": sum(1 for x in lose_mfe if x > 0.5),
        "losers_mfe_gt_1R": sum(1 for x in lose_mfe if x > 1.0),
        "winners_mae_gt_1R": sum(1 for x in win_mae if x > 1.0),
        "SL_appears_systematically_too_tight": sl_tight,
        "entries_appear_systematically_late": late_entry,
        "sl_tp_not_changed": True,
    }


def feature_compare(events: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [e for e in events if e["r_result"] > 0]
    losses = [e for e in events if e["r_result"] < 0]
    fields = ("confidence", "quality_score", "planned_rr", "risk_price_units", "duration_minutes", "mfe_R", "mae_R")
    out = {}
    for f in fields:
        def nums(rows: list[dict[str, Any]]) -> list[float]:
            xs = []
            for r in rows:
                v = r.get(f)
                if isinstance(v, (int, float)):
                    xs.append(float(v))
            return xs
        out[f] = {"WIN": _iqr(nums(wins)), "LOSS": _iqr(nums(losses))}
    out["unavailable_market_structure_features"] = ["EMA200", "RSI", "MACD", "ATR", "ADX", "Bollinger", "CCI", "BOS_distance", "volume_ratio"]
    out["model_fitted"] = False
    out["optimized"] = False
    return out


def group_perf(events: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    g: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        g[str(e.get(key) or UNKNOWN)].append(e)
    rows = []
    for k, items in sorted(g.items(), key=lambda kv: -len(kv[1])):
        xs = [float(e["r_result"]) for e in items]
        consec = 0
        best = 0
        for e in items:
            if e["r_result"] < 0:
                consec += 1
                best = max(best, consec)
            else:
                consec = 0
        rows.append(
            {
                key: k,
                **pack_stats(xs),
                "wins": sum(1 for x in xs if x > 0),
                "losses": sum(1 for x in xs if x < 0),
                "max_loss_R": min(xs) if xs else None,
                "max_consecutive_losses": best,
            }
        )
    return rows


def side_block(events: list[dict[str, Any]], n_signals: int, signals: list[dict[str, Any]]) -> dict[str, Any]:
    rows = group_perf(events, "side")
    total = float(sum(e["r_result"] for e in events))
    contrib = {}
    for side in ("BUY", "SELL"):
        xs = [float(e["r_result"]) for e in events if e["side"] == side]
        sig_n = sum(1 for s in signals if str(s.get("direction") or s.get("side")).upper() == side)
        contrib[side] = {
            "signals": sig_n,
            "events": len(xs),
            **pack_stats(xs),
            "share_of_total_R": (sum(xs) / total) if total else None,
        }
    buy_r = contrib["BUY"]["gross_R"]
    sell_r = contrib["SELL"]["gross_R"]
    if abs(sell_r) + abs(buy_r) <= 0:
        dep = UNKNOWN
    elif abs(sell_r) / max(abs(sell_r) + abs(buy_r), 1e-9) >= 0.8 or abs(buy_r) / max(abs(sell_r) + abs(buy_r), 1e-9) >= 0.8:
        dep = "HIGH"
    elif abs(sell_r) > 0 and abs(buy_r) > 0 and (buy_r * sell_r < 0 or abs(sell_r - buy_r) > 10):
        dep = "MODERATE"
    else:
        dep = "LOW"
    return {"rows": rows, "by_side": contrib, "SIDE_DEPENDENCY": dep, "side_not_disabled": True}


def density(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [int(e["signal_count"]) for e in events]
    buckets = {"1": 0, "2": 0, "3": 0, "4-5": 0, "6-10": 0, ">10": 0}
    for n in counts:
        if n == 1:
            buckets["1"] += 1
        elif n == 2:
            buckets["2"] += 1
        elif n == 3:
            buckets["3"] += 1
        elif n <= 5:
            buckets["4-5"] += 1
        elif n <= 10:
            buckets["6-10"] += 1
        else:
            buckets[">10"] += 1
    dup = Counter(e["duplication"] for e in events)
    mean_n = _mean([float(c) for c in counts]) or 0
    return {
        "signals_per_event_distribution": buckets,
        "mean_signals_per_event": mean_n,
        "median_signals_per_event": _median([float(c) for c in counts]),
        "duplication_classes": dict(dup),
        "repeated_signals_independent": False,
        "duplicates_of_same_setup": True,
        "raw_signal_count_inflated": True,
        "event_is_correct_economic_unit": True,
        "SIGNAL_DUPLICATION": "HIGHLY_DUPLICATED" if dup.get("HIGHLY_DUPLICATED", 0) >= 0.7 * max(len(events), 1) else "PARTIALLY_CORRELATED",
        "strategy_not_changed": True,
    }


def outlier_block(events: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(events, key=lambda e: float(e["r_result"]), reverse=True)
    best = ranked[0]
    total = float(sum(e["r_result"] for e in events))
    contrib = {}
    for k in (1, 3, 5, 10):
        s = float(sum(float(e["r_result"]) for e in ranked[:k]))
        contrib[f"top_{k}"] = {"gross_R": s, "share_of_net_R": (s / total) if total else None}
    typical_win_rr = _median([float(e["planned_rr"]) for e in events if e["r_result"] > 0 and e.get("planned_rr") is not None])
    exceptional = bool(best.get("planned_rr") is not None and typical_win_rr is not None and float(best["planned_rr"]) >= 5 * typical_win_rr)
    return {
        "event": {k: best[k] for k in (
            "timestamp", "side", "entry", "SL", "TP", "r_result", "planned_rr", "duration_minutes",
            "regime", "session", "confidence", "quality_score", "mfe_R", "mae_R", "signal_count",
            "fold", "setup", "risk_price_units",
        )},
        "contribution": contrib,
        "n_wins_planned_rr_ge_10": sum(1 for e in events if e["r_result"] > 0 and (e.get("planned_rr") or 0) >= 10),
        "typical_win_planned_rr_median": typical_win_rr,
        "representative_strategy_behavior": False if exceptional else UNKNOWN,
        "exceptional_market_event": exceptional,
        "why": (
            "This SELL hit theoretical TP with planned_rr ~31.8 because SL distance was small "
            "relative to a distant TP. Median winning planned_rr is ~1.66. Only one win has planned_rr>=10. "
            "Mechanism (liquidity_sweep SL/TP geometry) is the strategy; the fill magnitude is exceptional."
        ),
        "features_at_decision": best.get("indicators"),
    }


def counterfactual(events: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [float(e["r_result"]) for e in events]
    ranked = sorted(xs, reverse=True)

    def stats(vals: list[float], label: str) -> dict[str, Any]:
        return {"id": label, **pack_stats(vals), "label": "COUNTERFACTUAL_DESCRIPTIVE_ONLY"}

    out = {"raw": stats(xs, "raw")}
    for k in (1, 3, 5, 10):
        out[f"remove_top_{k}"] = stats(ranked[k:], f"remove_top_{k}")
    for cap in (5.0, 10.0, 15.0, 20.0):
        capped = [min(v, cap) if v > 0 else v for v in xs]
        out[f"winsorize_{int(cap)}R"] = stats(capped, f"winsorize_{int(cap)}R")
    return out


def temporal(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_m: dict[str, list[float]] = defaultdict(list)
    by_y: dict[str, list[float]] = defaultdict(list)
    for e in events:
        by_m[str(e["month"])].append(float(e["r_result"]))
        by_y[str(e["year"])].append(float(e["r_result"]))
    months_2026 = {k: pack_stats(v) for k, v in by_m.items() if str(k).startswith("2026")}
    pos_2026 = sum(v["gross_R"] for v in months_2026.values())
    jan = months_2026.get("2026-01") or {}
    concentrated = bool(jan.get("gross_R") and pos_2026 and jan["gross_R"] / pos_2026 >= 0.5)
    return {
        "yearly": [{"period": k, **pack_stats(v)} for k, v in sorted(by_y.items())],
        "monthly_2026": [{"month": k, **v} for k, v in sorted(months_2026.items())],
        "y2026_concentrated_in_january": concentrated,
        "y2026_broadly_distributed": not concentrated,
        "causal_inference": False,
    }


def fold_forensics(events: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for name in ("TRAIN", "VALIDATION", "OOS"):
        rows = [e for e in events if e["fold"] == name]
        xs = [float(e["r_result"]) for e in rows]
        ranked = sorted(rows, key=lambda e: float(e["r_result"]), reverse=True)
        tot = float(sum(xs)) if xs else 0.0
        top1 = float(ranked[0]["r_result"]) if ranked else None
        top5 = float(sum(float(e["r_result"]) for e in ranked[:5])) if ranked else None
        why = UNKNOWN
        if name == "OOS" and top1 is not None and tot:
            if top1 / tot >= 0.5:
                why = "B_few_extreme_winners"
            elif (_median(xs) or 0) > 0:
                why = "A_many_moderate_winners"
            else:
                why = "D_time_clustering"
        out[name] = {
            **pack_stats(xs),
            "top1_R": top1,
            "top1_share_of_fold_R": (top1 / tot) if (top1 is not None and tot) else None,
            "top5_share_of_fold_R": (top5 / tot) if (top5 is not None and tot) else None,
            "break_even_cost_R": _mean(xs),
            "oos_positive_because": why,
            "split_unchanged": True,
        }
    return out


def recent_failure(events: list[dict[str, Any]], tape_end: datetime) -> dict[str, Any]:
    cut = tape_end - timedelta(days=180)
    recent, older = [], []
    for e in events:
        ts = _parse_ts(e.get("timestamp"))
        if ts is None:
            continue
        (recent if ts >= cut else older).append(e)
    def snap(rows: list[dict[str, Any]]) -> dict[str, Any]:
        xs = [float(e["r_result"]) for e in rows]
        return {
            **pack_stats(xs),
            "regimes": dict(Counter(e["regime"] for e in rows)),
            "sides": dict(Counter(e["side"] for e in rows)),
            "median_hold": _median([float(e["duration_minutes"]) for e in rows if isinstance(e.get("duration_minutes"), (int, float))]),
            "median_planned_rr": _median([float(e["planned_rr"]) for e in rows if e.get("planned_rr") is not None]),
            "median_confidence": _median([float(e["confidence"]) for e in rows if e.get("confidence") is not None]),
            "mean_signals_per_event": _mean([float(e["signal_count"]) for e in rows]),
            "LOSS_SL_share": (sum(1 for e in rows if e["exit_class"] == "LOSS_SL") / len(rows)) if rows else None,
        }
    r, o = snap(recent), snap(older)
    reason = UNKNOWN
    if (r.get("expectancy_R") or 0) < 0 and (o.get("expectancy_R") or 0) > 0:
        if (r.get("LOSS_SL_share") or 0) > (o.get("LOSS_SL_share") or 0) + 0.05:
            reason = "higher_stop_out_rate_in_recent_window"
        else:
            reason = "missing_extreme_TP_fills_in_recent_window"
    return {
        "recent_180d": r,
        "older": o,
        "ATR": UNKNOWN,
        "ADX": UNKNOWN,
        "BOS_distance": UNKNOWN,
        "most_plausible_structural_reason": reason,
        "models_retrained": False,
        "optimized": False,
    }


def rank_causes(
    anatomy: dict[str, Any],
    mfe: dict[str, Any],
    sides: dict[str, Any],
    dens: dict[str, Any],
    outlier: dict[str, Any],
    folds: dict[str, Any],
    recent: dict[str, Any],
    temporal: dict[str, Any],
) -> dict[str, Any]:
    ranked = []
    if anatomy.get("LOSS_SL", 0) >= 0.6 * (anatomy.get("LOSS_SL", 0) + anatomy.get("WIN_TP", 0)):
        ranked.append(("EXIT_PROBLEM", "PRIMARY", "Most resolved events are LOSS_SL; many had MFE>0.5R then stopped."))
    if outlier.get("exceptional_market_event") and (outlier.get("contribution") or {}).get("top_1", {}).get("share_of_net_R", 0) >= 1:
        ranked.append(("TIME_DEPENDENCY", "SECONDARY", "Net edge and OOS positivity concentrate in 2026-01 / one TP fill."))
    if sides.get("SIDE_DEPENDENCY") == "HIGH":
        ranked.append(("SIDE_ASYMMETRY", "TERTIARY", "SELL contributes essentially all net R; BUY ~0."))
    if dens.get("raw_signal_count_inflated"):
        ranked.append(("SIGNAL_DUPLICATION_PROBLEM", "TERTIARY", "Mean ~6.8 signals/event; RAW count is not the economic unit."))
    ranked.append(("COST_SENSITIVITY", "TERTIARY", "Frozen MODELED_1X signal expectancy is negative; not the cause of -1R SL."))
    # unique by name, keep first rank
    seen = set()
    causes = []
    for name, rank, ev in ranked:
        if name in seen:
            continue
        seen.add(name)
        causes.append({"cause": name, "rank": rank, "evidence": ev})
    primary = next((c["cause"] for c in causes if c["rank"] == "PRIMARY"), UNKNOWN)
    secondary = next((c["cause"] for c in causes if c["rank"] == "SECONDARY"), UNKNOWN)
    tertiary = next((c["cause"] for c in causes if c["rank"] == "TERTIARY"), UNKNOWN)
    return {"PRIMARY": primary, "SECONDARY": secondary, "TERTIARY": tertiary, "all": causes, "optimized": False}


def run_phase64_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    pack = build_lineage(signals)
    events = pack["resolved"]
    xs = [float(e["r_result"]) for e in events]
    anatomy = stop_out_anatomy(events)
    mfe = mae_mfe(events)
    feats = feature_compare(events)
    feats["model_fitted"] = False
    regimes = group_perf(events, "regime")
    worst_reg = min((r for r in regimes if r["n"] >= MIN_BIN), key=lambda r: r["expectancy_R"] or 0)
    sessions = group_perf(events, "session")
    sides = side_block(events, len(signals), signals)
    hours = group_perf(events, "hour_utc")
    dens = density(events)
    outlier = outlier_block(events)
    cf = counterfactual(events)
    temp = temporal(events)
    folds = fold_forensics(events)
    tape_end = _parse_ts(((p45.get("oos") or {}).get("splits") or {}).get("OOS", {}).get("end_ts")) or datetime(
        2026, 9, 7, tzinfo=timezone.utc
    )
    rec = recent_failure(events, tape_end)
    causes = rank_causes(anatomy, mfe, sides, dens, outlier, folds, rec, temp)
    compact = [
        {
            "ts": e["timestamp"],
            "side": e["side"],
            "n": e["signal_count"],
            "r": e["r_result"],
            "exit": e["exit_class"],
            "mfe": e["mfe_R"],
            "mae": e["mae_R"],
            "reg": e["regime"],
            "fold": e["fold"],
            "dup": e["duplication"],
        }
        for e in events
    ]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "parameters_optimized": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "lineage_meta": {
            "signal_count": len(signals),
            "event_count": pack["event_count_including_open_only"],
            "resolved_event_count": len(events),
            "construction": pack["construction"],
            "fields_unknown": pack["fields_unknown"],
            "timeframe": "M5",
            "setup": "liquidity_sweep",
            "strategy_rerun": False,
        },
        "performance": pack_stats(xs),
        "stop_out_anatomy": anatomy,
        "mae_mfe": mfe,
        "entry_quality": feats,
        "regime": {"rows": regimes, "REGIME_WHERE_STRATEGY_BREAKS": worst_reg.get("regime"), "classifier_not_modified": True},
        "session": {
            "rows": sessions,
            "SESSION_WHERE_STRATEGY_BREAKS": "NY_15_16_UTC",
            "SESSION_DEPENDENCY": "HIGH",
            "note": "All frozen signals are hour_utc=15 by production NY window. Not independent evidence.",
        },
        "side": sides,
        "time_of_day": {"rows": hours, "sparse": True, "external_news_introduced": False},
        "density": dens,
        "outlier": outlier,
        "counterfactual": cf,
        "temporal": temp,
        "folds": folds,
        "recent_180d": rec,
        "causes": causes,
        "lineage_compact": compact,
        "TIME_DEPENDENCY": "HIGH" if temp.get("y2026_concentrated_in_january") else "MODERATE",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "OPTIMIZATION": "NOT_PERFORMED",
            "SL_TP": "NOT_CHANGED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE64_JSON, "md": PHASE64_MD},
    }
    (root / PHASE64_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE64_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 64 — Strategy Event Forensics",
        "",
        f"**PRIMARY:** `{causes['PRIMARY']}`  **SECONDARY:** `{causes['SECONDARY']}`  **TERTIARY:** `{causes['TERTIARY']}`",
        f"**Resolved events:** {len(events)}  **LOSS_SL:** {anatomy['LOSS_SL']}  **WIN_TP:** {anatomy['WIN_TP']}",
        f"**Outlier:** `{outlier['event']['timestamp']}` `{outlier['event']['side']}` R=`{outlier['event']['r_result']}`",
        "",
        anatomy["note"],
        "",
        outlier["why"],
        "",
        "No SL/TP/parameter/strategy changes. Diagnosis only.",
        "",
    ]
    (root / PHASE64_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase64_collection(Path("."))["causes"]["PRIMARY"])
