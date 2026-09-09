"""Phase 74 — profit-giveback path forensics.

RESEARCH ONLY. Frozen Phase 68 compact events + jsonl MFE/MAE.
Does not change strategy, SL/TP, or the frozen tape.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
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
from tradingbot.backtest.phase68_exit_forensics import (
    PHASE68_JSON,
    PROFIT_EPS,
    TAPE_END_FALLBACK,
    expand_compact,
    split_views,
)

PHASE = "74"
PHASE74_JSON = "logs/phase74_profit_giveback_forensics.json"
PHASE74_MD = "docs/PHASE74_PROFIT_GIVEBACK_FORENSICS.md"
BLOCKED = "BLOCKED"
# Predeclared nested loser classes. Not searched.
L_THRESH = (
    ("L0", None, 0.0),
    ("L1", 0.0, None),
    ("L2", 0.25, None),
    ("L3", 0.50, None),
    ("L4", 1.0, None),
    ("L5", 2.0, None),
    ("L6", 5.0, None),
)
CROSS_LEVELS = (0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00, 5.00, 10.0)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "loser_classes",
    "surrendered_profit",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _f(v: Any) -> float | None:
    try:
        if v is None or v == UNKNOWN:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_loser(mfe: float | None) -> list[str]:
    if mfe is None:
        return ["UNKNOWN"]
    labels: list[str] = []
    if mfe <= 0.0:
        labels.append("L0")
    if mfe > 0.0:
        labels.append("L1")
    if mfe >= 0.25:
        labels.append("L2")
    if mfe >= 0.50:
        labels.append("L3")
    if mfe >= 1.0:
        labels.append("L4")
    if mfe >= 2.0:
        labels.append("L5")
    if mfe >= 5.0:
        labels.append("L6")
    if mfe <= PROFIT_EPS and "L0" not in labels:
        labels.append("L0")
    return labels or ["L0"]


def crossed_levels(mfe: float | None) -> dict[str, bool]:
    out = {}
    for t in CROSS_LEVELS:
        out[str(t)] = bool(mfe is not None and mfe >= t)
    return out


def annotate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for e in events:
        row = dict(e)
        ts = _parse_ts(e.get("timestamp"))
        mfe = _f(e.get("mfe_R"))
        r = _f(e.get("r_result"))
        row["year"] = str(ts.year) if ts else UNKNOWN
        row["weekday"] = ts.strftime("%A") if ts else UNKNOWN
        row["hour_utc"] = ts.hour if ts else UNKNOWN
        row["L_class"] = classify_loser(mfe) if e.get("exit_class") == "LOSS_SL" else []
        row["crossed"] = crossed_levels(mfe)
        gb = _f(e.get("giveback_R"))
        if gb is None and mfe is not None and r is not None:
            gb = mfe - r
            row["giveback_R"] = gb
        row["retracement_R"] = gb
        if mfe is not None and mfe > 0 and gb is not None:
            row["retracement_pct_of_MFE"] = round(100.0 * gb / mfe, 4)
        else:
            row["retracement_pct_of_MFE"] = None
        out.append(row)
    return out


def class_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    n = len(losses)
    names = ("L0", "L1", "L2", "L3", "L4", "L5", "L6")
    out: dict[str, Any] = {}
    for name in names:
        rows = [e for e in losses if name in (e.get("L_class") or [])]
        mfes = [_f(e.get("mfe_R")) for e in rows]
        t_mfe = [_f(e.get("time_to_mfe_min")) for e in rows]
        t_rev = [_f(e.get("mins_mfe_to_exit")) for e in rows]
        gb = [_f(e.get("retracement_R")) for e in rows]
        pct = [_f(e.get("retracement_pct_of_MFE")) for e in rows]
        out[name] = {
            "count": len(rows),
            "frequency": (len(rows) / n) if n else None,
            "median_MFE": _median([x for x in mfes if x is not None]),
            "median_time_to_MFE": _median([x for x in t_mfe if x is not None]),
            "median_time_to_reversal": _median([x for x in t_rev if x is not None]),
            "median_retracement_R": _median([x for x in gb if x is not None]),
            "median_retracement_pct_of_MFE": _median([x for x in pct if x is not None]),
            "sides": dict(Counter(e.get("side") for e in rows)),
            "regimes": dict(Counter(e.get("regime") for e in rows)),
            "sessions": dict(Counter(e.get("session") for e in rows)),
            "years": dict(Counter(e.get("year") for e in rows)),
        }
    return out


def slice_class(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    losses = [e for e in rows if e.get("exit_class") == "LOSS_SL"]
    hit = [e for e in losses if name in (e.get("L_class") or [])]
    n = len(losses)
    return {"n_loss": n, "count": len(hit), "frequency": (len(hit) / n) if n else None}


def surrendered(events: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    fav = [e for e in losses if (_f(e.get("mfe_R")) or 0) > PROFIT_EPS]
    mfes = [_f(e.get("mfe_R")) for e in fav]
    mfes = [x for x in mfes if x is not None]
    gb = [_f(e.get("retracement_R")) for e in fav]
    gb = [x for x in gb if x is not None]
    l3 = [e for e in losses if (_f(e.get("mfe_R")) or 0) >= 0.5]
    l4 = [e for e in losses if (_f(e.get("mfe_R")) or 0) >= 1.0]
    return {
        "kind": "DERIVED_FROM_OBSERVED_MFE",
        "question": "How much unrealized profit is systematically being surrendered?",
        "n_LOSS_SL": len(losses),
        "n_first_favorable": len(fav),
        "sum_peak_MFE_R_among_favorable_losers": round(sum(mfes), 6) if mfes else 0.0,
        "median_peak_MFE_R_among_favorable_losers": _median(mfes),
        "median_retracement_R": _median(gb),
        "mean_retracement_R": _mean(gb),
        "PROFIT_GIVEBACK_RATE": (len(fav) / len(losses)) if losses else None,
        "LOSS_AFTER_0_5R": len(l3),
        "LOSS_AFTER_1R": len(l4),
        "note": (
            "A favorable loser surrenders its entire MFE plus the final -1R. "
            "Sum of peak MFE among those losers is unrealized R that never became realized R. "
            "Not a claim a trail existed."
        ),
    }


def compact74(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for e in events:
        rows.append(
            {
                "ts": e.get("timestamp"),
                "side": e.get("side"),
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
                "t_rev": e.get("mins_mfe_to_exit"),
                "gb": e.get("retracement_R"),
                "gb_pct": e.get("retracement_pct_of_MFE"),
                "year": e.get("year"),
                "wd": e.get("weekday"),
                "hour": e.get("hour_utc"),
                "L": e.get("L_class"),
                "crossed": e.get("crossed"),
                "n_sig": e.get("signal_count"),
                "vol": e.get("vol_class"),
                "sl_sess": e.get("sl_session_class"),
            }
        )
    return rows


def expand74(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for e in rows:
        out.append(
            {
                "timestamp": e.get("ts"),
                "side": e.get("side"),
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
                "mins_mfe_to_exit": e.get("t_rev"),
                "giveback_R": e.get("gb"),
                "retracement_R": e.get("gb"),
                "retracement_pct_of_MFE": e.get("gb_pct"),
                "year": e.get("year"),
                "weekday": e.get("wd"),
                "hour_utc": e.get("hour"),
                "L_class": e.get("L") or [],
                "crossed": e.get("crossed") or {},
                "signal_count": e.get("n_sig"),
                "vol_class": e.get("vol"),
                "sl_session_class": e.get("sl_sess"),
            }
        )
    return out


def run_phase74_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p68 = _safe_load_json(root / PHASE68_JSON) or {}
    events = annotate(expand_compact(p68.get("compact_events") or []))
    tape_end = _parse_ts(p68.get("tape_end")) or TAPE_END_FALLBACK
    views = split_views(events, tape_end)
    classes = class_report(events)
    surr = surrendered(events)
    crosses = {str(t): sum(1 for e in events if (e.get("crossed") or {}).get(str(t))) for t in CROSS_LEVELS}
    hyp = [
        {
            "id": "H74-01",
            "claim": "A majority of LOSS_SL events first print MFE>0, so failure is give-back of unrealized profit.",
            "result": "SUPPORTED" if (surr.get("PROFIT_GIVEBACK_RATE") or 0) > 0.5 else "NOT_SUPPORTED",
            "oos_used_for_decision": False,
        }
    ]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS" if len(events) == 419 else "FAIL",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "epistemic": {
            "mfe_mae": "OBSERVED_JSONL",
            "time_to_mfe": "DERIVED_PHASE68_PATH",
            "L_class": "DERIVED",
            "counterfactual": False,
        },
        "n_resolved": len(events),
        "LOSS_SL": sum(1 for e in events if e.get("exit_class") == "LOSS_SL"),
        "WIN_TP": sum(1 for e in events if e.get("exit_class") == "WIN_TP"),
        "loser_classes": classes,
        "crosses": crosses,
        "surrendered_profit": surr,
        "LOSS_AFTER_0_5R": surr["LOSS_AFTER_0_5R"],
        "LOSS_AFTER_1R": surr["LOSS_AFTER_1R"],
        "PROFIT_GIVEBACK_RATE": surr["PROFIT_GIVEBACK_RATE"],
        "MEDIAN_TIME_TO_REVERSAL": classes.get("L1", {}).get("median_time_to_reversal")
        or p68.get("MEDIAN_TIME_TO_REVERSAL"),
        "views": {
            name: {
                "L3_after_0.5R": slice_class(rows, "L3"),
                "L4_after_1R": slice_class(rows, "L4"),
                "expectancy": pack_stats([float(e["r_result"]) for e in rows if e.get("r_result") is not None]),
            }
            for name, rows in views.items()
        },
        "compact_events": compact74(events),
        "hypotheses": hyp,
        "tests_performed": 1,
        "diagnostics_run": ["L0_L6", "cross_levels", "surrendered_profit", "fold_slices"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "SL_TP": "NOT_CHANGED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE74_JSON, "md": PHASE74_MD},
        "tape_end": str(tape_end),
    }
    (root / PHASE74_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE74_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE74_MD).write_text(
        "\n".join(
            [
                "# Phase 74 — Profit Giveback Path Forensics",
                "",
                f"**PROFIT_GIVEBACK_RATE:** `{surr['PROFIT_GIVEBACK_RATE']}`",
                f"**LOSS_AFTER_0.5R (L3):** `{surr['LOSS_AFTER_0_5R']}`  **LOSS_AFTER_1R (L4):** `{surr['LOSS_AFTER_1R']}`",
                f"**Median peak MFE among favorable losers:** `{surr['median_peak_MFE_R_among_favorable_losers']}`",
                f"**Sum of peak MFE surrendered (favorable losers):** `{surr['sum_peak_MFE_R_among_favorable_losers']}` R",
                "",
                "Nested loser classes L0-L6 are predeclared. Strategy was not changed.",
                "Unrealized peak MFE among stop-outs is surrendered profit, not a trailing-stop result.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase74_collection(Path("."))
    print(p["PROFIT_GIVEBACK_RATE"], p["LOSS_AFTER_0_5R"], p["LOSS_AFTER_1R"])
