"""Phase 78 — time / reversal exit forensics. No arbitrary threshold search."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    UNKNOWN,
    _git_head,
    _median,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import TAPE_END_FALLBACK, split_views
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74

PHASE = "78"
PHASE78_JSON = "logs/phase78_time_exit_forensics.json"
PHASE78_MD = "docs/PHASE78_TIME_EXIT_FORENSICS.md"
BLOCKED = "BLOCKED"
# Predeclared structural buckets — not searched.
HOLD_BUCKETS = (
    ("lt_15m", 0.0, 15.0),
    ("15_30m", 15.0, 30.0),
    ("30_60m", 30.0, 60.0),
    ("1_2h", 60.0, 120.0),
    ("2h_plus", 120.0, 1e12),
)
REV_BUCKETS = (
    ("lt_15m", 0.0, 15.0),
    ("15_30m", 15.0, 30.0),
    ("30_60m", 30.0, 60.0),
    ("1h_plus", 60.0, 1e12),
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "TIME_DEPENDENCY",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _bucket(x: float | None, edges: tuple) -> str:
    if x is None:
        return UNKNOWN
    for name, lo, hi in edges:
        if lo <= x < hi:
            return name
    return UNKNOWN


def pack_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [_f(e.get("r_result")) for e in rows]
    xs = [x for x in xs if x is not None]
    t_mfe = [_f(e.get("time_to_mfe_min")) for e in rows]
    t_rev = [_f(e.get("mins_mfe_to_exit")) for e in rows]
    hold = [_f(e.get("duration_minutes")) for e in rows]
    return {
        "n": len(rows),
        "small_n": len(rows) < 8,
        **pack_stats(xs),
        "median_time_to_MFE": _median([x for x in t_mfe if x is not None]),
        "median_time_to_reversal": _median([x for x in t_rev if x is not None]),
        "median_hold": _median([x for x in hold if x is not None]),
    }


def by_key(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    g: dict[str, list] = {}
    for e in rows:
        g.setdefault(str(e.get(key) or UNKNOWN), []).append(e)
    return {k: pack_rows(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}


def run_phase78_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    from tradingbot.backtest.phase61_edge_survival_forensics import _parse_ts

    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    losses_05 = [
        e for e in events if e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) >= 0.5
    ]
    losses_1 = [
        e for e in events if e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) >= 1.0
    ]
    for e in events:
        e["hold_bucket"] = _bucket(_f(e.get("duration_minutes")), HOLD_BUCKETS)
        e["rev_bucket"] = _bucket(_f(e.get("mins_mfe_to_exit")), REV_BUCKETS)
    hold_dist = by_key(events, "hold_bucket")
    rev_05 = by_key(losses_05, "rev_bucket")
    # If giveback is spread across several reversal buckets, time is not a single kill-switch.
    usable = [v for v in rev_05.values() if not v.get("small_n")]
    if len(usable) <= 1:
        td = "PRIMARY"
    elif len(usable) >= 3:
        td = "SECONDARY"
    else:
        td = "WEAK"
    if not losses_05:
        td = "UNSUPPORTED"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "predeclared_buckets": {"hold": [x[0] for x in HOLD_BUCKETS], "reversal": [x[0] for x in REV_BUCKETS]},
        "all_events": {
            "time_to_MFE": pack_rows(events)["median_time_to_MFE"],
            "hold_buckets": hold_dist,
            "weekday": by_key(events, "weekday"),
            "hour_utc": by_key(events, "hour_utc"),
            "session": by_key(events, "session"),
            "regime": by_key(events, "regime"),
            "side": by_key(events, "side"),
        },
        "loss_after_0.5R": {
            "n": len(losses_05),
            **pack_rows(losses_05),
            "reversal_buckets": rev_05,
            "weekday": by_key(losses_05, "weekday"),
            "session": by_key(losses_05, "session"),
        },
        "loss_after_1R": {
            "n": len(losses_1),
            **pack_rows(losses_1),
            "reversal_buckets": by_key(losses_1, "rev_bucket"),
        },
        "folds": {
            name: pack_rows(
                [e for e in rows if e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) >= 0.5]
            )
            for name, rows in split_views(events, tape_end).items()
        },
        "TIME_DEPENDENCY": td,
        "note": (
            "Entry hour is NY 15 UTC by production design, so hour-of-entry is not independent evidence. "
            "Reversal-time buckets among MFE>=0.5R losers are the relevant exit-time signature."
        ),
        "threshold_search": False,
        "hypotheses": [
            {
                "id": "H78-01",
                "claim": "Give-back after MFE has a concentrated single-bucket time signature that would make TIME primary.",
                "result": td,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["hold_buckets", "reversal_buckets", "weekday_session"],
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
        "artifacts": {"json": PHASE78_JSON, "md": PHASE78_MD},
    }
    (root / PHASE78_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE78_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE78_MD).write_text(
        "\n".join(
            [
                "# Phase 78 — Time / Reversal Exit Forensics",
                "",
                f"**TIME_DEPENDENCY (exit signature):** `{td}`",
                f"Losers with MFE>=0.5R: `{len(losses_05)}`; MFE>=1R: `{len(losses_1)}`.",
                "",
                "Buckets are predeclared. No arbitrary minute search. Entry TOD is production-constrained.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase78_collection(Path("."))["TIME_DEPENDENCY"])
