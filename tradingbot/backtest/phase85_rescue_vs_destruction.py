"""Phase 85 — loser rescue vs winner/tail destruction.

A family that rescues losers but destroys similar winner expectancy is not a success.
Expectancy-only ranking is forbidden.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    _dd,
    _git_head,
    _mean,
    _median,
    _pf,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import EXTREME_R
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase82_profit_protection_design import STRUCTURAL_FRACTION
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, TESTABLE_FAMILIES

PHASE = "85"
PHASE85_JSON = "logs/phase85_rescue_vs_destruction.json"
PHASE85_MD = "docs/PHASE85_RESCUE_VS_DESTRUCTION.md"
BLOCKED = "BLOCKED"
# Unique structural half: "material" = lost more than half of original R. Not searched.
MATERIAL_FRAC = STRUCTURAL_FRACTION
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_family",
    "final_gate",
    "production_safety",
    "artifacts",
)


def score_family(name: str, walks: list[dict[str, Any]]) -> dict[str, Any]:
    orig = [_f(w.get("orig")) for w in walks]
    cf = [_f(w.get("cf")) for w in walks]
    pairs = [(a, b, w) for a, b, w in zip(orig, cf, walks) if a is not None and b is not None]
    losers = [(a, b) for a, b, _ in pairs if a < 0]
    winners = [(a, b) for a, b, _ in pairs if a > 0]
    tails = [(a, b) for a, b, w in pairs if a >= EXTREME_R or (_f(w.get("rr")) or 0) > 10]
    ox = [a for a, b, _ in pairs]
    cx = [b for a, b, _ in pairs]
    tail_ox = [a for a, _ in tails]
    tail_cx = [b for _, b in tails]
    rescue = {
        "n_orig_losers": len(losers),
        "to_ge_0R": sum(1 for a, b in losers if b >= 0),
        "to_ge_0_25R": sum(1 for a, b in losers if b >= 0.25),
        "to_ge_0_5R": sum(1 for a, b in losers if b >= 0.5),
    }
    destruction = {
        "n_orig_winners": len(winners),
        "lt_original_R": sum(1 for a, b in winners if b < a),
        "to_le_0R": sum(1 for a, b in winners if b <= 0),
        "materially_reduced": sum(1 for a, b in winners if a > 0 and b < MATERIAL_FRAC * a),
    }
    tail_d = {
        "n_rr_gt_10": len(tails),
        "materially_reduced": sum(1 for a, b in tails if a > 0 and b < MATERIAL_FRAC * a),
        "to_le_0R": sum(1 for a, b in tails if b <= 0),
        "lost_extreme_class": sum(1 for a, b in tails if a >= EXTREME_R and b < EXTREME_R),
    }
    gross_delta = float(sum(cx) - sum(ox)) if pairs else None
    exp_delta = (_mean(cx) - _mean(ox)) if pairs else None
    med_delta = ((_median(cx) or 0) - (_median(ox) or 0)) if pairs else None
    pf_delta = None
    if pairs and _pf(ox) is not None:
        pf_delta = (_pf(cx) or 0) - (_pf(ox) or 0)
    dd_delta = None
    if pairs and _dd(ox) is not None:
        dd_delta = (_dd(cx) or 0) - (_dd(ox) or 0)
    tail_contrib_delta = (float(sum(tail_cx) - sum(tail_ox))) if tails else None
    winner_r_delta = float(sum(b - a for a, b in winners)) if winners else 0.0
    loser_r_delta = float(sum(b - a for a, b in losers)) if losers else 0.0
    # Not a success if rescued loser R is offset by destroyed winner R.
    net_offset = bool(
        loser_r_delta > 0 and winner_r_delta < 0 and abs(winner_r_delta) >= 0.5 * loser_r_delta
    )
    return {
        "name": name,
        "LOSER_RESCUE": rescue,
        "WINNER_DESTRUCTION": destruction,
        "TAIL_DESTRUCTION": tail_d,
        "gross_R_delta": gross_delta,
        "event_expectancy_delta": exp_delta,
        "median_R_delta": med_delta,
        "PF_delta": pf_delta,
        "DD_delta": dd_delta,
        "tail_contribution_delta": tail_contrib_delta,
        "loser_R_delta": loser_r_delta,
        "winner_R_delta": winner_r_delta,
        "rescue_offset_by_winner_destruction": net_offset,
        "not_selected_by_expectancy_alone": True,
        "material_frac_predeclared": MATERIAL_FRAC,
    }


def run_phase85_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p83 = _safe_load_json(root / PHASE83_JSON) or {}
    walks = p83.get("walks") or {}
    names = list(TESTABLE_FAMILIES)
    if p83.get("hybrid_created"):
        names.append("HYBRID")
    by_family = {}
    for name in names:
        w = walks.get(name) or []
        by_family[name] = score_family(name, w) if w else {"name": name, "status": "DATA_LIMITED"}
    by_family["ATR_NORMALIZED_RETRACE"] = {"name": "ATR_NORMALIZED_RETRACE", "status": "DATA_LIMITED"}
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
        "hypotheses": [
            {
                "id": "H85-01",
                "claim": "Loser rescue must be reported against winner and tail destruction; expectancy alone is not success.",
                "result": {k: v.get("rescue_offset_by_winner_destruction") for k, v in by_family.items()},
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
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE85_JSON, "md": PHASE85_MD},
    }
    (root / PHASE85_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE85_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 85 — Loser Rescue vs Winner Destruction",
        "",
        f"Material reduction = lost more than unique half ({MATERIAL_FRAC}) of original R. Not searched.",
        "Expectancy-only selection is forbidden. Not optimal.",
        "",
    ]
    for name, row in by_family.items():
        if row.get("status") == "DATA_LIMITED":
            lines.append(f"- `{name}`: DATA_LIMITED")
            continue
        lr = row.get("LOSER_RESCUE") or {}
        wd = row.get("WINNER_DESTRUCTION") or {}
        td = row.get("TAIL_DESTRUCTION") or {}
        lines.append(
            f"- `{name}`: rescue>=0 `{lr.get('to_ge_0R')}` / losers `{lr.get('n_orig_losers')}`; "
            f"winners<=0 `{wd.get('to_le_0R')}` material `{wd.get('materially_reduced')}`; "
            f"tail material `{td.get('materially_reduced')}`; "
            f"exp_delta=`{row.get('event_expectancy_delta')}` offset=`{row.get('rescue_offset_by_winner_destruction')}`"
        )
    (root / PHASE85_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase85_collection(Path("."))
    print(list(p["by_family"]))
