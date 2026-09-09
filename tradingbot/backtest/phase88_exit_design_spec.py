"""Phase 88 — causal exit design specification.

Does NOT implement production protection. Does not force a design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase82_profit_protection_design import MEANINGFUL_MFE_R, STRUCTURAL_FRACTION
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON
from tradingbot.backtest.phase84_tail_preservation import PHASE84_JSON
from tradingbot.backtest.phase85_rescue_vs_destruction import PHASE85_JSON
from tradingbot.backtest.phase86_profit_protection_oos import PHASE86_JSON
from tradingbot.backtest.phase87_profit_protection_interactions import PHASE87_JSON

PHASE = "88"
PHASE88_JSON = "logs/phase88_exit_design_spec.json"
PHASE88_MD = "docs/PHASE88_EXIT_DESIGN_SPEC.md"
BLOCKED = "BLOCKED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
TAIL_RANK = {"PRESERVED": 2, "PARTIALLY_PRESERVED": 1, "DESTROYED": 0, "DATA_LIMITED": -1}
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "EXIT_DESIGN_SPEC",
    "final_gate",
    "production_safety",
    "artifacts",
)


def pick_design(p83: dict, p84: dict, p85: dict, p86: dict) -> tuple[str, str]:
    """Return (family_name or INSUFFICIENT_EVIDENCE, reason). OOS not used."""
    survivors = p86.get("survivors") or []
    if not survivors:
        helpful = p83.get("helpful_families") or []
        reason = (
            "No family is HELPFUL on TRAIN and VAL while preserving tails. "
            f"Phase83 HELPFUL={helpful}. Survivors={survivors}."
        )
        return INSUFFICIENT, reason
    tails = p84.get("by_family") or {}
    dest = p85.get("by_family") or {}

    def key(name: str) -> tuple:
        tail = (tails.get(name) or {}).get("TAIL_PRESERVATION")
        td = (dest.get(name) or {}).get("TAIL_DESTRUCTION") or {}
        wd = (dest.get(name) or {}).get("WINNER_DESTRUCTION") or {}
        offset = bool((dest.get(name) or {}).get("rescue_offset_by_winner_destruction"))
        # Prefer preserved tails, fewer extreme losses, not offset; never OOS/full expectancy.
        return (
            TAIL_RANK.get(str(tail), -1),
            -int(td.get("lost_extreme_class") or 0),
            -int(wd.get("to_le_0R") or 0),
            0 if offset else 1,
            name,
        )

    ranked = sorted(survivors, key=key, reverse=True)
    chosen = ranked[0]
    tail = (tails.get(chosen) or {}).get("TAIL_PRESERVATION")
    offset = bool((dest.get(chosen) or {}).get("rescue_offset_by_winner_destruction"))
    if tail == "DESTROYED" or offset:
        return INSUFFICIENT, (
            f"Best TRAIN/VAL survivor `{chosen}` still DESTROYS tails or offsets rescue with winner destruction."
        )
    return chosen, f"Structurally defensible among predeclared families: `{chosen}` (not optimal; OOS unused)."


def spec_for(name: str, reason: str, p83: dict, p84: dict, p87: dict) -> dict[str, Any]:
    cfs = (p83.get("counterfactuals") or {}).get(name) or {}
    tail = ((p84.get("by_family") or {}).get(name) or {})
    inter = ((p87.get("by_family") or {}).get(name) or {})
    if name == INSUFFICIENT:
        return {
            "EXIT_DESIGN_SPEC": INSUFFICIENT,
            "status": INSUFFICIENT,
            "implemented_in_production": False,
            "why": reason,
            "forced": False,
        }
    trigger = (
        f"After closed-bar running MFE >= {MEANINGFUL_MFE_R}R (Phase 74 L3). "
        "Do not arm on intra-bar MFE."
    )
    if name == "PEAK_RETRACE_EXIT":
        floor = (
            f"Trailing floor = {STRUCTURAL_FRACTION} * running closed-bar MFE. "
            "BUY: stop = entry + floor_R * risk. SELL: stop = entry - floor_R * risk."
        )
        after = "Floor only ratchets with new closed-bar MFE. Never loosens. Original SL remains until armed."
        tails_why = "Floor scales with MFE, so a 32R peak would sit near 16R rather than 0R — unlike naive BE."
    elif name == "MFE_FRACTION_FLOOR":
        floor = (
            f"One-shot floor = {STRUCTURAL_FRACTION} * MFE at first armed close. Does not trail."
        )
        after = "Floor stays at the arming value until original TP or the floor is hit."
        tails_why = "Does not chase new peaks; still floors inside profit unlike 0R BE, but can clip early retraces."
    elif name == "SWING_PROTECTION":
        floor = (
            "BUY: stop ratchets to confirmed in-trade swing low (1 closed bar each side) only if swing > entry. "
            "SELL: stop ratchets to confirmed in-trade swing high only if swing < entry."
        )
        after = "No confirmed favorable swing => original SL unchanged. Pivot uses only already-closed bars."
        tails_why = "Does not move to 0R after first +0.5R; a deep pullback to entry can survive if no swing is confirmed."
    elif name == "HYBRID":
        floor = "More conservative of peak-retrace floor and last confirmed favorable swing (BUY max, SELL min)."
        after = "Both parents must have been independently HELPFUL. Compounded clipping risk."
        tails_why = "Hybrid only if both parents preserve tails better than naive BE."
    else:
        floor = "unspecified"
        after = "unspecified"
        tails_why = "unspecified"
    return {
        "EXIT_DESIGN_SPEC": name,
        "status": "SPECIFIED_RESEARCH_ONLY",
        "implemented_in_production": False,
        "not_optimal": True,
        "why": reason,
        "forced": False,
        "1_trigger_condition": trigger,
        "2_state_required": "armed flag; running closed-bar MFE; current protective price; original SL/TP/entry/risk",
        "3_data_required": "frozen M5 OHLC after entry; jsonl entry/SL/TP/side",
        "4_causal_timing": "Stop in force at bar open equals previous close update. Same-bar new MFE vs new floor = AMBIGUOUS; do not assume favorable first.",
        "5_how_floor_moves": floor,
        "6_after_activation": after,
        "7_interaction_with_existing_TP": "Original TP unchanged. If TP hits before the floor, take TP (SL-before-TP if both extremes print).",
        "8_interaction_with_existing_SL": "Until armed, original SL remains. After arming, protective price replaces SL only if it is strictly more conservative for the open P/L.",
        "9_extreme_trend_extension": tails_why,
        "10_BUY_behavior": "Protect below price (raise floor). Never loosen.",
        "11_SELL_behavior": "Protect above price (lower floor). Never loosen. No side-specific parameters.",
        "12_failure_modes": [
            "Early arming then retrace through the floor destroys legitimate tails (observed on naive BE).",
            "Same-bar OHLC order unknown => AMBIGUOUS fills.",
            "M5 pivot confirmation can lag a fast reversal.",
        ],
        "13_data_limitations": "No ATR on parquet. No persisted strategy swings on jsonl. No tick path.",
        "14_backtest_limitations": "Theoretical walk on M5 OHLC; not broker fills; not live slippage.",
        "15_execution_assumptions": "Stop replaceable next bar after close. No partials. No gap model.",
        "16_safety_constraints": "Research-only. No RiskGate/Execution/strategy change. No live/shadow.",
        "17_why_naive_BE_rejected": "Phase 75 A-D HARMFUL on TRAIN and VAL: rescued losers but destroyed winners including +31.84R -> 0R.",
        "18_why_preserve_tails_better": tails_why,
        "phase83_status": cfs.get("status"),
        "TAIL_PRESERVATION": tail.get("TAIL_PRESERVATION"),
        "interaction_usefulness": inter.get("usefulness"),
    }


def run_phase88_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p83 = _safe_load_json(root / PHASE83_JSON) or {}
    p84 = _safe_load_json(root / PHASE84_JSON) or {}
    p85 = _safe_load_json(root / PHASE85_JSON) or {}
    p86 = _safe_load_json(root / PHASE86_JSON) or {}
    p87 = _safe_load_json(root / PHASE87_JSON) or {}
    chosen, reason = pick_design(p83, p84, p85, p86)
    spec = spec_for(chosen, reason, p83, p84, p87)
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
        "chosen_family": chosen,
        "EXIT_DESIGN_SPEC": spec.get("EXIT_DESIGN_SPEC"),
        "spec": spec,
        "implemented_in_production": False,
        "oos_used_for_selection": False,
        "hypotheses": [
            {
                "id": "H88-01",
                "claim": "Specify at most one structurally defensible protection family, or INSUFFICIENT_EVIDENCE.",
                "result": spec.get("EXIT_DESIGN_SPEC"),
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["pick_design", "spec_fields_1_18"],
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
            "spec_implemented": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE88_JSON, "md": PHASE88_MD},
    }
    (root / PHASE88_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE88_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 88 — Causal Exit Design Specification",
        "",
        "DO NOT IMPLEMENT IN PRODUCTION. Not optimal. Not forced.",
        "",
        f"**EXIT_DESIGN_SPEC:** `{spec.get('EXIT_DESIGN_SPEC')}`",
        "",
        spec.get("why") or reason,
        "",
    ]
    if spec.get("EXIT_DESIGN_SPEC") != INSUFFICIENT:
        for i in range(1, 19):
            key = [k for k in spec if k.startswith(f"{i}_")]
            if key:
                lines.append(f"{i}. {spec[key[0]]}")
    (root / PHASE88_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase88_collection(Path("."))["EXIT_DESIGN_SPEC"])
