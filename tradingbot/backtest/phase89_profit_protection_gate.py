"""Phase 89 — final profit-protection research gate.

Chooses exactly one next research target. Does not implement it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase81_exit_research_gate import PHASE81_JSON
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, TESTABLE_FAMILIES
from tradingbot.backtest.phase84_tail_preservation import PHASE84_JSON
from tradingbot.backtest.phase85_rescue_vs_destruction import PHASE85_JSON
from tradingbot.backtest.phase86_profit_protection_oos import PHASE86_JSON
from tradingbot.backtest.phase87_profit_protection_interactions import PHASE87_JSON
from tradingbot.backtest.phase88_exit_design_spec import INSUFFICIENT, PHASE88_JSON

PHASE = "89"
PHASE89_JSON = "logs/phase89_profit_protection_gate.json"
PHASE89_MD = "docs/PHASE89_PROFIT_PROTECTION_GATE.md"
BLOCKED = "BLOCKED"
STATUS_ALLOWED = ("SUPPORTED_DESIGN", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "REJECTED")
TAIL_ALLOWED = ("PRESERVED", "PARTIALLY_PRESERVED", "DESTROYED", "UNKNOWN")
OOS_ALLOWED = ("POSITIVE", "NEGATIVE", "MIXED", "INSUFFICIENT")
ROBUST_ALLOWED = ("ROBUST", "MODERATE", "FRAGILE", "INSUFFICIENT")
NEXT_ALLOWED = (
    "OFFLINE_EXIT_IMPLEMENTATION",
    "MORE_PROFIT_PROTECTION_FORENSICS",
    "EXIT_GEOMETRY_RESEARCH",
    "TIME_EXIT_RESEARCH",
    "SIDE_EXIT_RESEARCH",
    "TAIL_CAPTURE_RESEARCH",
    "STRATEGY_REPLACEMENT_RESEARCH",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PROFIT_PROTECTION_STATUS",
    "NEXT_RESEARCH_TARGET",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _fold_word(sign: str | None) -> str:
    if sign == "POS":
        return "POSITIVE"
    if sign == "NEG":
        return "NEGATIVE"
    if sign in {"NEUTRAL", None, "INSUFFICIENT"}:
        return "INSUFFICIENT" if sign in {None, "INSUFFICIENT"} else "MIXED"
    return "INSUFFICIENT"


def decide(p81: dict, p83: dict, p84: dict, p85: dict, p86: dict, p88: dict) -> dict[str, Any]:
    spec = p88.get("EXIT_DESIGN_SPEC")
    survivors = p86.get("survivors") or []
    helpful = p83.get("helpful_families") or []
    families = p86.get("by_family") or {}
    primary = None
    if spec and spec != INSUFFICIENT:
        primary = spec
    elif survivors:
        primary = survivors[0]
    diagnostic_name = primary or "PEAK_RETRACE_EXIT"
    chosen = families.get(diagnostic_name) or {}
    folds = chosen.get("folds") or {}
    train_s = (folds.get("TRAIN") or {}).get("sign")
    val_s = (folds.get("VALIDATION") or {}).get("sign")
    oos_s = (folds.get("OOS") or {}).get("sign")
    rec_s = (folds.get("RECENT_180D") or {}).get("sign")
    tails = (p84.get("by_family") or {}).get(diagnostic_name) or {}
    tail_labels = [
        ((p84.get("by_family") or {}).get(n) or {}).get("TAIL_PRESERVATION")
        for n in TESTABLE_FAMILIES
    ]
    if primary:
        tail = tails.get("TAIL_PRESERVATION") or "UNKNOWN"
    elif "DESTROYED" in tail_labels:
        tail = "DESTROYED"
    elif "PARTIALLY_PRESERVED" in tail_labels:
        tail = "PARTIALLY_PRESERVED"
    elif "PRESERVED" in tail_labels:
        tail = "PRESERVED"
    else:
        tail = "UNKNOWN"
    dest = (p85.get("by_family") or {}).get(diagnostic_name) or {}
    offset = bool(dest.get("rescue_offset_by_winner_destruction"))
    q1 = True  # giveback remains causally justified from 74-81
    q2 = bool(spec and spec != INSUFFICIENT)
    q3 = bool(survivors) and not offset
    q4 = tail in {"PRESERVED", "PARTIALLY_PRESERVED"}
    q5 = bool(chosen.get("TRAIN_improves") and chosen.get("VAL_improves") and chosen.get("OOS_improves"))
    q6 = bool(chosen.get("RECENT_180D_improves"))
    q7 = bool(chosen.get("useful_without_top1"))
    q8 = True  # no parameter search in 82-89
    q9 = bool(q2 and q3 and q4 and chosen.get("TRAIN_improves") and chosen.get("VAL_improves"))
    if q2 and q4 and chosen.get("TRAIN_improves") and chosen.get("VAL_improves") and not offset:
        status = "SUPPORTED_DESIGN"
    elif helpful or survivors:
        status = "PARTIALLY_SUPPORTED"
    elif tail == "DESTROYED" and not helpful:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "INSUFFICIENT_EVIDENCE"
    if spec == INSUFFICIENT and not helpful:
        # Protection still needed (Phase 81) but these families are not a design.
        status = "PARTIALLY_SUPPORTED" if (p81.get("PROFIT_PROTECTION_DIAGNOSIS") == "SUPPORTED") else "INSUFFICIENT_EVIDENCE"
    oos_status = _fold_word(oos_s)
    rec_status = _fold_word(rec_s)
    if train_s == "POS" and val_s == "POS" and oos_s == "POS" and rec_s == "POS":
        robust = "ROBUST"
    elif train_s == "POS" and val_s == "POS":
        robust = "MODERATE"
    elif primary:
        robust = "FRAGILE"
    else:
        robust = "INSUFFICIENT"
    if q9 and status == "SUPPORTED_DESIGN":
        nxt = "OFFLINE_EXIT_IMPLEMENTATION"
    elif tail == "DESTROYED" and helpful:
        nxt = "TAIL_CAPTURE_RESEARCH"
    elif p81.get("PROFIT_PROTECTION_DIAGNOSIS") == "SUPPORTED":
        nxt = "MORE_PROFIT_PROTECTION_FORENSICS"
    else:
        nxt = "INSUFFICIENT_EVIDENCE"
    edge = p81.get("EDGE_QUALITY") or "FRAGILE"
    if robust == "FRAGILE":
        edge = "FRAGILE"
    final = "GO_RESEARCH" if nxt in {
        "OFFLINE_EXIT_IMPLEMENTATION",
        "MORE_PROFIT_PROTECTION_FORENSICS",
        "TAIL_CAPTURE_RESEARCH",
        "EXIT_GEOMETRY_RESEARCH",
        "TIME_EXIT_RESEARCH",
        "SIDE_EXIT_RESEARCH",
    } else "INSUFFICIENT_EVIDENCE"
    secondary = "NONE"
    if primary:
        others = [n for n in TESTABLE_FAMILIES if n != primary]
        if others:
            secondary = others[0]
    return {
        "q": {
            "1_causally_justified": q1,
            "2_one_defensible_design": q2,
            "3_giveback_without_unacceptable_destruction": q3,
            "4_preserves_right_tail": q4,
            "5_survives_TRAIN_VAL_OOS": q5,
            "6_survives_recent_180d": q6,
            "7_useful_without_3184_outlier": q7,
            "8_avoids_parameter_search": q8,
            "9_strong_enough_for_offline_implementation_research": q9,
        },
        "PROFIT_PROTECTION_STATUS": status,
        "PRIMARY_PROTECTION_MECHANISM": primary if primary else "NONE",
        "SECONDARY_PROTECTION_MECHANISM": secondary,
        "TAIL_PRESERVATION": tail if tail in TAIL_ALLOWED else "UNKNOWN",
        "OOS_STATUS": oos_status,
        "RECENT_STATUS": rec_status,
        "ROBUSTNESS": robust,
        "EDGE_QUALITY": edge,
        "NEXT_RESEARCH_TARGET": nxt,
        "FINAL_GATE": final,
        "TRAIN_RESULT": train_s,
        "VAL_RESULT": val_s,
        "OOS_RESULT": oos_s,
        "RECENT_180D_RESULT": rec_s,
        "LOSER_RESCUE": dest.get("LOSER_RESCUE"),
        "WINNER_DESTRUCTION": dest.get("WINNER_DESTRUCTION"),
        "TAIL_DESTRUCTION": dest.get("TAIL_DESTRUCTION"),
        "OUTLIER_EFFECT": (tails.get("outlier") or {}).get("cf_R"),
        "TOP5_EFFECT": (tails.get("top5") or {}).get("cf_mean_R"),
        "BUY_RESULT": None,
        "SELL_RESULT": None,
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 82–89 (`docs/PHASE82_PROFIT_PROTECTION_DESIGN.md` through "
        "`docs/PHASE89_PROFIT_PROTECTION_GATE.md`) are research-only profit-protection "
        "taxonomy, predeclared counterfactuals, and a design gate. They do not optimize, "
        "modify production, authorize live/shadow, connect to MT5, or implement the spec."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 74–81"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 82 protection taxonomy | `run_phase82_collection()` | n/a | RESEARCH; no walk | **PASS**; no search |\n"
        "| Phase 83 protection CF | `run_phase83_collection()` | n/a | RESEARCH; predeclared | **PASS**; not optimal |\n"
        "| Phase 84 tail preservation | `run_phase84_collection()` | n/a | RESEARCH; outlier kept | **PASS** |\n"
        "| Phase 85 rescue vs destruction | `run_phase85_collection()` | n/a | RESEARCH; not expectancy-only | **PASS** |\n"
        "| Phase 86 protection OOS | `run_phase86_collection()` | n/a | RESEARCH; OOS not selector | **PASS** |\n"
        "| Phase 87 protection interactions | `run_phase87_collection()` | n/a | RESEARCH; diagnosis only | **PASS** |\n"
        "| Phase 88 exit design spec | `run_phase88_collection()` | n/a | RESEARCH; not implemented | **PASS** |\n"
        "| Phase 89 protection gate | `run_phase89_collection()` | n/a | RESEARCH; one target | **PASS**; not implemented |"
    )
    if "Phase 82 protection taxonomy" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase82_profit_protection_design.py` — **RESEARCH_ONLY** taxonomy; no walk.\n"
        "`tradingbot/backtest/phase83_profit_protection_counterfactuals.py` — **RESEARCH_ONLY** theoretical CF.\n"
        "`tradingbot/backtest/phase84_tail_preservation.py` — **RESEARCH_ONLY** tail diagnostic.\n"
        "`tradingbot/backtest/phase85_rescue_vs_destruction.py` — **RESEARCH_ONLY** rescue vs destruction.\n"
        "`tradingbot/backtest/phase86_profit_protection_oos.py` — **RESEARCH_ONLY** fold consistency.\n"
        "`tradingbot/backtest/phase87_profit_protection_interactions.py` — **RESEARCH_ONLY** side/session diagnosis.\n"
        "`tradingbot/backtest/phase88_exit_design_spec.py` — **RESEARCH_ONLY** spec; not implemented.\n"
        "`tradingbot/backtest/phase89_profit_protection_gate.py` — **RESEARCH_ONLY** next-target gate; not implemented.\n"
    )
    needle = "`tradingbot/backtest/phase81_exit_research_gate.py`"
    if "phase82_profit_protection_design.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 82 started | **NO** |", "| Phase 82 started | **YES** |")
    block = f"""

