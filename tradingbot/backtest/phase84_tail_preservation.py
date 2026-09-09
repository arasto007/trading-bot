"""Phase 84 — right-tail preservation diagnostic.

The +31.84R winner is an independent diagnostic, not a tuning target.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _mean, _utc_now
from tradingbot.backtest.phase68_exit_forensics import EXTREME_R, TAPE_END_FALLBACK, split_views
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, TESTABLE_FAMILIES

PHASE = "84"
PHASE84_JSON = "logs/phase84_tail_preservation.json"
PHASE84_MD = "docs/PHASE84_TAIL_PRESERVATION.md"
BLOCKED = "BLOCKED"
ALLOWED_TAIL = ("PRESERVED", "PARTIALLY_PRESERVED", "DESTROYED", "DATA_LIMITED")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_family",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _label(orig: float | None, cf: float | None) -> str:
    if orig is None or cf is None:
        return "DATA_LIMITED"
    if orig >= EXTREME_R:
        if cf >= EXTREME_R:
            return "PRESERVED"
        # Unique half of a 10R+ fill is still extreme; clipping below that destroys the tail.
        if cf >= 0.5 * orig and cf > 0:
            return "PARTIALLY_PRESERVED"
        return "DESTROYED"
    if orig > 0 and cf >= orig:
        return "PRESERVED"
    if orig > 0 and cf > 0:
        return "PARTIALLY_PRESERVED"
    if orig > 0 and cf <= 0:
        return "DESTROYED"
    return "DATA_LIMITED"


def _cohort_pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    orig = [_f(r.get("orig")) for r in rows]
    cf = [_f(r.get("cf")) for r in rows]
    pairs = [(a, b) for a, b in zip(orig, cf) if a is not None and b is not None]
    if not pairs:
        return {"n": 0, "status": "DATA_LIMITED"}
    ox, cx = [a for a, _ in pairs], [b for _, b in pairs]
    preserved_frac = [(b / a) if a else None for a, b in pairs if a and a > 0]
    pf = [x for x in preserved_frac if x is not None]
    return {
        "n": len(pairs),
        "orig_mean_R": _mean(ox),
        "cf_mean_R": _mean(cx),
        "median_preserved_frac": None if not pf else sorted(pf)[len(pf) // 2],
        "n_still_gt_10": sum(1 for b in cx if b >= EXTREME_R),
        "n_still_winner": sum(1 for b in cx if b > 0),
        "n_cf_le_0": sum(1 for b in cx if b <= 0),
        "exits": {str(r.get("exit")): sum(1 for x in rows if x.get("exit") == r.get("exit")) for r in rows},
    }


def analyze_family(name: str, walks: list[dict[str, Any]], events: list[dict[str, Any]], views: dict) -> dict[str, Any]:
    by_ts = {w.get("ts"): w for w in walks}
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    w1 = by_ts.get(top1.get("timestamp")) or {}
    orig1 = _f(top1.get("r_result"))
    cf1 = _f(w1.get("cf"))
    tail = _label(orig1, cf1)
    top5 = ranked[:5]
    rr10 = [e for e in events if (_f(e.get("r_result")) or 0) >= EXTREME_R or (_f(e.get("planned_rr")) or 0) > 10]
    sell_w = [e for e in events if e.get("side") == "SELL" and (_f(e.get("r_result")) or 0) > 0]
    y2026 = [e for e in events if str(e.get("timestamp") or "").startswith("2026") and (_f(e.get("r_result")) or 0) > 0]
    oos_w = [e for e in views.get("OOS") or [] if (_f(e.get("r_result")) or 0) > 0]
    ordinary = [e for e in events if 0 < (_f(e.get("r_result")) or 0) < EXTREME_R]

    def rows_for(subset: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [by_ts[e["timestamp"]] for e in subset if e.get("timestamp") in by_ts]

    exited_before_tail = bool(w1.get("exit") not in {None, "tp", "fallback"} and (cf1 or 0) < (orig1 or 0))
    preserved_move = None if not orig1 else (None if cf1 is None else cf1 / orig1)
    ordinary_rows = rows_for(ordinary)
    ord_still = sum(1 for r in ordinary_rows if (_f(r.get("cf")) or 0) > 0)
    systematic = False
    if ordinary_rows:
        frac = []
        for r in ordinary_rows:
            o, c = _f(r.get("orig")), _f(r.get("cf"))
            if o and o > 0 and c is not None:
                frac.append(c / o)
        if frac:
            systematic = (sum(1 for x in frac if x < 0.5) / len(frac)) >= 0.5
    return {
        "name": name,
        "TAIL_PRESERVATION": tail,
        "outlier": {
            "timestamp": top1.get("timestamp"),
            "side": top1.get("side"),
            "orig_R": orig1,
            "cf_R": cf1,
            "exit": w1.get("exit"),
            "armed": w1.get("armed"),
            "ambiguous": w1.get("amb"),
            "exited_before_tail_expansion": exited_before_tail,
            "preserved_frac_of_eventual_move": preserved_move,
        },
        "top5": _cohort_pack(rows_for(top5)),
        "rr_gt_10": _cohort_pack(rows_for(rr10)),
        "SELL_winners": _cohort_pack(rows_for(sell_w)),
        "winners_2026": _cohort_pack(rows_for(y2026)),
        "OOS_winners": _cohort_pack(rows_for(oos_w)),
        "ordinary_winners_still_positive": {"n": len(ordinary_rows), "still_gt_0": ord_still},
        "systematically_truncates_right_tail": systematic or tail == "DESTROYED",
        "not_retuned_to_save_outlier": True,
    }


def run_phase84_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p83 = _safe_load_json(root / PHASE83_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    from tradingbot.backtest.phase61_edge_survival_forensics import _parse_ts

    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    walks = p83.get("walks") or {}
    by_family = {}
    for name in list(TESTABLE_FAMILIES) + (["HYBRID"] if p83.get("hybrid_created") else []):
        w = walks.get(name) or []
        if not w:
            by_family[name] = {"name": name, "TAIL_PRESERVATION": "DATA_LIMITED"}
            continue
        by_family[name] = analyze_family(name, w, events, views)
    by_family["ATR_NORMALIZED_RETRACE"] = {"name": "ATR_NORMALIZED_RETRACE", "TAIL_PRESERVATION": "DATA_LIMITED"}
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
        "outlier_kept_in_baseline": True,
        "by_family": by_family,
        "hypotheses": [
            {
                "id": "H84-01",
                "claim": "Each predeclared protection family can be scored for tail preservation without retuning.",
                "result": {k: v.get("TAIL_PRESERVATION") for k, v in by_family.items()},
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": list(by_family.keys()),
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
        "artifacts": {"json": PHASE84_JSON, "md": PHASE84_MD},
    }
    (root / PHASE84_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE84_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 84 — Right-Tail Preservation",
        "",
        "The +31.84R event is a diagnostic, not a tuning target. Baseline unchanged. Not optimal.",
        "",
    ]
    for name, row in by_family.items():
        out = row.get("outlier") or {}
        lines.append(
            f"- `{name}`: TAIL_PRESERVATION=`{row.get('TAIL_PRESERVATION')}` "
            f"outlier orig=`{out.get('orig_R')}` cf=`{out.get('cf_R')}` exit=`{out.get('exit')}` "
            f"preserved_frac=`{out.get('preserved_frac_of_eventual_move')}`"
        )
    (root / PHASE84_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase84_collection(Path("."))
    print({k: v.get("TAIL_PRESERVATION") for k, v in p["by_family"].items()})
