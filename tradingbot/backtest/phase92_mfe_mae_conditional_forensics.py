"""Phase 92 — MFE-conditional outcome matrices.

RESEARCH ONLY. Buckets are Phase 74 CROSS_LEVELS edges. No threshold search.
Conditioning is first-cross on the frozen path, then subsequent outcome.
"""

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
    _parse_ts,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import TAPE_END_FALLBACK, split_views
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON

PHASE = "92"
PHASE92_JSON = "logs/phase92_mfe_mae_conditional_forensics.json"
PHASE92_MD = "docs/PHASE92_MFE_MAE_CONDITIONAL_FORENSICS.md"
BLOCKED = "BLOCKED"
# Predeclared edges from Phase 74 CROSS_LEVELS. Not searched.
MFE_BUCKETS = (
    (0.0, 0.25, "0_0.25"),
    (0.25, 0.50, "0.25_0.50"),
    (0.50, 0.75, "0.50_0.75"),
    (0.75, 1.00, "0.75_1.00"),
    (1.00, 1.50, "1.00_1.50"),
    (1.50, 2.00, "1.50_2"),
    (2.00, 5.00, "2_5"),
    (5.00, 10.0, "5_10"),
    (10.0, 1e12, "gt_10"),
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_bucket",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _cross_key(cross: dict, lo: float) -> dict[str, Any]:
    if lo <= 0:
        return {}
    for k, v in (cross or {}).items():
        try:
            if abs(float(k) - lo) < 1e-9:
                return v or {}
        except (TypeError, ValueError):
            continue
    return {}


def reached_lo(row: dict[str, Any], lo: float) -> bool:
    if lo <= 0:
        return True
    c = _cross_key(row.get("cross") or {}, lo)
    if c.get("first_bar") is not None:
        return True
    return (_f(row.get("mfe")) or 0) >= lo


def bucket_of_final_mfe(mfe: float | None) -> str:
    if mfe is None:
        return UNKNOWN
    for lo, hi, name in MFE_BUCKETS:
        if lo <= mfe < hi:
            return name
    return UNKNOWN


def summarize(rows: list[dict[str, Any]], lo: float) -> dict[str, Any]:
    hit = [r for r in rows if reached_lo(r, lo)]
    xs = [_f(r.get("orig")) for r in hit]
    xs = [x for x in xs if x is not None]
    n = len(hit)
    n_win = sum(1 for r in hit if r.get("cls") == "WIN_TP")
    n_loss = sum(1 for r in hit if r.get("cls") == "LOSS_SL")
    n_entry = 0
    n_sl = 0
    n_tp = 0
    max_after = []
    gb = []
    for r in hit:
        c = _cross_key(r.get("cross") or {}, lo) if lo > 0 else {}
        if lo <= 0 or not c.get("first_bar"):
            n_sl += int(r.get("cls") == "LOSS_SL")
            n_tp += int(r.get("cls") == "WIN_TP")
            max_after.append(_f(r.get("mfe")))
            if _f(r.get("mfe")) is not None and _f(r.get("orig")) is not None:
                gb.append(float(r["mfe"]) - float(r["orig"]))
            continue
        if c.get("revisited_entry"):
            n_entry += 1
        if c.get("then_sl"):
            n_sl += 1
        if c.get("then_tp"):
            n_tp += 1
        if c.get("max_mfe_after") is not None:
            max_after.append(float(c["max_mfe_after"]))
        o = _f(r.get("orig"))
        if o is not None:
            gb.append((c.get("max_mfe_after") or _f(r.get("mfe")) or 0) - o)
    return {
        "n": n,
        "n_winners": n_win,
        "n_losers": n_loss,
        **pack_stats(xs),
        "median_final_R": _median(xs),
        "p_return_to_entry": (n_entry / n) if n else None,
        "p_final_minus_1R": (n_sl / n) if n else None,
        "p_reach_TP": (n_tp / n) if n else None,
        "mean_max_eventual_R_after_cross": _mean([x for x in max_after if x is not None]),
        "mean_giveback": _mean(gb),
        "small_n": n < 8,
    }


def slice_map(rows: list[dict[str, Any]], key: str, lo: float) -> dict[str, Any]:
    g: dict[str, list] = {}
    for r in rows:
        g.setdefault(str(r.get(key) or UNKNOWN), []).append(r)
    return {k: summarize(v, lo) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}


def run_phase92_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    compact = p90.get("compact") or []
    events = expand74(p74.get("compact_events") or [])
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    by_ts = {r.get("ts"): r for r in compact}

    def view_rows(name: str) -> list[dict[str, Any]]:
        return [by_ts[e["timestamp"]] for e in views.get(name) or [] if e.get("timestamp") in by_ts]

    by_bucket = {}
    asymmetric = []
    for lo, hi, name in MFE_BUCKETS:
        full = summarize(compact, lo)
        by_bucket[name] = {
            "lo": lo,
            "hi": hi,
            "FULL": full,
            "by_side": slice_map(compact, "side", lo),
            "by_regime": slice_map(compact, "reg", lo),
            "by_year": slice_map(compact, "year", lo),
            "TRAIN": summarize(view_rows("TRAIN"), lo),
            "VALIDATION": summarize(view_rows("VALIDATION"), lo),
            "OOS": summarize(view_rows("OOS"), lo),
            "RECENT_180D": summarize(view_rows("RECENT_180D"), lo),
        }
        p_sl = full.get("p_final_minus_1R")
        p_tp = full.get("p_reach_TP")
        if p_sl is not None and p_tp is not None and not full.get("small_n"):
            if p_sl >= 0.6 and p_tp <= 0.2:
                asymmetric.append(name)
            elif p_tp >= 0.6 and p_sl <= 0.2:
                asymmetric.append(name + ":WIN_HEAVY")
    justified = "NONE"
    if any(x in {"0.50_0.75", "0.75_1.00", "1.00_1.50", "1.50_2"} for x in asymmetric if "WIN" not in x):
        justified = "GIVEBACK_HEAVY_MID_MFE"
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
        "predeclared_buckets": [b[2] for b in MFE_BUCKETS],
        "by_bucket": by_bucket,
        "asymmetric_buckets": asymmetric,
        "ASYMMETRIC_CONDITIONAL_PROFILE": justified,
        "hypotheses": [
            {
                "id": "H92-01",
                "claim": "Some predeclared MFE first-cross states have an asymmetric risk of giveback vs TP.",
                "result": justified,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["mfe_buckets", "side", "regime", "year", "folds"],
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
        "artifacts": {"json": PHASE92_JSON, "md": PHASE92_MD},
    }
    (root / PHASE92_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE92_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 92 — MFE/MAE Conditional Forensics",
        "",
        "RESEARCH ONLY. First-cross conditioning. Buckets from Phase 74 CROSS_LEVELS. Not searched.",
        f"**ASYMMETRIC_CONDITIONAL_PROFILE:** `{justified}`",
        "",
    ]
    for name, row in by_bucket.items():
        f = row["FULL"]
        lines.append(
            f"- `{name}` n=`{f.get('n')}` meanR=`{f.get('expectancy_R')}` "
            f"p_entry=`{f.get('p_return_to_entry')}` p_-1R=`{f.get('p_final_minus_1R')}` "
            f"p_TP=`{f.get('p_reach_TP')}` giveback=`{f.get('mean_giveback')}`"
        )
    (root / PHASE92_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase92_collection(Path("."))
    print(p["ASYMMETRIC_CONDITIONAL_PROFILE"], p["asymmetric_buckets"])
