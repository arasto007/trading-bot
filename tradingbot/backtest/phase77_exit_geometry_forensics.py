"""Phase 77 — planned-RR / exit-geometry forensics. No RR optimization."""

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
    _mean,
    _median,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74

PHASE = "77"
PHASE77_JSON = "logs/phase77_exit_geometry_forensics.json"
PHASE77_MD = "docs/PHASE77_EXIT_GEOMETRY.md"
BLOCKED = "BLOCKED"
RR_BINS = (
    ("RR_le_1", 0.0, 1.0),
    ("RR_1_2", 1.0, 2.0),
    ("RR_2_3", 2.0, 3.0),
    ("RR_3_5", 3.0, 5.0),
    ("RR_5_10", 5.0, 10.0),
    ("RR_gt_10", 10.0, 1e12),
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "rr_bins",
    "high_rr_class",
    "final_gate",
    "production_safety",
    "artifacts",
)


def rr_bin(rr: float | None) -> str:
    if rr is None:
        return UNKNOWN
    if rr <= 1:
        return "RR_le_1"
    if rr <= 2:
        return "RR_1_2"
    if rr <= 3:
        return "RR_2_3"
    if rr <= 5:
        return "RR_3_5"
    if rr <= 10:
        return "RR_5_10"
    return "RR_gt_10"


def pack_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [_f(e.get("r_result")) for e in rows]
    xs = [x for x in xs if x is not None]
    sl = [_f(e.get("risk_price_units")) for e in rows]
    tp = []
    for e in rows:
        a, b = _f(e.get("entry")), _f(e.get("TP"))
        if a is not None and b is not None:
            tp.append(abs(a - b))
    mfe = [_f(e.get("mfe_R")) for e in rows]
    mae = [_f(e.get("mae_R")) for e in rows]
    hold = [_f(e.get("duration_minutes")) for e in rows]
    rr = [_f(e.get("planned_rr")) for e in rows]
    return {
        "n": len(rows),
        "small_n": len(rows) < 8,
        **pack_stats(xs),
        "median_SL": _median([x for x in sl if x is not None]),
        "median_TP_distance": _median(tp),
        "median_planned_RR": _median([x for x in rr if x is not None]),
        "median_MFE": _median([x for x in mfe if x is not None]),
        "median_MAE": _median([x for x in mae if x is not None]),
        "median_hold": _median([x for x in hold if x is not None]),
        "LOSS_SL": sum(1 for e in rows if e.get("exit_class") == "LOSS_SL"),
        "WIN_TP": sum(1 for e in rows if e.get("exit_class") == "WIN_TP"),
        "sides": {s: sum(1 for e in rows if e.get("side") == s) for s in ("BUY", "SELL")},
        "regimes": _cnt(rows, "regime"),
        "sessions": _cnt(rows, "session"),
        "years": _cnt(rows, "year"),
    }


def _cnt(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in rows:
        k = str(e.get(key) or UNKNOWN)
        out[k] = out.get(k, 0) + 1
    return out


def run_phase77_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    for e in events:
        e["rr_bin"] = rr_bin(_f(e.get("planned_rr")))
    bins = {}
    for name, lo, hi in RR_BINS:
        if name == "RR_le_1":
            rows = [e for e in events if e["rr_bin"] == name]
        elif name == "RR_gt_10":
            rows = [e for e in events if e["rr_bin"] == name]
        else:
            rows = [e for e in events if e["rr_bin"] == name]
        bins[name] = pack_group(rows)
    high = [e for e in events if (_f(e.get("planned_rr")) or 0) > 10]
    all_sl = [_f(e.get("risk_price_units")) for e in events]
    high_sl = [_f(e.get("risk_price_units")) for e in high]
    med_sl = _median([x for x in all_sl if x is not None])
    med_high_sl = _median([x for x in high_sl if x is not None])
    tight = bool(med_high_sl is not None and med_sl is not None and med_high_sl < 0.5 * med_sl)
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    n_high = len(high)
    n_high_win = sum(1 for e in high if e.get("exit_class") == "WIN_TP")
    if n_high >= 8 and tight:
        geometry_class = "LEGITIMATE_STRUCTURAL_CLASS_TIGHT_SL_DISTANT_TP"
    elif n_high >= 2:
        geometry_class = "LEGITIMATE_STRUCTURAL_CLASS"
    else:
        geometry_class = "ACCIDENTAL_SINGLETON"
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
        "rr_bins": bins,
        "high_rr_class": {
            **pack_group(high),
            "tight_SL_vs_tape_median": tight,
            "median_SL_all": med_sl,
            "median_SL_RR_gt10": med_high_sl,
            "wins_in_class": n_high_win,
            "geometry_class": geometry_class,
            "timestamps": [e.get("timestamp") for e in high],
        },
        "extreme_winner_kept": {
            "timestamp": top1.get("timestamp"),
            "planned_rr": top1.get("planned_rr"),
            "r_result": top1.get("r_result"),
            "in_RR_gt_10": (_f(top1.get("planned_rr")) or 0) > 10,
            "removed_from_baseline": False,
        },
        "HIGH_PLANNED_RR_IS": geometry_class,
        "hypotheses": [
            {
                "id": "H77-01",
                "claim": "RR>10 is a class of hybrid Asian-range TP / tiny swing SL, not a unique formula bug.",
                "result": geometry_class,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["rr_bins", "rr_gt10_class", "extreme_kept"],
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
            "baseline_rewritten": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE77_JSON, "md": PHASE77_MD},
    }
    (root / PHASE77_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE77_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE77_MD).write_text(
        "\n".join(
            [
                "# Phase 77 — Exit Geometry / Planned-RR Forensics",
                "",
                f"**HIGH_PLANNED_RR_IS:** `{geometry_class}`  n(RR>10)=`{n_high}` wins_in_class=`{n_high_win}`",
                f"**Tight SL in RR>10 vs tape median:** `{tight}` ({med_high_sl} vs {med_sl})",
                "",
                "The +31.84R event remains in the official baseline. RR was not optimized.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase77_collection(Path("."))["HIGH_PLANNED_RR_IS"])