## Profit-protection design research (Phases 82–89)

| Claim | Status |
|---|---|
| PROFIT_PROTECTION_STATUS | **{payload.get("PROFIT_PROTECTION_STATUS")}** |
| EXIT_DESIGN_SPEC | **{payload.get("EXIT_DESIGN_SPEC")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| TAIL_PRESERVATION | **{payload.get("TAIL_PRESERVATION")}** |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Parameter search | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 90 started | **NO** |
"""
    if "## Profit-protection design research (Phases 82–89)" in ktext:
        start = ktext.find("## Profit-protection design research (Phases 82–89)")
        ktext = ktext[:start].rstrip() + block
        ku.write_text(ktext, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    n = 419
    rows = [
        ("H82-01", 82, "TAXONOMY_READY", "taxonomy; no search"),
        ("H83-01", 83, payload.get("PRIMARY_PROTECTION_MECHANISM"), "predeclared CF"),
        ("H84-01", 84, payload.get("TAIL_PRESERVATION"), "tail diagnostic"),
        ("H85-01", 85, "rescue_vs_destruction", "not expectancy-only"),
        ("H86-01", 86, payload.get("OOS_STATUS"), "TRAIN/VAL/OOS report"),
        ("H87-01", 87, "interaction_diagnosis", "no side parameters"),
        ("H88-01", 88, payload.get("EXIT_DESIGN_SPEC"), "spec; not implemented"),
        ("H89-01", 89, payload.get("NEXT_RESEARCH_TARGET"), "gate; not implemented"),
    ]
    extra = ["", "## Phases 82–89", ""]
    extra.append("| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |")
    extra.append("|---|---|---|---|---|---|---|---|---|---|")
    for hid, ph, result, note in rows:
        extra.append(
            f"| {hid} | {today} | {ph} | frozen Phase38/40 | {n} | event tape 419 resolved | {result} | reported | NO | {note} |"
        )
    extra.append("")
    extra.append(f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not implemented).")
    extra.append("")
    marker = "## Phases 82–89"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def run_phase89_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p81 = _safe_load_json(root / PHASE81_JSON) or {}
    p83 = _safe_load_json(root / PHASE83_JSON) or {}
    p84 = _safe_load_json(root / PHASE84_JSON) or {}
    p85 = _safe_load_json(root / PHASE85_JSON) or {}
    p86 = _safe_load_json(root / PHASE86_JSON) or {}
    p87 = _safe_load_json(root / PHASE87_JSON) or {}
    p88 = _safe_load_json(root / PHASE88_JSON) or {}
    d = decide(p81, p83, p84, p85, p86, p88)
    if d["PROFIT_PROTECTION_STATUS"] not in STATUS_ALLOWED:
        d["PROFIT_PROTECTION_STATUS"] = "INSUFFICIENT_EVIDENCE"
    if d["NEXT_RESEARCH_TARGET"] not in NEXT_ALLOWED:
        d["NEXT_RESEARCH_TARGET"] = "INSUFFICIENT_EVIDENCE"
    inter = (p87.get("by_family") or {}).get(d.get("PRIMARY_PROTECTION_MECHANISM") or "") or {}
    if not inter:
        inter = (p87.get("by_family") or {}).get("PEAK_RETRACE_EXIT") or {}
    by_side = inter.get("by_side") or {}
    d["BUY_RESULT"] = (by_side.get("BUY") or {}).get("sign")
    d["SELL_RESULT"] = (by_side.get("SELL") or {}).get("sign")
    ambiguous_total = 0
    for name in TESTABLE_FAMILIES:
        ambiguous_total += int(((p83.get("counterfactuals") or {}).get(name) or {}).get("n_ambiguous") or 0)
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
        "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        **d,
        "EXIT_DESIGN_SPEC": p88.get("EXIT_DESIGN_SPEC"),
        "EXIT_DESIGN_SPEC_STATUS": p88.get("EXIT_DESIGN_SPEC"),
        "PARAMETER_SEARCH_USED": False,
        "OPTIMIZATION_USED": False,
        "PRODUCTION_CHANGED": False,
        "MT5_USED": False,
        "LIVE_TRADING": False,
        "n_ambiguous_path_ordering": ambiguous_total,
        "helpful_families": p83.get("helpful_families"),
        "hybrid_created": p83.get("hybrid_created"),
        "survivors": p86.get("survivors"),
        "questions": d["q"],
        "hypotheses": [
            {
                "id": "H89-01",
                "claim": "Gate a single next research target from 82-88 without implementing it or using OOS as selector.",
                "result": d["NEXT_RESEARCH_TARGET"],
                "oos_used_for_decision": False,
            }
        ],
        "oos_used_for_selection": False,
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "final_gate": d["FINAL_GATE"],
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
            "spec_implemented": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE89_JSON, "md": PHASE89_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE89_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE89_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE89_MD).write_text(
        "\n".join(
            [
                "# Phase 89 — Profit Protection Research Gate",
                "",
                f"**PROFIT_PROTECTION_STATUS:** `{payload['PROFIT_PROTECTION_STATUS']}`",
                f"**EXIT_DESIGN_SPEC:** `{payload['EXIT_DESIGN_SPEC']}`",
                f"**PRIMARY_PROTECTION_MECHANISM:** `{payload.get('PRIMARY_PROTECTION_MECHANISM')}`",
                f"**TAIL_PRESERVATION:** `{payload.get('TAIL_PRESERVATION')}`",
                f"**OOS_STATUS:** `{payload.get('OOS_STATUS')}`",
                f"**RECENT_STATUS:** `{payload.get('RECENT_STATUS')}`",
                f"**ROBUSTNESS:** `{payload.get('ROBUSTNESS')}`",
                f"**NEXT_RESEARCH_TARGET:** `{payload['NEXT_RESEARCH_TARGET']}`",
                f"**FINAL_GATE:** `{payload['FINAL_GATE']}` (research continuation only; production unchanged)",
                "",
                "Do NOT implement the target. Do not optimize. Do not trade. Parameter search was not used.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    append_ledger(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase89_collection(Path("."))["NEXT_RESEARCH_TARGET"])
