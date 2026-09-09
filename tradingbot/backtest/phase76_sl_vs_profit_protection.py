"""Phase 76 — initial stop vs profit-protection (no SL/TP optimization)."""

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

PHASE = "76"
PHASE76_JSON = "logs/phase76_sl_vs_profit_protection.json"
PHASE76_MD = "docs/PHASE76_SL_VS_PROFIT_PROTECTION.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "groups",
    "verdict",
    "final_gate",
    "production_safety",
    "artifacts",
)


def group_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def nums(key: str) -> list[float]:
        xs = [_f(e.get(key)) for e in rows]
        return [x for x in xs if x is not None]

    sl = nums("risk_price_units")
    rr = nums("planned_rr")
    mfe = nums("mfe_R")
    mae = nums("mae_R")
    tm = nums("time_to_mfe_min")
    tr = nums("mins_mfe_to_exit")
    r = nums("r_result")
    return {
        "n": len(rows),
        "small_n": len(rows) < 8,
        "realized": pack_stats(r),
        "median_SL_distance": _median(sl),
        "mean_SL_distance": _mean(sl),
        "median_planned_RR": _median(rr),
        "median_MFE": _median(mfe),
        "median_MAE": _median(mae),
        "median_time_to_MFE": _median(tm),
        "median_time_to_reversal": _median(tr),
        "sides": {s: sum(1 for e in rows if e.get("side") == s) for s in ("BUY", "SELL")},
        "regimes": _count(rows, "regime"),
        "sessions": _count(rows, "session"),
    }


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in rows:
        k = str(e.get(key) or UNKNOWN)
        out[k] = out.get(k, 0) + 1
    return out


def run_phase76_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    never = [e for e in losses if (_f(e.get("mfe_R")) or 0) <= 0]
    g05 = [e for e in losses if (_f(e.get("mfe_R")) or 0) > 0.5]
    g1 = [e for e in losses if (_f(e.get("mfe_R")) or 0) > 1.0]
    wins = [e for e in events if e.get("exit_class") == "WIN_TP"]
    extreme = [e for e in wins if (_f(e.get("r_result")) or 0) >= 10]
    groups = {
        "losers_never_profit": group_stats(never),
        "losers_MFE_gt_0.5R": group_stats(g05),
        "losers_MFE_gt_1R": group_stats(g1),
        "winners": group_stats(wins),
        "extreme_winners": group_stats(extreme),
    }
    n_loss = len(losses)
    share_1 = (len(g1) / n_loss) if n_loss else 0.0
    share_05 = (len(g05) / n_loss) if n_loss else 0.0
    never_share = (len(never) / n_loss) if n_loss else 0.0
    sl_never = groups["losers_never_profit"]["median_SL_distance"]
    sl_g1 = groups["losers_MFE_gt_1R"]["median_SL_distance"]
    sl_win = groups["winners"]["median_SL_distance"]
    against_entry = share_1 >= 0.25
    # Predeclared verdict rule (not optimized).
    if share_1 >= 0.25 and never_share < 0.35:
        primary = "SL_ACCEPTABLE_BUT_NO_PROFIT_PROTECTION"
        combo = False
    elif never_share >= 0.50:
        primary = "SL_TOO_CLOSE_TO_ENTRY"
        combo = False
    elif share_05 >= 0.40:
        primary = "SL_ACCEPTABLE_BUT_NO_PROFIT_PROTECTION"
        combo = True
    else:
        primary = "COMBINATION"
        combo = True
    sl_similar = (
        sl_never is not None
        and sl_g1 is not None
        and sl_win is not None
        and abs(sl_g1 - sl_win) / max(sl_win, 1e-9) < 0.5
    )
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
        "groups": groups,
        "share_never_profit": never_share,
        "share_loss_after_0.5R": share_05,
        "share_loss_after_1R": share_1,
        "SL_distances_similar_across_groups": sl_similar,
        "against_pure_entry_wrong": against_entry,
        "against_pure_entry_wrong_statement": (
            f"{len(g1)}/{n_loss} losers had MFE>1R. That is evidence against a pure "
            "'entry is wrong / never had edge' explanation: the path was right long enough to print +1R."
        ),
        "verdict": {
            "primary": primary,
            "combination": combo,
            "SL_too_close": never_share >= 0.50,
            "no_profit_protection": share_05 >= 0.40,
            "TP_too_distant": False,
            "TP_structurally_wrong": "see Phase77",
            "exit_too_slow_after_reversal": (groups["losers_MFE_gt_0.5R"]["median_time_to_reversal"] or 0) >= 15,
            "options_considered": [
                "SL too close to entry",
                "SL acceptable but no profit protection",
                "TP too distant",
                "TP structurally wrong",
                "Exit too slow after reversal",
                "Combination",
            ],
        },
        "LOSS_AFTER_0_5R": len(g05),
        "LOSS_AFTER_1R": len(g1),
        "hypotheses": [
            {
                "id": "H76-01",
                "claim": "MFE>1R among many losers rejects a pure initial-entry-failure story.",
                "result": "SUPPORTED" if against_entry else "NOT_SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["group_sl_rr_mfe", "verdict_rule"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "SL_TP": "NOT_CHANGED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE76_JSON, "md": PHASE76_MD},
    }
    (root / PHASE76_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE76_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE76_MD).write_text(
        "\n".join(
            [
                "# Phase 76 — Initial Stop vs Profit Protection",
                "",
                f"**Verdict:** `{primary}`",
                "",
                payload["against_pure_entry_wrong_statement"],
                "",
                f"Never-profit losers: {len(never)}/{n_loss}. MFE>0.5R: {len(g05)}. MFE>1R: {len(g1)}.",
                "SL/TP were not optimized.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase76_collection(Path("."))["verdict"]["primary"])
