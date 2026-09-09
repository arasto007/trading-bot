"""Phase 86 — TRAIN / VAL / OOS / recent-180d causal consistency.

OOS is reported, never used to select. Top-1 / top-5 removals are diagnostics only.
Official baseline is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    _git_head,
    _mean,
    _parse_ts,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import TAPE_END_FALLBACK, split_views
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, TESTABLE_FAMILIES
from tradingbot.backtest.phase84_tail_preservation import PHASE84_JSON

PHASE = "86"
PHASE86_JSON = "logs/phase86_profit_protection_oos.json"
PHASE86_MD = "docs/PHASE86_PROFIT_PROTECTION_OOS.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_family",
    "oos_used_for_selection",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _sign(delta: float | None) -> str:
    if delta is None:
        return "INSUFFICIENT"
    if delta > 0:
        return "POS"
    if delta < 0:
        return "NEG"
    return "NEUTRAL"


def _delta_from_walks(walks: list[dict[str, Any]], ts_set: set[str] | None = None) -> dict[str, Any]:
    rows = [w for w in walks if ts_set is None or w.get("ts") in ts_set]
    ox, cx = [], []
    for w in rows:
        o, c = _f(w.get("orig")), _f(w.get("cf"))
        if o is None or c is None:
            continue
        ox.append(o)
        cx.append(c)
    if not ox:
        return {"n": 0, "delta_expectancy": None, "sign": "INSUFFICIENT"}
    d = _mean(cx) - _mean(ox)
    return {"n": len(ox), "orig_exp": _mean(ox), "cf_exp": _mean(cx), "delta_expectancy": d, "sign": _sign(d)}


def evaluate_family(
    name: str,
    walks: list[dict[str, Any]],
    views: dict[str, list[dict[str, Any]]],
    top1_ts: str | None,
    top5_ts: set[str],
    p83_status: str | None,
    tail: str | None,
) -> dict[str, Any]:
    def ts(rows: list[dict[str, Any]]) -> set[str]:
        return {e.get("timestamp") for e in rows if e.get("timestamp")}

    folds = {
        "TRAIN": _delta_from_walks(walks, ts(views["TRAIN"])),
        "VALIDATION": _delta_from_walks(walks, ts(views["VALIDATION"])),
        "OOS": _delta_from_walks(walks, ts(views["OOS"])),
        "RECENT_180D": _delta_from_walks(walks, ts(views["RECENT_180D"])),
        "FULL": _delta_from_walks(walks, None),
        "WITHOUT_TOP1": _delta_from_walks(walks, None if not top1_ts else {w.get("ts") for w in walks if w.get("ts") != top1_ts}),
        "WITHOUT_TOP5": _delta_from_walks(walks, {w.get("ts") for w in walks if w.get("ts") not in top5_ts}),
    }
    train_pos = folds["TRAIN"]["sign"] == "POS"
    val_pos = folds["VALIDATION"]["sign"] == "POS"
    survives = bool(p83_status == "HELPFUL" and tail not in {"DESTROYED", "DATA_LIMITED"} and train_pos and val_pos)
    return {
        "name": name,
        "phase83_status": p83_status,
        "TAIL_PRESERVATION": tail,
        "folds": folds,
        "TRAIN_improves": train_pos,
        "VAL_improves": val_pos,
        "OOS_improves": folds["OOS"]["sign"] == "POS",
        "RECENT_180D_improves": folds["RECENT_180D"]["sign"] == "POS",
        "useful_without_top1": folds["WITHOUT_TOP1"]["sign"] == "POS",
        "useful_without_top5": folds["WITHOUT_TOP5"]["sign"] == "POS",
        "directional_TRAIN_VAL": train_pos and val_pos,
        "survives": survives,
        "full_horizon_not_used_as_robustness": True,
        "oos_used_for_selection": False,
        "baseline_unchanged": True,
    }


def run_phase86_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p83 = _safe_load_json(root / PHASE83_JSON) or {}
    p84 = _safe_load_json(root / PHASE84_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1_ts = ranked[0].get("timestamp") if ranked else None
    top5_ts = {e.get("timestamp") for e in ranked[:5] if e.get("timestamp")}
    walks = p83.get("walks") or {}
    cfs = p83.get("counterfactuals") or {}
    tails = p84.get("by_family") or {}
    names = list(TESTABLE_FAMILIES)
    if p83.get("hybrid_created"):
        names.append("HYBRID")
    by_family = {}
    for name in names:
        w = walks.get(name) or []
        by_family[name] = evaluate_family(
            name,
            w,
            views,
            top1_ts,
            top5_ts,
            (cfs.get(name) or {}).get("status"),
            (tails.get(name) or {}).get("TAIL_PRESERVATION"),
        )
    by_family["ATR_NORMALIZED_RETRACE"] = {
        "name": "ATR_NORMALIZED_RETRACE",
        "survives": False,
        "phase83_status": "DATA_LIMITED",
        "TAIL_PRESERVATION": "DATA_LIMITED",
    }
    survivors = [n for n, v in by_family.items() if v.get("survives")]
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
        "by_family": by_family,
        "survivors": survivors,
        "top1_top5_are_diagnostics_only": True,
        "official_baseline_unchanged": True,
        "oos_used_for_selection": False,
        "hypotheses": [
            {
                "id": "H86-01",
                "claim": "Robustness requires TRAIN and VAL directional improvement; full-horizon gain is not enough.",
                "result": survivors,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": list(by_family.keys()),
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
        "artifacts": {"json": PHASE86_JSON, "md": PHASE86_MD},
    }
    (root / PHASE86_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE86_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 86 — Profit-Protection OOS Consistency",
        "",
        "OOS reported, not used to select. Top-1/top-5 removals are diagnostics. Baseline unchanged.",
        f"Survivors (HELPFUL + tail not DESTROYED + TRAIN and VAL POS): `{survivors}`",
        "",
    ]
    for name, row in by_family.items():
        folds = row.get("folds") or {}
        lines.append(
            f"- `{name}` survives=`{row.get('survives')}` TRAIN=`{(folds.get('TRAIN') or {}).get('sign')}` "
            f"VAL=`{(folds.get('VALIDATION') or {}).get('sign')}` OOS=`{(folds.get('OOS') or {}).get('sign')}` "
            f"RECENT=`{(folds.get('RECENT_180D') or {}).get('sign')}` "
            f"without_top1=`{row.get('useful_without_top1')}` without_top5=`{row.get('useful_without_top5')}`"
        )
    (root / PHASE86_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase86_collection(Path("."))
    print(p["survivors"])
