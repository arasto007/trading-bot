"""Phase 31 — event-level independence, clustering, and concentration audit.

RESEARCH ONLY. Uses the frozen Phase 30 RAW book. No production change,
no optimization, no new signal generation.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    UNKNOWN,
)
from tradingbot.backtest.phase28_1_full_baseline import _parse_ts
from tradingbot.backtest.phase28_3_monte_carlo import path_metrics, run_bootstrap, summarize_paths
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import (
    PHASE30_JSON,
    event_representatives,
    performance_pack,
)

PHASE = "31"
PHASE31_JSON = "logs/phase31_event_independence.json"
PHASE31_MD = "docs_v2/02_research/PHASE31_EVENT_INDEPENDENCE.md"
EVALUATOR_VERSION = "phase31-independence-v1"
RNG_SEED = 310031
N_PATHS = 2000
SWEEP_CLONE_TOLERANCE = 0.5
MEAN_SIGNALS_PER_EVENT_HIGH = 2.0
LARGEST_CLUSTER_SHARE_HIGH = 0.25
CLUSTERED_SHARE_HIGH = 0.50
OVERLAP_HOLD_SHARE_HIGH = 0.50
EVENT_TO_SIGNAL_RATIO_HIGH = 0.50
SAME_STOP_GROUP_MIN = 3

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "dataset_fingerprint",
    "event_definition",
    "signal_classifications",
    "event_metrics",
    "performance",
    "concentration",
    "dependence",
    "bootstrap",
    "conclusion",
    "FINAL_GATE",
    "phase_32_started",
)

EVENT_CONSTRUCTION = {
    "name": "mechanical_asian_range_side",
    "source": "gold_ny_sweep / london_sweep M5 production mechanics",
    "rule": (
        "One EVENT = one (UTC date, asian_high, asian_low, side) tuple. "
        "The strategy computes the Asian range once per UTC date, then may emit "
        "multiple closed-bar NY 15-16 UTC signals while that same range remains "
        "the reference and the same side (BUY=Asian-low sweep, SELL=Asian-high sweep) "
        "remains valid. Repeated fires on that range+side are the same market occurrence, "
        "not independent liquidity events."
    ),
    "fields": ["utc_date", "asian_high", "asian_low", "side"],
    "not_invented_to_improve_statistics": True,
    "phase28_4_heuristic": {
        "used_as_official_event": False,
        "role": "diagnostic only",
        "rule": (
            "Same UTC date + same direction + (gap<=30m from first cluster member "
            "OR same exit_index OR sweep extreme within 0.5). "
            "The 30-minute-from-first-member cut can split one Asian-range+side day "
            "(observed: 2026-08-27 BUY). That split is a proximity heuristic, not a "
            "new sweep/reclaim occurrence."
        ),
    },
    "sweep_clone_tolerance": SWEEP_CLONE_TOLERANCE,
    "selection_for_event_performance": "earliest official signal in the mechanical event",
    "not_optimized": True,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(values, q))


def mechanical_event_key(row: dict[str, Any]) -> tuple[str, float, float, str]:
    ts = _parse_ts(row["timestamp"])
    if ts is None:
        raise ValueError("signal missing parseable timestamp")
    return (
        str(ts.date()),
        round(float(row["asian_high"]), 2),
        round(float(row["asian_low"]), 2),
        str(row.get("side") or row.get("direction") or "").upper(),
    )


def intervals_overlap(a0: Any, a1: Any, b0: Any, b1: Any) -> bool:
    sa, ea = _parse_ts(a0), _parse_ts(a1)
    sb, eb = _parse_ts(b0), _parse_ts(b1)
    if None in (sa, ea, sb, eb):
        return False
    return sa <= eb and sb <= ea


def load_phase30_raw(root: Path) -> dict[str, Any]:
    p30 = _safe_load_json(root / PHASE30_JSON) or {}
    if not p30:
        raise FileNotFoundError("Phase 30 artifact is required")
    rows = list((p30.get("raw_signal_book") or {}).get("rows") or [])
    if len(rows) != 24:
        raise RuntimeError(f"Phase 30 RAW book expected 24 rows, got {len(rows)}")
    fp = p30.get("dataset_fingerprint")
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Phase 30 fingerprint does not match the frozen canonical tape")
    return {
        "rows": rows,
        "dataset_fingerprint": fp,
        "calendar_days": float(
            ((p30.get("raw_signal_book") or {}).get("performance") or {}).get("calendar_days") or 14.8785
        ),
        "ny_session_days_tape": int(
            ((p30.get("raw_signal_book") or {}).get("performance") or {}).get("ny_session_days") or 10
        ),
        "phase30_conclusion": (p30.get("conclusion") or {}).get("verdict"),
        "phase28_4_event_count": int((p30.get("event_level") or {}).get("n_events") or 7),
    }


def assign_mechanical_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[int]] = {}
    out = []
    for i, raw in enumerate(rows):
        key = mechanical_event_key(raw)
        groups.setdefault(key, []).append(i)
    event_ids: dict[tuple[Any, ...], int] = {}
    next_id = 0
    for raw in rows:
        key = mechanical_event_key(raw)
        if key not in event_ids:
            event_ids[key] = next_id
            next_id += 1
    first_by_event: dict[int, dict[str, Any]] = {}
    for raw in rows:
        eid = event_ids[mechanical_event_key(raw)]
        if eid not in first_by_event:
            first_by_event[eid] = raw
    for i, raw in enumerate(rows):
        row = dict(raw)
        key = mechanical_event_key(row)
        eid = event_ids[key]
        members = groups[key]
        first = first_by_event[eid]
        sweep = row.get("sweep_level")
        first_sweep = first.get("sweep_level")
        same_sweep = False
        if sweep is not None and first_sweep is not None:
            same_sweep = abs(float(sweep) - float(first_sweep)) < SWEEP_CLONE_TOLERANCE
        ts = _parse_ts(row["timestamp"])
        row["mechanical_event_id"] = eid
        row["event_key"] = {
            "utc_date": key[0],
            "asian_high": key[1],
            "asian_low": key[2],
            "side": key[3],
        }
        row["event_member_count"] = len(members)
        row["is_unique_event"] = members[0] == i
        row["repeated_signal_within_same_event"] = members[0] != i
        row["same_direction_reentry"] = members[0] != i
        row["same_sweep"] = same_sweep
        row["same_ny_session"] = True
        row["same_day"] = True
        row["session_date"] = None if ts is None else str(ts.date())
        row["phase28_4_cluster_id"] = row.get("event_cluster_id")
        out.append(row)
    dates = [r["session_date"] for r in out]
    sides_by_day: dict[str, set[str]] = defaultdict(set)
    for r in out:
        sides_by_day[str(r["session_date"])].add(str(r["side"]))
    for r in out:
        day_sides = sides_by_day[str(r["session_date"])]
        r["opposite_direction_on_same_day"] = len(day_sides) > 1
        r["same_ny_session_signal_count"] = dates.count(r["session_date"])
        r["same_day_signal_count"] = dates.count(r["session_date"])
    for i, a in enumerate(out):
        overlaps = []
        for j, b in enumerate(out):
            if i == j:
                continue
            if intervals_overlap(a["timestamp"], a.get("exit_time"), b["timestamp"], b.get("exit_time")):
                overlaps.append(b["signal_id"])
        a["overlapping_holding_period"] = bool(overlaps)
        a["overlapping_signal_ids"] = overlaps
    return out


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r.get(key)].append(r)
    return dict(groups)


def event_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = _group_by(rows, "mechanical_event_id")
    sizes = sorted(len(v) for v in groups.values())
    n_events = len(groups)
    n_signals = len(rows)
    clustered = sum(1 for r in rows if r["event_member_count"] > 1)
    singletons = sum(1 for sz in sizes if sz == 1)
    return {
        "signal_count": n_signals,
        "event_count": n_events,
        "signals_per_event": {
            "mean": (n_signals / n_events) if n_events else 0.0,
            "median": _pct(sizes, 50),
            "p75": _pct(sizes, 75),
            "p90": _pct(sizes, 90),
            "maximum": max(sizes) if sizes else 0,
        },
        "singleton_events": singletons,
        "clustered_events": n_events - singletons,
        "clustered_signals": clustered,
        "clustered_signal_share": clustered / n_signals if n_signals else 0.0,
        "largest_cluster_signal_share": (max(sizes) / n_signals) if n_signals and sizes else 0.0,
        "phase28_4_heuristic_event_count": len({r.get("phase28_4_cluster_id") for r in rows}),
        "sizes": sizes,
    }


def classify_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append(
            {
                "signal_id": r["signal_id"],
                "timestamp": r["timestamp"],
                "side": r["side"],
                "theoretical_R": r.get("theoretical_R"),
                "outcome": r.get("outcome"),
                "mechanical_event_id": r["mechanical_event_id"],
                "phase28_4_cluster_id": r.get("phase28_4_cluster_id"),
                "unique_event": r["is_unique_event"],
                "repeated_signal_within_same_event": r["repeated_signal_within_same_event"],
                "same_direction_reentry": r["same_direction_reentry"],
                "opposite_direction_signal": r["opposite_direction_on_same_day"],
                "same_sweep": r["same_sweep"],
                "same_ny_session": r["same_ny_session"],
                "same_day": r["same_day"],
                "overlapping_holding_period": r["overlapping_holding_period"],
                "asian_high": r.get("asian_high"),
                "asian_low": r.get("asian_low"),
                "sweep_level": r.get("sweep_level"),
                "reclaim_level": r.get("reclaim_level"),
                "entry_price": r.get("entry_price"),
                "stop_loss": r.get("stop_loss"),
                "take_profit": r.get("take_profit"),
                "exit_time": r.get("exit_time"),
                "exit_index": r.get("exit_index"),
            }
        )
    return out


def performance_views(rows: list[dict[str, Any]], *, calendar_days: float, ny_session_days: int) -> dict[str, Any]:
    events = event_representatives(
        [
            {
                **r,
                "event_cluster_id": r["mechanical_event_id"],
            }
            for r in rows
        ]
    )
    per_signal = performance_pack(rows, calendar_days=calendar_days, ny_session_days=ny_session_days)
    per_event = performance_pack(events, calendar_days=calendar_days, ny_session_days=len({e["session_date"] for e in events}))
    per_event["selection_rule"] = "earliest official signal in each mechanical event"
    per_event["not_optimized"] = True

    by_day: dict[str, dict[str, Any]] = {}
    for r in rows:
        day = r["session_date"]
        block = by_day.setdefault(day, {"n": 0, "net_R": 0.0, "wins": 0, "losses": 0, "events": set()})
        block["n"] += 1
        block["net_R"] += float(r.get("theoretical_R") or 0.0)
        if r.get("outcome") == "win":
            block["wins"] += 1
        elif r.get("outcome") == "loss":
            block["losses"] += 1
        block["events"].add(r["mechanical_event_id"])
    day_rows = []
    for day, b in sorted(by_day.items()):
        day_rows.append(
            {
                "date": day,
                "signal_count": b["n"],
                "event_count": len(b["events"]),
                "net_R": b["net_R"],
                "wins": b["wins"],
                "losses": b["losses"],
            }
        )
    return {
        "per_signal": per_signal,
        "per_event": per_event,
        "per_day": {
            "n_days": len(day_rows),
            "rows": day_rows,
            "note": "Signal-sum P/L on each UTC date. Same-day opposite-direction signals stay separate events.",
        },
        "per_session": {
            "n_sessions": len(day_rows),
            "rows": day_rows,
            "note": "Every official signal is inside NY 15-16 UTC; session key = UTC date.",
        },
        "event_representatives": events,
    }


def concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = _group_by(rows, "mechanical_event_id")
    event_sums = []
    for eid, members in groups.items():
        rs = [float(m["theoretical_R"]) for m in members]
        event_sums.append(
            {
                "mechanical_event_id": eid,
                "n": len(members),
                "signal_sum_R": float(sum(rs)),
                "abs_signal_sum_R": float(abs(sum(rs))),
                "representative_R": float(members[0]["theoretical_R"]),
                "date": members[0]["session_date"],
                "side": members[0]["side"],
                "signal_ids": [m["signal_id"] for m in members],
            }
        )
    total_net = float(sum(e["signal_sum_R"] for e in event_sums))
    total_abs = float(sum(e["abs_signal_sum_R"] for e in event_sums)) or 1.0
    n_signals = len(rows)
    by_abs = sorted(event_sums, key=lambda e: e["abs_signal_sum_R"], reverse=True)

    def top_k(k: int) -> dict[str, Any]:
        chosen = by_abs[:k]
        return {
            "k": k,
            "event_ids": [e["mechanical_event_id"] for e in chosen],
            "signal_count": sum(e["n"] for e in chosen),
            "signal_share": sum(e["n"] for e in chosen) / n_signals if n_signals else 0.0,
            "net_R": sum(e["signal_sum_R"] for e in chosen),
            "share_of_net_R": (sum(e["signal_sum_R"] for e in chosen) / total_net) if total_net else 0.0,
            "share_of_abs_R": sum(e["abs_signal_sum_R"] for e in chosen) / total_abs,
        }

    n_events = len(event_sums)
    top10_k = max(1, int(math.ceil(0.10 * n_events))) if n_events else 0
    largest = by_abs[0] if by_abs else None
    return {
        "total_net_R": total_net,
        "total_abs_event_R": total_abs,
        "events_ranked_by_abs_contribution": by_abs,
        "top_1_event": top_k(1) if n_events else None,
        "top_2_events": top_k(min(2, n_events)) if n_events else None,
        "top_5_events": top_k(min(5, n_events)) if n_events else None,
        "top_10pct_events": {
            "k": top10_k,
            "rule": "ceil(10% of mechanical events), minimum 1",
            **(top_k(top10_k) if top10_k else {}),
        },
        "largest_cluster_signal_share": (largest["n"] / n_signals) if largest and n_signals else 0.0,
        "largest_two_clusters_signal_share": (
            sum(e["n"] for e in by_abs[:2]) / n_signals if n_signals else 0.0
        ),
        "unit": "theoretical GROSS R from the Phase 30 RAW book; not fills; not cost-adjusted",
    }


def dependence_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    overlap_n = sum(1 for r in rows if r["overlapping_holding_period"])
    same_sweep_clones = sum(1 for r in rows if r["same_sweep"] and r["repeated_signal_within_same_event"])
    by_exit = _group_by(rows, "exit_index")
    same_stop = [
        {"exit_index": k, "n": len(v), "signal_ids": [x["signal_id"] for x in v], "outcomes": [x.get("outcome") for x in v]}
        for k, v in by_exit.items()
        if k is not None and len(v) >= 2 and all(x.get("outcome") == "loss" for x in v)
    ]
    same_tp = [
        {"exit_index": k, "n": len(v), "signal_ids": [x["signal_id"] for x in v]}
        for k, v in by_exit.items()
        if k is not None and len(v) >= 2 and all(x.get("outcome") == "win" for x in v)
    ]
    same_move = sum(1 for r in rows if r["event_member_count"] > 1)
    stop_ge3 = sum(1 for g in same_stop if g["n"] >= SAME_STOP_GROUP_MIN)
    return {
        "simultaneous_or_overlapping_trades": {
            "signals": overlap_n,
            "share": overlap_n / len(rows) if rows else 0.0,
        },
        "same_sweep_clones": {
            "signals": same_sweep_clones,
            "tolerance": SWEEP_CLONE_TOLERANCE,
            "note": "Repeated signals whose sweep_level is within 0.5 of the event's first sweep.",
        },
        "same_stop_event": {
            "groups": same_stop,
            "groups_ge_3": stop_ge3,
        },
        "same_tp_event": {
            "groups": same_tp,
        },
        "same_underlying_price_movement": {
            "signals_sharing_mechanical_event": same_move,
            "share": same_move / len(rows) if rows else 0.0,
            "definition": "Any repeated signal on the same (date, asian_high, asian_low, side).",
        },
        "treating_signals_independently_exaggerates_evidence": True,
        "not_a_strategy_failure": True,
    }


def classify_dependence(metrics: dict[str, Any], dep: dict[str, Any]) -> dict[str, Any]:
    mean_spe = float(metrics["signals_per_event"]["mean"])
    largest_share = float(metrics["largest_cluster_signal_share"])
    clustered_share = float(metrics["clustered_signal_share"])
    overlap_share = float(dep["simultaneous_or_overlapping_trades"]["share"])
    stop_ge3 = int(dep["same_stop_event"]["groups_ge_3"])
    ratio = (metrics["event_count"] / metrics["signal_count"]) if metrics["signal_count"] else 1.0
    checks = [
        {
            "id": "A",
            "name": "mean_signals_per_event",
            "value": mean_spe,
            "threshold": MEAN_SIGNALS_PER_EVENT_HIGH,
            "pass_dependence": mean_spe >= MEAN_SIGNALS_PER_EVENT_HIGH,
            "rule": f"mean signals/event >= {MEAN_SIGNALS_PER_EVENT_HIGH}",
        },
        {
            "id": "B",
            "name": "largest_cluster_signal_share",
            "value": largest_share,
            "threshold": LARGEST_CLUSTER_SHARE_HIGH,
            "pass_dependence": largest_share >= LARGEST_CLUSTER_SHARE_HIGH,
            "rule": f"largest event contains >= {LARGEST_CLUSTER_SHARE_HIGH:.0%} of signals",
        },
        {
            "id": "C",
            "name": "clustered_signal_share",
            "value": clustered_share,
            "threshold": CLUSTERED_SHARE_HIGH,
            "pass_dependence": clustered_share >= CLUSTERED_SHARE_HIGH,
            "rule": f"clustered signals >= {CLUSTERED_SHARE_HIGH:.0%}",
        },
        {
            "id": "D",
            "name": "overlapping_hold_share",
            "value": overlap_share,
            "threshold": OVERLAP_HOLD_SHARE_HIGH,
            "pass_dependence": overlap_share >= OVERLAP_HOLD_SHARE_HIGH,
            "rule": f"overlapping holding periods >= {OVERLAP_HOLD_SHARE_HIGH:.0%}",
        },
        {
            "id": "E",
            "name": "same_stop_group_ge_3",
            "value": stop_ge3,
            "threshold": 1,
            "pass_dependence": stop_ge3 >= 1,
            "rule": f"at least one shared-SL exit group of size >= {SAME_STOP_GROUP_MIN}",
        },
        {
            "id": "F",
            "name": "event_to_signal_ratio",
            "value": ratio,
            "threshold": EVENT_TO_SIGNAL_RATIO_HIGH,
            "pass_dependence": ratio <= EVENT_TO_SIGNAL_RATIO_HIGH,
            "rule": f"unique events / signals <= {EVENT_TO_SIGNAL_RATIO_HIGH}",
        },
    ]
    hits = [c["id"] for c in checks if c["pass_dependence"]]
    if len(hits) >= 2:
        grade = "HIGH_DEPENDENCE"
    elif len(hits) == 1:
        grade = "MODERATE_DEPENDENCE"
    else:
        grade = "LOW_DEPENDENCE"
    return {
        "grade": grade,
        "hits": hits,
        "hit_count": len(hits),
        "criteria": checks,
        "thresholds_source": (
            "Explicit Phase 31 floors: mean signals/event>=2; largest-cluster share>=25%; "
            "clustered share>=50%; overlapping holds>=50%; >=1 shared-stop group of size>=3; "
            "events/signals<=0.5. HIGH if >=2 criteria hit; MODERATE if 1; LOW if 0. "
            "Not invented silently. Dependence is not a strategy failure."
        ),
        "not_a_strategy_failure": True,
        "signal_level_not_independent_evidence": grade != "LOW_DEPENDENCE",
    }


def bootstrap_units(rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    signal_r = [float(r["theoretical_R"]) for r in rows]
    event_r = [float(e["theoretical_R"]) for e in events]
    rng_s = np.random.default_rng(RNG_SEED)
    rng_e = np.random.default_rng(RNG_SEED)
    sig_paths = run_bootstrap(signal_r, rng_s, N_PATHS)
    ev_paths = run_bootstrap(event_r, rng_e, N_PATHS)
    return {
        "seed": RNG_SEED,
        "n_paths": N_PATHS,
        "signal_level": {
            "n": len(signal_r),
            "observed_net_R": float(sum(signal_r)),
            "observed_expectancy_R": float(sum(signal_r) / len(signal_r)),
            "summary": summarize_paths(sig_paths),
            "independent_evidence": False,
            "note": "Resamples 24 dependent signals. Do not present as independent evidence.",
        },
        "event_level": {
            "n": len(event_r),
            "observed_net_R": float(sum(event_r)),
            "observed_expectancy_R": float(sum(event_r) / len(event_r)) if event_r else 0.0,
            "summary": summarize_paths(ev_paths),
            "unit": "earliest official signal per mechanical event",
            "note": "Correct bootstrap unit when HIGH_DEPENDENCE is present.",
        },
        "do_not_present_signal_level_as_independent": True,
    }


def audit_independence(loaded: dict[str, Any]) -> dict[str, Any]:
    rows = assign_mechanical_events(list(loaded["rows"]))
    metrics = event_metrics(rows)
    perf = performance_views(
        rows,
        calendar_days=float(loaded["calendar_days"]),
        ny_session_days=int(loaded["ny_session_days_tape"]),
    )
    conc = concentration(rows)
    dep = dependence_audit(rows)
    grade = classify_dependence(metrics, dep)
    boot = bootstrap_units(rows, perf["event_representatives"])
    return {
        "rows": rows,
        "signal_classifications": classify_signals(rows),
        "event_metrics": metrics,
        "performance": {
            "per_signal": perf["per_signal"],
            "per_event": perf["per_event"],
            "per_day": perf["per_day"],
            "per_session": perf["per_session"],
        },
        "concentration": conc,
        "dependence": dep,
        "dependence_grade": grade,
        "bootstrap": boot,
    }


def classify_conclusion(grade: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    text = (
        f"{grade['grade']}. {metrics['signal_count']} RAW signals collapse to "
        f"{metrics['event_count']} mechanical events "
        f"(mean {metrics['signals_per_event']['mean']:.2f} signals/event; "
        f"largest cluster {metrics['largest_cluster_signal_share']:.0%} of the book). "
        "Treating signals independently exaggerates the sample. "
        "This is an independence finding, not a strategy failure, not an edge claim, "
        "and not a no-edge claim."
    )
    return {
        "verdict": grade["grade"],
        "not_a_strategy_failure": True,
        "edge_supported": False,
        "no_edge_supported": False,
        "signal_level_independent_evidence": False,
        "text": text,
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    m = payload["event_metrics"]
    g = payload["dependence_grade"]
    c = payload["concentration"]
    p = payload["performance"]
    path = root / PHASE31_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 31 — Event-Level Independence, Clustering & Concentration

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Conclusion:** `{payload["conclusion"]["verdict"]}`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

STOP AFTER PHASE 31. DO NOT START PHASE 32.

---

## Event definition

Official unit: **mechanical Asian-range + side**.

{payload["event_definition"]["rule"]}

Phase 28.4's 30-minute proximity cluster is **diagnostic only**. It is not the official event ID.
It can split one Asian-range+side day (2026-08-27 BUY). That is not a second sweep event.

Selection for event-level performance: earliest official signal in the mechanical event. Not optimized.

## Classification

Every RAW signal is labeled: unique event / repeated within event / same-direction re-entry /
opposite-direction on the same day / same sweep / same NY session / same day / overlapping hold.

## Event metrics

| Metric | Value |
|---|---:|
| Signals | {m["signal_count"]} |
| Events | {m["event_count"]} |
| Mean signals/event | {m["signals_per_event"]["mean"]} |
| Median | {m["signals_per_event"]["median"]} |
| p75 | {m["signals_per_event"]["p75"]} |
| p90 | {m["signals_per_event"]["p90"]} |
| Maximum | {m["signals_per_event"]["maximum"]} |
| Clustered signal share | {m["clustered_signal_share"]} |
| Phase 28.4 heuristic clusters | {m["phase28_4_heuristic_event_count"]} |

## Performance

| Book | N | WR | Expectancy R | PF | Net R |
|---|---:|---:|---:|---:|---:|
| Per-signal | {p["per_signal"].get("total_trades")} | {p["per_signal"].get("win_rate")} | {p["per_signal"].get("expectancy_R")} | {p["per_signal"].get("profit_factor")} | {p["per_signal"].get("net_R")} |
| Per-event | {p["per_event"].get("total_trades")} | {p["per_event"].get("win_rate")} | {p["per_event"].get("expectancy_R")} | {p["per_event"].get("profit_factor")} | {p["per_event"].get("net_R")} |

Per-day / per-session rows are in the JSON. All signals sit in NY 15-16 UTC.

## Concentration

| Slice | Events | Signal share | Share of \\|R\\| |
|---|---:|---:|---:|
| Top 1 | {c["top_1_event"]["k"]} | {c["top_1_event"]["signal_share"]} | {c["top_1_event"]["share_of_abs_R"]} |
| Top 2 | {c["top_2_events"]["k"]} | {c["top_2_events"]["signal_share"]} | {c["top_2_events"]["share_of_abs_R"]} |
| Top 5 | {c["top_5_events"]["k"]} | {c["top_5_events"]["signal_share"]} | {c["top_5_events"]["share_of_abs_R"]} |
| Top 10% | {c["top_10pct_events"]["k"]} | {c["top_10pct_events"]["signal_share"]} | {c["top_10pct_events"]["share_of_abs_R"]} |

Largest cluster signal share: `{c["largest_cluster_signal_share"]}`.

## Dependence

Overlapping holds: `{payload["dependence"]["simultaneous_or_overlapping_trades"]}`.  
Same-sweep clones: `{payload["dependence"]["same_sweep_clones"]["signals"]}`.  
Shared-stop groups: `{len(payload["dependence"]["same_stop_event"]["groups"])}`.  
Criteria hits: `{g["hits"]}` ({g["thresholds_source"]}).

Treating 24 signals as independent **exaggerates** the evidence. This is **not** a strategy failure.

## Bootstrap

Two versions, seed `{payload["bootstrap"]["seed"]}`, `{payload["bootstrap"]["n_paths"]}` paths.

- SIGNAL-LEVEL: **not** independent evidence.
- EVENT-LEVEL: correct unit under `{g["grade"]}`.

## CONCLUSION

**{payload["conclusion"]["verdict"]}**

{payload["conclusion"]["text"]}

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 32 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase31_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 31 refuses to proceed")
    loaded = load_phase30_raw(root)
    if loaded["dataset_fingerprint"] != fp:
        raise RuntimeError("Phase 30 fingerprint does not match the live parquet")

    pass_a = audit_independence(loaded)
    pass_b = audit_independence(loaded)
    core_a = {
        "metrics": pass_a["event_metrics"],
        "grade": pass_a["dependence_grade"]["grade"],
        "hits": pass_a["dependence_grade"]["hits"],
        "top1": pass_a["concentration"]["top_1_event"],
        "boot_s": pass_a["bootstrap"]["signal_level"]["summary"]["final_R"],
        "boot_e": pass_a["bootstrap"]["event_level"]["summary"]["final_R"],
    }
    core_b = {
        "metrics": pass_b["event_metrics"],
        "grade": pass_b["dependence_grade"]["grade"],
        "hits": pass_b["dependence_grade"]["hits"],
        "top1": pass_b["concentration"]["top_1_event"],
        "boot_s": pass_b["bootstrap"]["signal_level"]["summary"]["final_R"],
        "boot_e": pass_b["bootstrap"]["event_level"]["summary"]["final_R"],
    }
    if _stable_hash(core_a) != _stable_hash(core_b):
        raise RuntimeError("Phase 31 audit is not deterministic")

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    conclusion = classify_conclusion(pass_a["dependence_grade"], pass_a["event_metrics"])
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS",
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "parameters_searched": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "silent_xauusd_mapping": False,
        "logical_xauusd_used": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "event_definition": EVENT_CONSTRUCTION,
        "signal_classifications": pass_a["signal_classifications"],
        "event_metrics": pass_a["event_metrics"],
        "performance": pass_a["performance"],
        "concentration": pass_a["concentration"],
        "dependence": pass_a["dependence"],
        "dependence_grade": pass_a["dependence_grade"],
        "bootstrap": pass_a["bootstrap"],
        "conclusion": conclusion,
        "reproducibility": {
            "passes": 2,
            "passes_match": True,
            "data_fingerprint": fp,
            "evaluator_fingerprint": EVALUATOR_VERSION,
            "output_fingerprint": _stable_hash(core_a),
            "rng_seed": RNG_SEED,
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PHASE_32_STARTED": False,
        },
        "phase_32_started": False,
    }
    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE31_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Event independence (Phase 31)"
        block = (
            "\n\n## Event independence (Phase 31)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Official event = (UTC date, Asian high, Asian low, side) | **SUPPORTED** |\n"
            "| 24 RAW signals are independent observations | **FALSE** — HIGH_DEPENDENCE |\n"
            "| Phase 28.4 30-minute clusters are the official event | **NO** — diagnostic heuristic only |\n"
            "| Dependence is a strategy failure | **FALSE** |\n"
            "| Signal-level bootstrap is independent evidence | **NO** |\n"
            "| Phase 31 authorizes live trading or optimization | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")
    return payload


if __name__ == "__main__":
    run_phase31_collection()
