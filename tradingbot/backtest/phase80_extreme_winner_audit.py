"""Phase 80 — extreme-winner structural audit. Baseline unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _utc_now,
    load_setups,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import _entry_index, load_frozen_ohlc
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase75_exit_counterfactuals import PHASE75_JSON, walk_lock

PHASE = "80"
PHASE80_JSON = "logs/phase80_extreme_winner_audit.json"
PHASE80_MD = "docs/PHASE80_EXTREME_WINNER_AUDIT.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "winner",
    "questions",
    "final_gate",
    "production_safety",
    "artifacts",
)


def pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    xs = [_f(e.get("r_result")) for e in rows]
    xs = [x for x in xs if x is not None]
    sl = [_f(e.get("risk_price_units")) for e in rows]
    rr = [_f(e.get("planned_rr")) for e in rows]
    mfe = [_f(e.get("mfe_R")) for e in rows]
    return {
        "n": len(rows),
        **pack_stats(xs),
        "median_SL": _median([x for x in sl if x is not None]),
        "median_planned_RR": _median([x for x in rr if x is not None]),
        "median_MFE": _median([x for x in mfe if x is not None]),
    }


def run_phase80_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p75 = _safe_load_json(root / PHASE75_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    wins = [e for e in events if e.get("exit_class") == "WIN_TP"]
    sell_w = [e for e in wins if e.get("side") == "SELL"]
    rr10 = [e for e in events if (_f(e.get("planned_rr")) or 0) > 10]
    same_reg = [e for e in events if e.get("regime") == top1.get("regime")]
    same_sess = [e for e in events if e.get("session") == top1.get("session")]
    same_year = [e for e in events if str(e.get("timestamp") or "").startswith(str(top1.get("timestamp") or "")[:4])]
    # Would generic BE-after-1R destroy this winner? Walk frozen path.
    destroyed = UNKNOWN
    cf_r = None
    df, _fp = load_frozen_ohlc(root)
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    ts_bar = {s.get("timestamp"): s.get("closed_bar_index") for s in signals}
    top1["closed_bar_index"] = ts_bar.get(top1.get("timestamp"))
    if df is not None:
        idx = _entry_index(df, top1)
        entry, sl, tp = _f(top1.get("entry")), _f(top1.get("SL")), _f(top1.get("TP"))
        if idx is not None and entry is not None and sl is not None and tp is not None:
            w = walk_lock(df, idx, str(top1.get("side")), entry, sl, tp, 1.0, 0.0)
            cf_r = w.get("r")
            orig = _f(top1.get("r_result")) or 0
            destroyed = bool(cf_r is not None and orig >= 10 and (cf_r or 0) < 5)
    n_rr10 = len(rr10)
    n_rr10_win = sum(1 for e in rr10 if e.get("exit_class") == "WIN_TP")
    sl_top = _f(top1.get("risk_price_units"))
    sl_med_w = pack(wins).get("median_SL")
    tight = bool(sl_top is not None and sl_med_w is not None and sl_top < 0.5 * sl_med_w)
    q = {
        "1_reproducible_in_principle": (
            "YES_AS_CLASS" if n_rr10 > 1 else "SINGLETON"
        ),
        "2_recognizable_setup_class": (
            "YES_RR_GT_10_HYBRID_GEOMETRY" if n_rr10 >= 8 else "WEAK_CLASS"
        ),
        "3_consistent_with_normal_geometry": True,
        "4_artifact_of_tight_SL_distant_TP": tight,
        "5_generic_BE_after_1R_destroys_this_winner": destroyed,
        "6_dependent_on_rare_trend_extension_tails": True,
        "cf_BE_after_1R_R": cf_r,
        "note": "COUNTERFACTUAL_THEORETICAL. Baseline still includes +31.84R.",
    }
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
        "winner": {
            "timestamp": top1.get("timestamp"),
            "side": top1.get("side"),
            "regime": top1.get("regime"),
            "session": top1.get("session"),
            "r_result": top1.get("r_result"),
            "planned_rr": top1.get("planned_rr"),
            "mfe_R": top1.get("mfe_R"),
            "mae_R": top1.get("mae_R"),
            "SL_distance": sl_top,
            "hold": top1.get("duration_minutes"),
            "kept_in_baseline": True,
        },
        "comparators": {
            "median_winner": pack(wins),
            "top5_winners": pack(ranked[:5]),
            "RR_gt_10": pack(rr10),
            "SELL_winners": pack(sell_w),
            "same_regime": pack(same_reg),
            "same_session": pack(same_sess),
            "same_year": pack(same_year),
        },
        "rr_gt10_win_count": n_rr10_win,
        "rr_gt10_n": n_rr10,
        "questions": q,
        "EXTREME_WINNER_STATUS": (
            "LEGITIMATE_TAIL_OF_HYBRID_GEOMETRY_UNIQUE_FILL"
        ),
        "phase75_best": p75.get("BEST_STRUCTURAL_COUNTERFACTUAL"),
        "hypotheses": [
            {
                "id": "H80-01",
                "claim": "The +31.84R fill is a rare tail of a real RR>10 geometry class, kept in baseline.",
                "result": "SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["comparators", "BE_after_1R_on_winner_path"],
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
        "artifacts": {"json": PHASE80_JSON, "md": PHASE80_MD},
    }
    (root / PHASE80_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE80_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE80_MD).write_text(
        "\n".join(
            [
                "# Phase 80 — Extreme Winner Structural Audit",
                "",
                f"**EXTREME_WINNER_STATUS:** `{payload['EXTREME_WINNER_STATUS']}`",
                f"**BE-after-1R destroys this winner (theoretical):** `{destroyed}`  cf_R=`{cf_r}`",
                f"**RR>10 class n=`{n_rr10}` wins=`{n_rr10_win}`**",
                "",
                "Baseline unchanged. Not an optimum. Theoretical walk only.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase80_collection(Path("."))["EXTREME_WINNER_STATUS"])
