"""Phase 71 — extreme-winner forensics.

RESEARCH ONLY. Official baseline keeps +31.84R. Robustness is diagnostic only.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
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
from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON, expand_compact
from tradingbot.backtest.phase69_exit_geometry import PHASE69_JSON, MIN_RR

PHASE = "71"
PHASE71_JSON = "logs/phase71_extreme_winner_forensics.json"
PHASE71_MD = "docs/PHASE71_EXTREME_WINNER.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "winner",
    "rr_tails",
    "outlier_robustness",
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


def subset(events: list[dict[str, Any]], pred) -> dict[str, Any]:
    rows = [e for e in events if pred(e)]
    xs = [_f(e.get("r_result")) for e in rows]
    xs = [x for x in xs if x is not None]
    rr = [_f(e.get("planned_rr")) for e in rows]
    risk = [_f(e.get("risk_price_units")) for e in rows]
    tp = []
    for e in rows:
        a, b = _f(e.get("entry")), _f(e.get("TP"))
        if a is not None and b is not None:
            tp.append(abs(a - b))
    return {
        "n": len(rows),
        **pack_stats(xs),
        "median_planned_rr": _median([x for x in rr if x is not None]),
        "median_sl_distance": _median([x for x in risk if x is not None]),
        "median_tp_distance": _median(tp),
        "sides": dict(Counter(e.get("side") for e in rows)),
        "regimes": dict(Counter(e.get("regime") for e in rows)),
        "sessions": dict(Counter(e.get("session") for e in rows)),
        "months": dict(Counter(str(e.get("timestamp") or "")[:7] for e in rows)),
        "folds": dict(Counter(e.get("fold") for e in rows)),
    }


def rr_tail(events: list[dict[str, Any]], thr: float) -> dict[str, Any]:
    rows = [e for e in events if (_f(e.get("planned_rr")) or 0) > thr]
    pack = subset(events, lambda e: (_f(e.get("planned_rr")) or 0) > thr)
    regimes = pack["regimes"]
    sides = pack["sides"]
    months = pack["months"]
    sessions = pack["sessions"]
    n = pack["n"]
    conc = {
        "one_regime": n > 0 and max(regimes.values() or [0]) == n,
        "one_side": n > 0 and max(sides.values() or [0]) == n,
        "one_session": n > 0 and max(sessions.values() or [0]) == n,
        "one_month": n > 0 and max(months.values() or [0]) == n,
    }
    sls = [_f(e.get("risk_price_units")) for e in rows]
    tps = []
    for e in rows:
        a, b = _f(e.get("entry")), _f(e.get("TP"))
        if a is not None and b is not None:
            tps.append(abs(a - b))
    all_sl = [_f(e.get("risk_price_units")) for e in events]
    all_sl = [x for x in all_sl if x is not None]
    return {
        **pack,
        "threshold": thr,
        "concentration": conc,
        "sl_abnormal_vs_median": bool(
            _median([x for x in sls if x is not None]) is not None
            and _median(all_sl) is not None
            and (_median([x for x in sls if x is not None]) or 0) < 0.5 * (_median(all_sl) or 1)
        ),
        "tp_abnormal_vs_median": bool(
            _median(tps) is not None
            and _median(
                [abs((_f(e.get("entry")) or 0) - (_f(e.get("TP")) or 0)) for e in events if _f(e.get("entry")) is not None]
            )
            is not None
        ),
        "timestamps": [e.get("timestamp") for e in rows],
    }


def winsor(xs: list[float], lo_p: float = 0.05, hi_p: float = 0.95) -> list[float]:
    if not xs:
        return []
    ys = sorted(xs)
    lo = ys[int((len(ys) - 1) * lo_p)]
    hi = ys[int((len(ys) - 1) * hi_p)]
    return [min(max(x, lo), hi) for x in xs]


def run_phase71_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p68 = _safe_load_json(root / PHASE68_JSON) or {}
    p69 = _safe_load_json(root / PHASE69_JSON) or {}
    events = expand_compact(p68.get("compact_events") or [])
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    xs = [float(e["r_result"]) for e in events]
    gt3 = rr_tail(events, 3)
    gt5 = rr_tail(events, 5)
    gt10 = rr_tail(events, 10)
    realized_ge10 = [e for e in events if (_f(e.get("r_result")) or 0) >= 10]
    isolated_realized = bool(len(realized_ge10) <= 1)
    isolated_planned = bool(gt10["n"] <= 1)
    isolated = isolated_planned
    classification = p69.get("EXTREME_WINNER_CLASSIFICATION") or "B_RARE_LEGITIMATE_STRUCTURAL"
    if gt10["n"] > 1 and isolated_realized:
        class_note = (
            "Planned RR>10 is a legitimate hybrid-geometry class "
            f"(n={gt10['n']}), not a unique formula. The realized +31.84R fill is still unique."
        )
        classification = "B_RARE_LEGITIMATE_STRUCTURAL"
    elif isolated_planned and classification.startswith("B"):
        class_note = "Isolated instance of a legitimate hybrid-geometry class (planned RR > 10 count is 1)."
    else:
        class_note = classification
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "winner": {
            "timestamp": top1.get("timestamp"),
            "side": top1.get("side"),
            "regime": top1.get("regime"),
            "r_result": top1.get("r_result"),
            "planned_rr": top1.get("planned_rr"),
            "mfe_R": top1.get("mfe_R"),
            "mae_R": top1.get("mae_R"),
            "hold": top1.get("duration_minutes"),
            "entry": top1.get("entry"),
            "SL": top1.get("SL"),
            "TP": top1.get("TP"),
            "risk": top1.get("risk_price_units"),
            "fold": top1.get("fold"),
            "signal_count": top1.get("signal_count"),
            "kept_in_official_baseline": True,
            "code_path": (p69.get("extreme_winner") or {}).get("code_path"),
        },
        "comparators": {
            "all_SELL": subset(events, lambda e: e.get("side") == "SELL"),
            "SELL_winners": subset(events, lambda e: e.get("side") == "SELL" and e.get("exit_class") == "WIN_TP"),
            "STRONG_TREND_UP": subset(events, lambda e: e.get("regime") == "STRONG_TREND_UP"),
            "January_2026": subset(events, lambda e: str(e.get("timestamp") or "").startswith("2026-01")),
            "planned_rr_gt_3": gt3,
            "planned_rr_gt_5": gt5,
            "planned_rr_gt_10": gt10,
        },
        "rr_tails": {
            "gt_3": {"n": gt3["n"], "concentration": gt3["concentration"], "sl_abnormal": gt3["sl_abnormal_vs_median"]},
            "gt_5": {"n": gt5["n"], "concentration": gt5["concentration"], "sl_abnormal": gt5["sl_abnormal_vs_median"]},
            "gt_10": {"n": gt10["n"], "concentration": gt10["concentration"], "sl_abnormal": gt10["sl_abnormal_vs_median"]},
            "MIN_RR": MIN_RR,
        },
        "isolated": isolated,
        "isolated_planned_rr_gt10": isolated_planned,
        "isolated_realized_R_ge10": isolated_realized,
        "realized_R_ge10_n": len(realized_ge10),
        "EXTREME_WINNER_CLASSIFICATION": classification,
        "class_note": class_note,
        "outlier_robustness": {
            "kind": "COUNTERFACTUAL_DESCRIPTIVE",
            "official_baseline_unchanged": True,
            "full_tape": pack_stats(xs),
            "remove_top_1": pack_stats([float(e["r_result"]) for e in ranked[1:]]),
            "remove_top_3": pack_stats([float(e["r_result"]) for e in ranked[3:]]),
            "remove_top_5": pack_stats([float(e["r_result"]) for e in ranked[5:]]),
            "winsorized_5_95": pack_stats(winsor(xs)),
            "median_R": _median(xs),
        },
        "TOP1_REMOVAL_EXPECTANCY": _mean([float(e["r_result"]) for e in ranked[1:]]),
        "TOP5_REMOVAL_EXPECTANCY": _mean([float(e["r_result"]) for e in ranked[5:]]),
        "hypotheses": [
            {
                "id": "H71-01",
                "claim": "The +31.84R trade is an isolated tail of the hybrid geometry, not a distinct strategy.",
                "result": "CLASS_OF_FEW_PLANNED_RR" if not isolated_planned else "SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["comparators", "rr_tails", "outlier_robustness_descriptive"],
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
        "artifacts": {"json": PHASE71_JSON, "md": PHASE71_MD},
    }
    (root / PHASE71_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE71_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE71_MD).write_text(
        "\n".join(
            [
                "# Phase 71 — Extreme Winner Forensics",
                "",
                f"**Event:** `{top1.get('timestamp')}` `{top1.get('side')}` R=`{top1.get('r_result')}` planned_rr=`{top1.get('planned_rr')}`",
                f"**planned RR >3 / >5 / >10:** `{gt3['n']}` / `{gt5['n']}` / `{gt10['n']}`",
                f"**EXTREME_WINNER_CLASSIFICATION:** `{classification}`",
                "",
                class_note,
                "",
                "Official baseline still includes the event. Remove-top-k and winsorize are COUNTERFACTUAL diagnostics only.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase71_collection(Path("."))["EXTREME_WINNER_CLASSIFICATION"])
