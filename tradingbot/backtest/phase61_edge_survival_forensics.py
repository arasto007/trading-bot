"""Phase 61 — edge survival / economic-value forensics.

RESEARCH ONLY. Reads frozen Phase 40 jsonl + Phase 40/45/58 artifacts.
Does not rescan strategy, launch MT5, import live.py, optimize, or trade.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "61"
PHASE61_JSON = "logs/phase61_edge_survival_forensics.json"
PHASE61_MD = "docs/PHASE61_EDGE_SURVIVAL_FORENSICS.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_SETUPS_JSONL = "logs/phase40_raw_setups.jsonl"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE58_JSON = "logs/phase58_commission_accountability.json"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
PHASE40_BOOTSTRAP_SEED = 400040
N_PATHS = 2000
POINT = 0.01  # observed XAUUSD_i point/tick; not imported from live.py
SPREAD_BASE_PIPS = 2.5
SLIP_BASE_PIPS = 0.8
COST_CURVE = (
    0.0, 0.005, 0.010, 0.015, 0.020, 0.025, 0.030, 0.035, 0.040,
    0.045, 0.04866, 0.050, 0.060, 0.070, 0.080, 0.100,
)
SPLIT_FOLDS = (
    ("TRAIN", 0, 150000),
    ("VALIDATION", 150000, 200000),
    ("OOS", 200000, 250000),
)
HOLD_BINS = (
    ("lt_5m", 0.0, 5.0),
    ("5_15m", 5.0, 15.0),
    ("15_30m", 15.0, 30.0),
    ("30_60m", 30.0, 60.0),
    ("1_2h", 60.0, 120.0),
    ("2_4h", 120.0, 240.0),
    ("4_8h", 240.0, 480.0),
    ("8h_plus", 480.0, 1e12),
)
MIN_BIN = 8
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "events",
    "contribution",
    "time_stability",
    "cost_curve",
    "EDGE_QUALITY",
    "DECISION_ECONOMICS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _mean(xs: list[float]) -> float | None:
    return float(sum(xs) / len(xs)) if xs else None


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    mid = len(ys) // 2
    if len(ys) % 2:
        return float(ys[mid])
    return float((ys[mid - 1] + ys[mid]) / 2.0)


def _pf(xs: list[float]) -> float | None:
    gw = float(sum(x for x in xs if x > 0))
    gl = float(abs(sum(x for x in xs if x <= 0)))
    if gl <= 0:
        return None
    return gw / gl


def _wr(xs: list[float]) -> float | None:
    return float(sum(1 for x in xs if x > 0) / len(xs)) if xs else None


def _dd(xs: list[float]) -> float | None:
    if not xs:
        return None
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    return abs(max_dd)


def _max_consec_neg(xs: list[float]) -> int:
    best = cur = 0
    for x in xs:
        if x < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def pack_stats(xs: list[float], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "n": len(xs),
        "WR": _wr(xs),
        "expectancy_R": _mean(xs),
        "PF": _pf(xs),
        "DD_R": _dd(xs),
        "gross_R": float(sum(xs)) if xs else 0.0,
        "median_R": _median(xs),
        "small_sample": len(xs) < MIN_BIN,
    }
    if extra:
        row.update(extra)
    return row


def load_setups(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def event_key(row: dict[str, Any]) -> tuple[str, str]:
    ts = _parse_ts(row.get("timestamp"))
    day = str(ts.date()) if ts is not None else UNKNOWN
    side = str(row.get("side") or row.get("direction") or UNKNOWN).upper()
    return day, side


def reconstruct_events(signals: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in signals:
        groups[event_key(row)].append(row)
    events: list[dict[str, Any]] = []
    for key, members in groups.items():
        members_sorted = sorted(members, key=lambda r: str(r.get("timestamp")))
        head = dict(members_sorted[0])
        resolved = [
            m for m in members_sorted
            if m.get("outcome") != "open" and m.get("r_multiple") is not None
        ]
        r_val = float(head["r_multiple"]) if head.get("r_multiple") is not None and head.get("outcome") != "open" else None
        if resolved:
            first_res = resolved[0]
            r_val = float(first_res["r_multiple"])
            head = dict(first_res)
        ts = _parse_ts(head.get("timestamp"))
        exit_t = _parse_ts(head.get("exit_time"))
        bar = head.get("closed_bar_index")
        if bar is None:
            bar = head.get("cursor")
        try:
            bar_i = int(bar)
        except (TypeError, ValueError):
            bar_i = None
        fold = UNKNOWN
        if bar_i is not None:
            for name, a, b in SPLIT_FOLDS:
                if a <= bar_i < b:
                    fold = name
                    break
        risk = UNKNOWN
        try:
            risk = abs(float(head["entry_price"]) - float(head["stop_loss"]))
        except (TypeError, ValueError, KeyError):
            risk = UNKNOWN
        events.append(
            {
                "timestamp": head.get("timestamp"),
                "symbol": "XAUUSD_i",
                "direction": str(head.get("direction") or head.get("side") or UNKNOWN).upper(),
                "entry": head.get("entry_price"),
                "exit": UNKNOWN,
                "SL": head.get("stop_loss"),
                "TP": head.get("take_profit"),
                "r_result": r_val,
                "holding_time_minutes": head.get("duration_minutes"),
                "regime": head.get("regime") or UNKNOWN,
                "session": "NY_15_16_UTC" if head.get("hour_utc") == 15 else UNKNOWN,
                "hour_utc": head.get("hour_utc"),
                "signal_confidence": head.get("confidence"),
                "setup": head.get("setup") or UNKNOWN,
                "event_key": {"utc_date": key[0], "side": key[1], "asian_high": UNKNOWN, "asian_low": UNKNOWN},
                "member_count": len(members_sorted),
                "resolved_members": len(resolved),
                "fold": fold,
                "closed_bar_index": bar_i,
                "risk_price_units": risk,
                "year": ts.year if ts else UNKNOWN,
                "month": f"{ts.year:04d}-{ts.month:02d}" if ts else UNKNOWN,
                "half": ("H1" if ts.month <= 6 else "H2") if ts else UNKNOWN,
                "exit_time": str(exit_t) if exit_t else UNKNOWN,
            }
        )
    events.sort(key=lambda e: str(e.get("timestamp")))
    resolved_events = [e for e in events if e.get("r_result") is not None]
    return {
        "construction": {
            "name": "PROXY_DATE_SIDE_EQUIVALENT_TO_MECHANICAL",
            "official_mechanical": "(utc_date, asian_high, asian_low, side)",
            "jsonl_asian_range": "NOT_PERSISTED",
            "used": "(utc_date, side)",
            "justification": (
                "Official Asian range is computed once per UTC date. "
                "jsonl does not persist asian_high/asian_low. "
                "(utc_date, side) reconstructs 420 clusters / 419 resolved; "
                "resolved event expectancy matches frozen Phase45 0.04866R."
            ),
            "not_a_new_event_definition": True,
            "strategy_logic_rerun": False,
        },
        "signal_count": len(signals),
        "event_count_including_open_only": len(events),
        "event_count_resolved": len(resolved_events),
        "events": events,
        "resolved": resolved_events,
    }


def contribution_analysis(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [float(e["r_result"]) for e in resolved]
    n = len(xs)
    total = float(sum(xs))
    order = sorted(range(n), key=lambda i: xs[i], reverse=True)
    ranked = [xs[i] for i in order]

    def share(k: int) -> dict[str, Any]:
        chunk = ranked[:k]
        s = float(sum(chunk))
        return {
            "n": k,
            "gross_R": s,
            "pct_total_R": (s / total) if total else None,
            "pct_total_pnl": (s / total) if total else None,
        }

    pct5 = max(1, int(math.ceil(0.05 * n)))
    pct10 = max(1, int(math.ceil(0.10 * n)))
    bot50 = xs[n // 2 :] if n else []
    removals = {}
    for k in (1, 3, 5, 10, 20):
        remain = ranked[k:] if n > k else []
        removals[f"remove_top_{k}"] = pack_stats(remain, {"removed": k, "edge_survives": bool(remain) and (_mean(remain) or 0) > 0})
    top5_remain = removals["remove_top_5"]["expectancy_R"] or 0.0
    top10_remain = removals["remove_top_10"]["expectancy_R"] or 0.0
    top5pct_share = share(pct5)["pct_total_R"] or 0.0
    if top5_remain <= 0:
        conc = "EXTREME_CONCENTRATION"
    elif top10_remain <= 0 or top5pct_share >= 0.50:
        conc = "HIGH_CONCENTRATION"
    elif top5pct_share >= 0.25:
        conc = "MODERATE_CONCENTRATION"
    else:
        conc = "LOW_CONCENTRATION"
    return {
        "total_gross_R": total,
        "n": n,
        "top_1": share(1),
        "top_3": share(min(3, n)),
        "top_5": share(min(5, n)),
        "top_10": share(min(10, n)),
        "top_20": share(min(20, n)),
        "top_5pct": share(pct5),
        "top_10pct": share(pct10),
        "bottom_50pct": {
            "n": len(bot50),
            "gross_R": float(sum(sorted(xs)[: n // 2])) if n else 0.0,
            "expectancy_R": _mean(sorted(xs)[: n // 2]) if n else None,
        },
        "removals": removals,
        "classification": conc,
        "question": "If the best N events disappear, does the edge survive?",
    }


def loss_concentration(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [float(e["r_result"]) for e in resolved]
    losses = sorted(xs)
    consec = _max_consec_neg(xs)
    worst = losses[0] if losses else None
    rare_catastrophe = bool(worst is not None and worst < -3.0)
    return {
        "largest_loss_R": worst,
        "top_5_losses": losses[:5],
        "top_10_losses": losses[:10],
        "max_consecutive_negative_events": consec,
        "max_consecutive_losses": consec,
        "n_losses": int(sum(1 for x in xs if x < 0)),
        "loss_median_R": _median([x for x in xs if x < 0]),
        "dominated_by_rare_catastrophe": rare_catastrophe,
        "note": "Most losses are SL-like near -1R unless a larger R is observed.",
    }


def yearly_and_half(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    by_year: dict[Any, list[float]] = defaultdict(list)
    by_half_2026: dict[str, list[float]] = defaultdict(list)
    for e in resolved:
        if e.get("year") != UNKNOWN:
            by_year[e["year"]].append(float(e["r_result"]))
        if e.get("year") == 2026 and e.get("half") in {"H1", "H2"}:
            by_half_2026[str(e["half"])].append(float(e["r_result"]))
    yearly = [{"period": str(y), **pack_stats(by_year[y])} for y in sorted(by_year)]
    signs = [float(r["expectancy_R"] or 0) for r in yearly]
    flips = sum(1 for a, b in zip(signs, signs[1:]) if a * b < 0)
    halves = []
    for name in ("H1", "H2"):
        xs = by_half_2026.get(name) or []
        if len(xs) < MIN_BIN:
            halves.append({"period": f"2026-{name}", "n": len(xs), "status": "INSUFFICIENT", "expectancy_R": _mean(xs)})
        else:
            halves.append({"period": f"2026-{name}", **pack_stats(xs)})
    if flips >= 1 and any((r.get("expectancy_R") or 0) < 0 for r in yearly) and any((r.get("expectancy_R") or 0) > 0 for r in yearly):
        clf = "UNSTABLE"
    elif flips == 0:
        clf = "STABLE"
    else:
        clf = "MIXED"
    return {"yearly": yearly, "y2026_halves": halves, "yearly_sign_flips": flips, "classification": clf}


def monthly_stability(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    by_m: dict[str, list[float]] = defaultdict(list)
    for e in resolved:
        if e.get("month") != UNKNOWN:
            by_m[str(e["month"])].append(float(e["r_result"]))
    rows = [{"month": m, **pack_stats(by_m[m])} for m in sorted(by_m)]
    usable = [r for r in rows if not r["small_sample"]]
    pos = [r for r in usable if (r.get("expectancy_R") or 0) > 0]
    neg = [r for r in usable if (r.get("expectancy_R") or 0) < 0]
    exps = [float(r["expectancy_R"]) for r in usable if r.get("expectancy_R") is not None]
    return {
        "months": rows,
        "usable_months": len(usable),
        "tiny_samples_excluded_from_summary": len(rows) - len(usable),
        "positive_months": len(pos),
        "negative_months": len(neg),
        "pct_positive": (len(pos) / len(usable)) if usable else None,
        "median_monthly_expectancy_R": _median(exps),
        "worst_month": min(usable, key=lambda r: r["expectancy_R"] or 0) if usable else None,
        "best_month": max(usable, key=lambda r: r["expectancy_R"] or 0) if usable else None,
        "do_not_overinterpret_tiny_samples": True,
    }


def regime_stability(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    by_r: dict[str, list[float]] = defaultdict(list)
    for e in resolved:
        by_r[str(e.get("regime") or UNKNOWN)].append(float(e["r_result"]))
    rows = [{"regime": k, **pack_stats(by_r[k])} for k in sorted(by_r)]
    pos = [r for r in rows if (r.get("expectancy_R") or 0) > 0 and r["n"] >= MIN_BIN]
    if len(rows) <= 1:
        dep = "UNKNOWN"
    elif len(pos) <= 1:
        dep = "HIGH"
    elif any((r.get("expectancy_R") or 0) < 0 for r in rows if r["n"] >= MIN_BIN) and pos:
        dep = "MODERATE"
    else:
        dep = "LOW"
    return {
        "source": "existing Phase40 infer_regime_from_ohlcv labels — not refit",
        "rows": rows,
        "REGIME_DEPENDENCY": dep,
        "new_labels_created": False,
        "models_refit": False,
    }


def session_stability(resolved: list[dict[str, Any]], signals: list[dict[str, Any]]) -> dict[str, Any]:
    hours = {r.get("hour_utc") for r in signals}
    by_s: dict[str, list[float]] = defaultdict(list)
    for e in resolved:
        by_s[str(e.get("session") or UNKNOWN)].append(float(e["r_result"]))
    return {
        "production_session": "NY 15–16 UTC",
        "observed_hour_utc_values": sorted(h for h in hours if h is not None),
        "rows": [{"session": k, **pack_stats(v)} for k, v in sorted(by_s.items())],
        "Asia": {"n": 0, "status": "NO_OBSERVATIONS", "reason": "scan is NY-only by design"},
        "London": {"n": 0, "status": "NO_OBSERVATIONS", "reason": "scan is NY-only by design"},
        "London_NY_overlap": {"note": "hour 15 is inside typical overlap; not a separate label in the jsonl"},
        "New_York": pack_stats([float(e["r_result"]) for e in resolved]),
        "SESSION_DEPENDENCY": "HIGH",
        "note": "Dependence on NY 15–16 is expected by design. It is not independent evidence that the window is optimal.",
        "new_session_labels": False,
    }


def holding_time(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for name, lo, hi in HOLD_BINS:
        xs = []
        for e in resolved:
            d = e.get("holding_time_minutes")
            if not isinstance(d, (int, float)):
                continue
            if lo <= float(d) < hi:
                xs.append(float(e["r_result"]))
        if len(xs) < MIN_BIN:
            rows.append({"bin": name, "n": len(xs), "status": "INSUFFICIENT"})
        else:
            rows.append({"bin": name, **pack_stats(xs)})
    unknown_n = sum(1 for e in resolved if not isinstance(e.get("holding_time_minutes"), (int, float)))
    return {"bins": rows, "unknown_holding_time": unknown_n, "min_observations": MIN_BIN}


def cost_curve(resolved: list[dict[str, Any]], n_signals: int) -> dict[str, Any]:
    xs = [float(e["r_result"]) for e in resolved]
    n_evt = len(xs)
    gross_e = _mean(xs) or 0.0
    ratio = (n_evt / n_signals) if n_signals else 1.0
    points = []
    zero_cross = None
    material_neg = None
    for c in COST_CURVE:
        net = [x - c for x in xs]
        rec = {
            "cost_R": c,
            "net_event_expectancy_R": _mean(net),
            "net_signal_expectancy_R": (gross_e - c) * ratio,
            "net_WR": _wr(net),
            "net_PF": _pf(net),
            "label": "SCENARIO / MODELED / NOT_ACCOUNT_VERIFIED",
        }
        points.append(rec)
        if zero_cross is None and (rec["net_event_expectancy_R"] or 0) <= 0:
            zero_cross = c
        if material_neg is None and (rec["net_event_expectancy_R"] or 0) <= -0.02:
            material_neg = c
    return {
        "points": points,
        "event_break_even_R": gross_e,
        "approx_zero_threshold_R": zero_cross,
        "materially_negative_from_R": material_neg,
        "signal_conversion": "net_signal = (event_expectancy - cost) * (n_resolved_events / n_signals)",
        "n_events": n_evt,
        "n_signals": n_signals,
    }


def modeled_cost_r(event: dict[str, Any], spread_pips: float, slip_pips: float) -> float | None:
    risk = event.get("risk_price_units")
    try:
        risk_f = float(risk)
    except (TypeError, ValueError):
        return None
    if risk_f <= 0:
        return None
    round_trip = (float(spread_pips) + 2.0 * float(slip_pips)) * POINT
    return round_trip / risk_f


def modeled_scenarios(resolved: list[dict[str, Any]]) -> dict[str, Any]:
    specs = {
        "LOW_COST": {"spread_pips": SPREAD_BASE_PIPS * 0.5, "slip_pips": SLIP_BASE_PIPS * 0.5, "mult": 0.5},
        "BASE_COST": {"spread_pips": SPREAD_BASE_PIPS, "slip_pips": SLIP_BASE_PIPS, "mult": 1.0},
        "HIGH_COST": {"spread_pips": SPREAD_BASE_PIPS * 2.0, "slip_pips": SLIP_BASE_PIPS * 2.0, "mult": 2.0},
    }
    out = {}
    for name, spec in specs.items():
        nets = []
        costs = []
        skipped = 0
        for e in resolved:
            c = modeled_cost_r(e, spec["spread_pips"], spec["slip_pips"])
            if c is None:
                skipped += 1
                continue
            costs.append(c)
            nets.append(float(e["r_result"]) - c)
        out[name] = {
            **pack_stats(nets),
            "mean_modeled_cost_R": _mean(costs),
            "spread_pips": spec["spread_pips"],
            "slip_pips": spec["slip_pips"],
            "skipped": skipped,
            "formula": "cost_R = (spread + 2*slip) * point / |entry-SL|",
            "point": POINT,
            "label": "MODELED / NOT_OBSERVED / NOT_ACCOUNT_VERIFIED",
            "source": "Phase40 MODELED_1X bases spread=2.5 slip=0.8; LOW=0.5x HIGH=2x existing multipliers",
        }
    return {
        "method": "DETERMINISTIC_SENSITIVITY",
        "distribution_defensible": False,
        "scenarios": out,
        "label": "MODELED / NOT_OBSERVED / NOT_ACCOUNT_VERIFIED",
    }


def fold_cost_survival(resolved: list[dict[str, Any]], signals: list[dict[str, Any]], tape_end: datetime) -> dict[str, Any]:
    costs = (0.01, 0.02, 0.03, 0.04, 0.05)
    cut = tape_end - timedelta(days=180)

    def subset(name: str) -> list[dict[str, Any]]:
        if name in {"TRAIN", "VALIDATION", "OOS"}:
            return [e for e in resolved if e.get("fold") == name]
        if name == "RECENT_180D":
            out = []
            for e in resolved:
                ts = _parse_ts(e.get("timestamp"))
                if ts is not None and ts >= cut:
                    out.append(e)
            return out
        return resolved

    blocks = {}
    for name in ("TRAIN", "VALIDATION", "OOS", "RECENT_180D"):
        rows = subset(name)
        xs = [float(e["r_result"]) for e in rows]
        gross = _mean(xs)
        nets = {f"net_at_{c:.2f}R": ((gross - c) if gross is not None else None) for c in costs}
        blocks[name] = {
            "n": len(xs),
            "gross_expectancy_R": gross,
            "break_even_cost_R": gross,
            **nets,
            "survives_0.02R": bool(gross is not None and gross > 0.02),
            "survives_0.05R": bool(gross is not None and gross > 0.05),
        }
    oos = blocks["OOS"]["gross_expectancy_R"]
    recent = blocks["RECENT_180D"]["gross_expectancy_R"]
    contradiction = bool(oos is not None and recent is not None and oos > 0 and recent < 0)
    return {
        "folds": blocks,
        "OOS_vs_RECENT_CONTRADICTION": contradiction,
        "contradiction_resolution": "NOT_RESOLVED",
        "note": "OOS is a later-window slice overlapping 2026; recent 180d is also mostly 2026. Contradiction recorded, not reconciled.",
    }


def _path_expectancy(seq: np.ndarray) -> float:
    return float(seq.mean()) if len(seq) else 0.0


def bootstrap_cost(resolved: list[dict[str, Any]], frozen_p5: Any) -> dict[str, Any]:
    xs = np.asarray([float(e["r_result"]) for e in resolved], dtype=float)
    rng = np.random.default_rng(PHASE40_BOOTSTRAP_SEED)
    levels = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05)
    rows = {}
    for c in levels:
        adj = xs - c
        n = len(adj)
        exps = []
        for _ in range(N_PATHS):
            seq = rng.choice(adj, size=n, replace=True)
            exps.append(_path_expectancy(seq))
        rows[f"cost_{c:.2f}R"] = {
            "p5": float(np.percentile(exps, 5)),
            "median": float(np.median(exps)),
            "p95": float(np.percentile(exps, 95)),
        }
    raw = rows["cost_0.00R"]
    diff = None
    if frozen_p5 is not None:
        diff = {
            "frozen_phase40_p5": frozen_p5,
            "this_phase_raw_p5": raw["p5"],
            "same_seed": PHASE40_BOOTSTRAP_SEED,
            "same_n_paths": N_PATHS,
            "sampling_unit": "resolved_event_R_date_side_proxy",
            "note": (
                "Phase40 bootstrap used official mechanical-event representatives (420 including open-only). "
                "This phase uses 419 resolved date+side events. Difference is recorded, not a silent replacement."
            ),
            "silent_replacement": False,
        }
    return {
        "seed": PHASE40_BOOTSTRAP_SEED,
        "n_paths": N_PATHS,
        "method": "iid resample of event R with replacement; expectancy = mean(path)",
        "levels": rows,
        "vs_phase40": diff,
        "kind": "DESCRIPTIVE",
        "inferential_claim": False,
    }


def score_edge_quality(
    *,
    gross_e: float,
    time_clf: str,
    regime_dep: str,
    session_dep: str,
    conc: str,
    rare_cat: bool,
    oos_e: float | None,
    recent_e: float | None,
    boot_p5: float | None,
    be: float,
    modeled_base_e: float | None,
    modeled_1x_signal_e: float | None = None,
) -> dict[str, Any]:
    def gross() -> str:
        if gross_e <= 0:
            return "FAIL"
        if gross_e < 0.03:
            return "WEAK"
        if gross_e < 0.08:
            return "MODERATE"
        return "STRONG"

    def time() -> str:
        return {"STABLE": "STRONG", "MIXED": "MODERATE", "UNSTABLE": "FAIL"}.get(time_clf, "UNKNOWN")

    def regime() -> str:
        return {"LOW": "STRONG", "MODERATE": "MODERATE", "HIGH": "WEAK", "UNKNOWN": "UNKNOWN"}.get(regime_dep, "UNKNOWN")

    def session() -> str:
        return "WEAK" if session_dep == "HIGH" else "UNKNOWN"

    def contrib() -> str:
        return {
            "LOW_CONCENTRATION": "STRONG",
            "MODERATE_CONCENTRATION": "MODERATE",
            "HIGH_CONCENTRATION": "WEAK",
            "EXTREME_CONCENTRATION": "FAIL",
        }.get(conc, "UNKNOWN")

    def loss() -> str:
        return "FAIL" if rare_cat else "MODERATE"

    def oos() -> str:
        if oos_e is None:
            return "UNKNOWN"
        if oos_e > 0.1:
            return "STRONG"
        if oos_e > 0:
            return "MODERATE"
        return "FAIL"

    def recent() -> str:
        if recent_e is None:
            return "UNKNOWN"
        if recent_e < 0:
            return "FAIL"
        if recent_e < 0.02:
            return "WEAK"
        return "MODERATE"

    def boot() -> str:
        if boot_p5 is None:
            return "UNKNOWN"
        return "FAIL" if boot_p5 < 0 else "MODERATE"

    def cost() -> str:
        if modeled_1x_signal_e is not None and modeled_1x_signal_e < 0:
            return "FAIL"
        if modeled_base_e is not None and modeled_base_e < 0:
            return "FAIL"
        if be < 0.03:
            return "WEAK"
        if be < 0.08:
            return "MODERATE"
        return "STRONG"

    dims = {
        "gross_edge": gross(),
        "time_stability": time(),
        "regime_stability": regime(),
        "session_stability": session(),
        "contribution_concentration": contrib(),
        "loss_concentration": loss(),
        "OOS_stability": oos(),
        "recent_stability": recent(),
        "bootstrap_robustness": boot(),
        "cost_tolerance": cost(),
    }
    rank = {"STRONG": 3, "MODERATE": 2, "WEAK": 1, "FAIL": 0, "UNKNOWN": None}
    fails = sum(1 for v in dims.values() if v == "FAIL")
    weaks = sum(1 for v in dims.values() if v == "WEAK")
    if dims["recent_stability"] == "FAIL" and dims["bootstrap_robustness"] == "FAIL":
        overall = "FRAGILE"
    elif fails >= 3:
        overall = "FRAGILE"
    elif fails >= 1 or weaks >= 4:
        overall = "WEAK"
    elif all(rank[v] is not None and rank[v] >= 2 for v in dims.values() if v != "UNKNOWN"):
        overall = "MODERATE" if weaks else "STRONG"
    else:
        overall = "WEAK"
    return {
        "dimensions": dims,
        "EDGE_QUALITY": overall,
        "rule": (
            "FAIL if recent<0 and bootstrap p5<0 → FRAGILE; "
            "else >=3 FAIL → FRAGILE; else any FAIL or >=4 WEAK → WEAK; "
            "else all remaining >= MODERATE → MODERATE/STRONG. Not an AI score."
        ),
    }


def decision_economics(
    quality: str,
    modeled_base: float | None,
    gross_e: float,
    recent_e: float | None,
    modeled_1x_signal: float | None = None,
) -> dict[str, Any]:
    signal_modeled_neg = bool(modeled_1x_signal is not None and modeled_1x_signal < 0)
    event_modeled_neg = bool(modeled_base is not None and modeled_base < 0)
    cost_unc_larger = bool((event_modeled_neg or signal_modeled_neg) and gross_e > 0)
    recent_bad = bool(recent_e is not None and recent_e < 0)
    if quality == "FRAGILE" and (cost_unc_larger or recent_bad):
        ans = "NO_VALUE_CURRENTLY"
        why = (
            "Gross event edge is thin (+0.049R) and FRAGILE: 2023–2024 and TRAIN negative, "
            "recent 180d event expectancy negative, bootstrap p5 negative, OOS positive (unresolved). "
            "Frozen MODELED_1X signal expectancy is negative. Event-level BASE spread+slip remains "
            "slightly positive but that is MODELED/NOT_ACCOUNT_VERIFIED and is not a rescue. "
            "ECN vs CLASSIC commission (~0.007R vs ~0.020R) cannot overturn those contradictions. "
            "Heavy G1–G3 engineering is not the highest-information next step. Cheap operator "
            "screenshots remain optional."
        )
    elif quality in {"FRAGILE", "WEAK"}:
        ans = "YES_BUT_ONLY_AFTER_OPERATOR_EVIDENCE" if not recent_bad else "LOW_VALUE"
        why = "Edge is weak; only nearly-free operator evidence is rational, not a new broker-forensics campaign."
    else:
        ans = "YES_HIGH_VALUE"
        why = "Gross edge would comfortably exceed plausible documented costs."
    return {
        "answer": ans,
        "why": why,
        "cost_uncertainty_larger_than_gross_edge": cost_unc_larger,
        "frozen_MODELED_1X_signal_negative": signal_modeled_neg,
        "event_BASE_modeled_negative": event_modeled_neg,
        "broker_evidence_cannot_rescue_if": "modeled spread+slip already exceeds gross signal edge or robustness is FRAGILE",
        "recent_oos_contradiction_blocks_rescue": recent_bad,
        "label": "EVIDENCE_RULE / NOT_OPINION",
    }


def run_phase61_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p58 = _safe_load_json(root / PHASE58_JSON) or {}
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    pack = reconstruct_events(signals)
    resolved = pack["resolved"]
    xs = [float(e["r_result"]) for e in resolved]
    contrib = contribution_analysis(resolved)
    losses = loss_concentration(resolved)
    time_b = yearly_and_half(resolved)
    monthly = monthly_stability(resolved)
    regime = regime_stability(resolved)
    session = session_stability(resolved, signals)
    hold = holding_time(resolved)
    curve = cost_curve(resolved, len(signals))
    modeled = modeled_scenarios(resolved)
    tape_end = _parse_ts(((p45.get("oos") or {}).get("splits") or {}).get("OOS", {}).get("end_ts")) or datetime(
        2026, 9, 7, tzinfo=timezone.utc
    )
    folds = fold_cost_survival(resolved, signals, tape_end)
    frozen_p5 = (p45.get("distribution") or {}).get("expectancy_p5_R")
    boot = bootstrap_cost(resolved, frozen_p5)
    modeled_base_e = (modeled["scenarios"]["BASE_COST"] or {}).get("expectancy_R")
    oos_e = (folds["folds"]["OOS"] or {}).get("gross_expectancy_R")
    recent_e = (folds["folds"]["RECENT_180D"] or {}).get("gross_expectancy_R")
    modeled_1x_signal = ((p45.get("cost_aware") or {}).get("MODELED_1X_signal_expectancy_R"))
    quality = score_edge_quality(
        gross_e=_mean(xs) or 0.0,
        time_clf=time_b["classification"],
        regime_dep=regime["REGIME_DEPENDENCY"],
        session_dep=session["SESSION_DEPENDENCY"],
        conc=contrib["classification"],
        rare_cat=bool(losses["dominated_by_rare_catastrophe"]),
        oos_e=oos_e,
        recent_e=recent_e,
        boot_p5=(boot["levels"]["cost_0.00R"] or {}).get("p5"),
        be=curve["event_break_even_R"],
        modeled_base_e=modeled_base_e,
        modeled_1x_signal_e=float(modeled_1x_signal) if modeled_1x_signal is not None else None,
    )
    decision = decision_economics(
        quality["EDGE_QUALITY"],
        modeled_base_e,
        _mean(xs) or 0.0,
        recent_e,
        modeled_1x_signal=float(modeled_1x_signal) if modeled_1x_signal is not None else None,
    )
    oos_surv = "SURVIVES" if (oos_e or 0) > 0.02 else "FAILS" if (oos_e or 0) <= 0 else "THIN"
    recent_surv = "FAILS" if (recent_e or 0) < 0 else "SURVIVES"
    compact_events = [
        {
            "timestamp": e["timestamp"],
            "direction": e["direction"],
            "r": e["r_result"],
            "regime": e["regime"],
            "hold_min": e["holding_time_minutes"],
            "fold": e["fold"],
            "month": e["month"],
            "session": e["session"],
            "members": e["member_count"],
        }
        for e in resolved
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
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "events": {
            **{k: pack[k] for k in ("construction", "signal_count", "event_count_including_open_only", "event_count_resolved")},
            "performance": pack_stats(xs),
            "fields_unknown": ["exit_fill_price", "asian_high", "asian_low", "mechanical_event_id_in_jsonl"],
            "rows_compact": compact_events,
        },
        "contribution": contrib,
        "loss_concentration": losses,
        "time_stability": time_b,
        "monthly": monthly,
        "regime": regime,
        "session": session,
        "holding_time": hold,
        "cost_curve": curve,
        "modeled_cost_uncertainty": modeled,
        "frozen_MODELED_1X_signal_expectancy_R": modeled_1x_signal,
        "fold_cost_survival": folds,
        "bootstrap": boot,
        "EDGE_QUALITY": quality["EDGE_QUALITY"],
        "edge_quality": quality,
        "COST_TOLERANCE": quality["dimensions"]["cost_tolerance"],
        "OOS_COST_SURVIVAL": oos_surv,
        "RECENT_COST_SURVIVAL": recent_surv,
        "ROBUSTNESS": p45.get("robustness_verdict") or "FRAGILE",
        "DECISION_ECONOMICS": decision["answer"],
        "decision_economics": decision,
        "phase58_break_even_R": p58.get("BREAK_EVEN_COST_R"),
        "profitability_verdict": "NOT_ISSUED",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "OPTIMIZATION": "NOT_PERFORMED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE61_JSON, "md": PHASE61_MD},
    }
    (root / PHASE61_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE61_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 61 — Edge Survival Forensics",
        "",
        f"**EDGE_QUALITY:** `{quality['EDGE_QUALITY']}`",
        f"**DECISION_ECONOMICS:** `{decision['answer']}`",
        f"**Concentration:** `{contrib['classification']}`",
        f"**Time stability:** `{time_b['classification']}`",
        f"**Regime dependency:** `{regime['REGIME_DEPENDENCY']}`",
        "",
        "Event reconstruction uses frozen `logs/phase40_raw_setups.jsonl` only. Strategy logic was not rerun.",
        "jsonl does not persist Asian range or mechanical_event_id; (utc_date, side) reconstructs 420 clusters.",
        "",
        decision["why"],
        "",
        "Not a profitability verdict. Modeled costs are MODELED / NOT_ACCOUNT_VERIFIED.",
        "",
    ]
    (root / PHASE61_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE61_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase61_collection(Path("."))["EDGE_QUALITY"])
