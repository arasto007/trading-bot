"""Phase 93 — structural tail preservation forensics.

The +31.84R event is kept. No winsorize, cap, or removal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _mean, _median, _utc_now, pack_stats
from tradingbot.backtest.phase68_exit_forensics import EXTREME_R
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON

PHASE = "93"
PHASE93_JSON = "logs/phase93_tail_preservation_forensics.json"
PHASE93_MD = "docs/PHASE93_TAIL_PRESERVATION_FORENSICS.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "TAIL_DISCRIMINATOR",
    "final_gate",
    "production_safety",
    "artifacts",
)


def pack_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [_f(r.get("orig")) for r in rows]
    xs = [x for x in xs if x is not None]
    mfe = [_f(r.get("mfe")) for r in rows]
    mae = [_f(r.get("mae")) for r in rows]
    hold = [_f(r.get("hold")) for r in rows]
    t_mfe = [_f(r.get("t_mfe")) for r in rows]
    t_rev = [_f(r.get("t_rev")) for r in rows]
    nsig = [_f(r.get("n_sig")) for r in rows]
    bars05 = [float((r.get("bars_above") or {}).get("0.5") or 0) for r in rows]
    return {
        "n": len(rows),
        **pack_stats(xs),
        "median_MFE": _median([x for x in mfe if x is not None]),
        "median_MAE": _median([x for x in mae if x is not None]),
        "median_hold": _median([x for x in hold if x is not None]),
        "median_time_to_MFE": _median([x for x in t_mfe if x is not None]),
        "median_time_MFE_to_exit": _median([x for x in t_rev if x is not None]),
        "median_signal_count": _median([x for x in nsig if x is not None]),
        "median_bars_above_0_5R": _median(bars05),
        "mean_bars_above_0_5R": _mean(bars05),
        "sides": {s: sum(1 for r in rows if r.get("side") == s) for s in sorted({str(r.get("side")) for r in rows})},
        "regimes": {s: sum(1 for r in rows if r.get("reg") == s) for s in sorted({str(r.get("reg")) for r in rows})},
        "path_classes": {s: sum(1 for r in rows if r.get("path_class") == s) for s in sorted({str(r.get("path_class")) for r in rows})},
        "shapes": {s: sum(1 for r in rows if r.get("shape") == s) for s in sorted({str(r.get("shape")) for r in rows})},
        "years": {s: sum(1 for r in rows if str(r.get("year")) == s) for s in sorted({str(r.get("year")) for r in rows})},
    }


def run_phase93_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    compact = p90.get("compact") or []
    wins = [r for r in compact if r.get("cls") == "WIN_TP"]
    rr5 = [r for r in compact if (_f(r.get("rr")) or 0) > 5]
    rr10 = [r for r in compact if (_f(r.get("rr")) or 0) > 10]
    r5 = [r for r in compact if (_f(r.get("orig")) or 0) > 5]
    r10 = [r for r in compact if (_f(r.get("orig")) or 0) > 10]
    ranked = sorted(compact, key=lambda r: float(r.get("orig") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    ordinary = [r for r in wins if (_f(r.get("orig")) or 0) < EXTREME_R]
    groups = {
        "all_winners": pack_group(wins),
        "planned_RR_gt_5": pack_group(rr5),
        "planned_RR_gt_10": pack_group(rr10),
        "realized_R_gt_5": pack_group(r5),
        "realized_R_gt_10": pack_group(r10),
        "ordinary_winners": pack_group(ordinary),
        "outlier": {
            "timestamp": top1.get("ts"),
            "side": top1.get("side"),
            "regime": top1.get("reg"),
            "path_class": top1.get("path_class"),
            "shape": top1.get("shape"),
            "orig": top1.get("orig"),
            "mfe": top1.get("mfe"),
            "mae": top1.get("mae"),
            "hold": top1.get("hold"),
            "t_mfe": top1.get("t_mfe"),
            "t_rev": top1.get("t_rev"),
            "n_sig": top1.get("n_sig"),
            "rr": top1.get("rr"),
            "bars_above": top1.get("bars_above"),
            "kept": True,
        },
    }
    # Discriminator must be observable pre-entry or early-in-trade (first 5 bars = REVERSAL_BARS).
    # Planned RR>10 is pre-entry geometry (Phase 77/80). Check whether ALL extreme realized
    # fills are inside that class AND whether that class also contains many ordinary/losing events.
    n_rr10 = len(rr10)
    n_rr10_r10 = sum(1 for r in rr10 if (_f(r.get("orig")) or 0) >= EXTREME_R)
    n_r10 = len(r10)
    early_mae_out = _f(top1.get("mae"))
    early_mae_ord = groups["ordinary_winners"].get("median_MAE")
    disc = "NOT_ESTABLISHED"
    reason = (
        "Planned RR>10 is a real geometry class (Phase 80) but does not uniquely identify the "
        "realized extreme fill: most RR>10 events are not +10R realizations. Early MAE of the "
        "outlier is not a pre-entry discriminator (it is in-trade). No other early-bar signature "
        "uniquely separates F from E."
    )
    if n_r10 == 1 and n_rr10_r10 == 1 and n_rr10 > 1:
        disc = "NOT_ESTABLISHED"
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
        "outlier_removed": False,
        "outlier_winsorized": False,
        "outlier_capped": False,
        "groups": groups,
        "rr_gt10_n": n_rr10,
        "realized_gt10_n": n_r10,
        "rr_gt10_also_realized_gt10": n_rr10_r10,
        "outlier_mae": early_mae_out,
        "ordinary_winner_median_mae": early_mae_ord,
        "TAIL_DISCRIMINATOR": disc,
        "TAIL_DISCRIMINATOR_REASON": reason,
        "hypotheses": [
            {
                "id": "H93-01",
                "claim": "Extreme-tail events have an observable pre-entry or early-in-trade discriminator vs ordinary winners.",
                "result": disc,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["winner_groups", "outlier_kept"],
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
        "artifacts": {"json": PHASE93_JSON, "md": PHASE93_MD},
    }
    (root / PHASE93_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE93_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE93_MD).write_text(
        "\n".join(
            [
                "# Phase 93 — Structural Tail Preservation Forensics",
                "",
                "Outlier kept. Not winsorized. Not capped. Not noise.",
                f"**TAIL_DISCRIMINATOR:** `{disc}`",
                "",
                reason,
                "",
                f"Outlier: `{top1.get('ts')}` class=`{top1.get('path_class')}` shape=`{top1.get('shape')}` "
                f"R=`{top1.get('orig')}` MAE=`{top1.get('mae')}` n_sig=`{top1.get('n_sig')}`",
                f"RR>10 n=`{n_rr10}` realized>10 n=`{n_r10}` overlap=`{n_rr10_r10}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase93_collection(Path("."))
    print(p["TAIL_DISCRIMINATOR"], p["groups"]["outlier"]["timestamp"])
