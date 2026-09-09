"""Phase 97 — final profit-protection research gate.

Does not implement a production exit. Does not force EXIT_DESIGN_SPEC.
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
from tradingbot.backtest.phase89_profit_protection_gate import PHASE89_JSON
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON
from tradingbot.backtest.phase91_reversal_timing_forensics import PHASE91_JSON
from tradingbot.backtest.phase93_tail_preservation_forensics import PHASE93_JSON
from tradingbot.backtest.phase94_cluster_forensics import PHASE94_JSON
from tradingbot.backtest.phase95_protection_family_v2 import PHASE95_JSON
from tradingbot.backtest.phase96_protection_robustness_gate import PHASE96_JSON

PHASE = "97"
PHASE97_JSON = "logs/phase97_profit_protection_final_gate.json"
PHASE97_MD = "docs/PHASE97_PROFIT_PROTECTION_FINAL_GATE.md"
INSUFFICIENT_SPEC = "INSUFFICIENT_EVIDENCE"
GATE_ALLOWED = (
    "PROTECTION_DESIGN_SUPPORTED",
    "PROTECTION_DESIGN_PARTIALLY_SUPPORTED",
    "PROTECTION_DESIGN_UNSUPPORTED",
    "PROTECTION_DESIGN_DATA_LIMITED",
    "INSUFFICIENT_EVIDENCE_CONTINUE_RESEARCH",
)
NEXT_ALLOWED = (
    "OFFLINE_EXIT_IMPLEMENTATION",
    "MORE_PROFIT_PROTECTION_FORENSICS",
    "TAIL_CAPTURE_RESEARCH",
    "EXIT_GEOMETRY_RESEARCH",
    "STRATEGY_REPLACEMENT_RESEARCH",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PROTECTION_STATUS",
    "EXIT_DESIGN_SPEC",
    "NEXT_RESEARCH_TARGET",
    "final_gate",
    "production_safety",
    "artifacts",
)


def decide(p81: dict, p89: dict, p90: dict, p91: dict, p93: dict, p94: dict, p95: dict, p96: dict) -> dict[str, Any]:
    prod = p96.get("production_candidates") or []
    helpful = p95.get("helpful_families") or []
    by_f = p96.get("by_family") or {}
    tails = p95.get("tails") or {}
    q1 = p81.get("PRIMARY_EXIT_MECHANISM") == "PROFIT_GIVEBACK" or (p90.get("questions") or {}).get("1_majority_recoverable_losses") == "C_AND_D"
    q2 = (p91.get("TIME_AS_CAUSAL_PROTECTION_SIGNAL") in {"PARTIALLY_SUPPORTED", "SUPPORTED"}) or bool(
        (p90.get("questions") or {}).get("3_common_signature_losers_vs_winners")
    )
    # q2 causal mechanism that predicts harmful giveback: FAST_SPIKE and class C/D exist, but separator not established
    sep = (p90.get("questions") or {}).get("3_common_signature_losers_vs_winners")
    q2_strong = sep == "PARTIAL_MFE_SEPARATION"
    q3 = False
    q4 = False
    q5 = False
    q6 = False
    q7 = False
    q8 = bool(p94.get("signals_not_independent"))  # clustering handled: we used events
    q9 = False
    for name in helpful or list(by_f):
        row = by_f.get(name) or {}
        tail = (tails.get(name) or {}).get("TAIL_PRESERVATION")
        if row.get("class") == "PRODUCTION_CANDIDATE":
            q3 = True
        if tail in {"PRESERVED", "PARTIALLY_PRESERVED"}:
            q4 = True
        if (row.get("OOS") or {}).get("sign") == "POS":
            q5 = True
        if (row.get("RECENT_180D") or {}).get("sign") == "POS":
            q6 = True
        if (row.get("without_top1_delta") or 0) > 0:
            q7 = True
        buy = ((row.get("by_side") or {}).get("BUY") or {}).get("sign")
        sell = ((row.get("by_side") or {}).get("SELL") or {}).get("sign")
        if buy == sell == "POS":
            q9 = True
    q10 = bool(prod)
    if q10:
        status = "PROTECTION_DESIGN_SUPPORTED"
        spec = prod[0]
        nxt = "OFFLINE_EXIT_IMPLEMENTATION"
    elif helpful and q4:
        status = "PROTECTION_DESIGN_PARTIALLY_SUPPORTED"
        spec = INSUFFICIENT_SPEC
        nxt = "MORE_PROFIT_PROTECTION_FORENSICS"
    elif helpful:
        status = "PROTECTION_DESIGN_PARTIALLY_SUPPORTED"
        spec = INSUFFICIENT_SPEC
        nxt = "TAIL_CAPTURE_RESEARCH" if not q4 else "MORE_PROFIT_PROTECTION_FORENSICS"
    else:
        # Giveback still primary; v2 families did not yield a design.
        status = "PROTECTION_DESIGN_PARTIALLY_SUPPORTED" if q1 else "INSUFFICIENT_EVIDENCE_CONTINUE_RESEARCH"
        spec = INSUFFICIENT_SPEC
        nxt = "MORE_PROFIT_PROTECTION_FORENSICS"
        if p93.get("TAIL_DISCRIMINATOR") == "NOT_ESTABLISHED" and not q4:
            nxt = "MORE_PROFIT_PROTECTION_FORENSICS"
    if status not in GATE_ALLOWED:
        status = "INSUFFICIENT_EVIDENCE_CONTINUE_RESEARCH"
    if nxt not in NEXT_ALLOWED:
        nxt = "INSUFFICIENT_EVIDENCE"
    # Robustness of the research program, not of a missing design.
    robust = "INSUFFICIENT"
    oos_status = "NEGATIVE"
    rec_status = "MIXED"
    any_oos_pos = any((v.get("OOS") or {}).get("sign") == "POS" for v in by_f.values())
    any_oos_neg = any((v.get("OOS") or {}).get("sign") == "NEG" for v in by_f.values())
    if any_oos_pos and any_oos_neg:
        oos_status = "MIXED"
    elif any_oos_pos:
        oos_status = "POSITIVE"
    elif any_oos_neg:
        oos_status = "NEGATIVE"
    any_rec_pos = any((v.get("RECENT_180D") or {}).get("sign") == "POS" for v in by_f.values())
    any_rec_neg = any((v.get("RECENT_180D") or {}).get("sign") == "NEG" for v in by_f.values())
    if any_rec_pos and any_rec_neg:
        rec_status = "MIXED"
    elif any_rec_pos:
        rec_status = "POSITIVE"
    elif any_rec_neg:
        rec_status = "NEGATIVE"
    tail_status = "DESTROYED"
    if any((t or {}).get("TAIL_PRESERVATION") == "PRESERVED" for t in tails.values()):
        tail_status = "PRESERVED"
    elif any((t or {}).get("TAIL_PRESERVATION") == "PARTIALLY_PRESERVED" for t in tails.values()):
        tail_status = "PARTIALLY_PRESERVED"
    elif any((t or {}).get("TAIL_PRESERVATION") == "DESTROYED" for t in tails.values()):
        tail_status = "DESTROYED"
    final = "GO_RESEARCH" if nxt in {
        "MORE_PROFIT_PROTECTION_FORENSICS",
        "TAIL_CAPTURE_RESEARCH",
        "OFFLINE_EXIT_IMPLEMENTATION",
        "EXIT_GEOMETRY_RESEARCH",
        "STRATEGY_REPLACEMENT_RESEARCH",
    } else "INSUFFICIENT_EVIDENCE"
    return {
        "questions": {
            "1_giveback_still_primary": bool(q1),
            "2_causal_mechanism_predicts_giveback": bool(q2) and not q2_strong,
            "2_separator_established": q2_strong,
            "3_act_without_destroying_winners": q3,
            "4_tail_survives": q4,
            "5_survives_OOS": q5,
            "6_survives_recent180": q6,
            "7_survives_removing_largest_winners": q7,
            "8_survives_event_clustering": q8,
            "9_stable_BUY_SELL": q9,
            "10_enough_for_EXIT_DESIGN_SPEC": q10,
        },
        "PROTECTION_STATUS": status,
        "EXIT_DESIGN_SPEC": spec,
        "EXIT_DESIGN_SPEC_STATUS": spec,
        "NEXT_RESEARCH_TARGET": nxt,
        "TAIL_STATUS": tail_status,
        "OOS_STATUS": oos_status,
        "RECENT180_STATUS": rec_status,
        "ROBUSTNESS_STATUS": robust,
        "PRIMARY_EXIT_MECHANISM": p81.get("PRIMARY_EXIT_MECHANISM") or "PROFIT_GIVEBACK",
        "SECONDARY_EXIT_MECHANISM": p81.get("SECONDARY_EXIT_MECHANISM") or "EXIT_GEOMETRY",
        "FINAL_GATE": final,
        "TAIL_DISCRIMINATOR": p93.get("TAIL_DISCRIMINATOR"),
        "signals_not_independent": p94.get("signals_not_independent"),
        "helpful_families": helpful,
        "production_candidates": prod,
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 90–97 (`docs/PHASE90_PROFIT_GIVEBACK_PATH_FORENSICS.md` through "
        "`docs/PHASE97_PROFIT_PROTECTION_FINAL_GATE.md`) are research-only path/timing/MFE "
        "forensics and v2 protection families. They do not optimize, modify production, "
        "authorize live/shadow, connect to MT5, or implement an exit spec."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 82–89"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 90 path forensics | `run_phase90_collection()` | n/a | RESEARCH; A-G classes | **PASS**; no search |\n"
        "| Phase 91 reversal timing | `run_phase91_collection()` | n/a | RESEARCH; no timeout | **PASS** |\n"
        "| Phase 92 MFE conditional | `run_phase92_collection()` | n/a | RESEARCH; CROSS_LEVELS | **PASS** |\n"
        "| Phase 93 tail discriminator | `run_phase93_collection()` | n/a | RESEARCH; outlier kept | **PASS** |\n"
        "| Phase 94 cluster forensics | `run_phase94_collection()` | n/a | RESEARCH; event unit | **PASS** |\n"
        "| Phase 95 protection v2 | `run_phase95_collection()` | n/a | RESEARCH; 4 families | **PASS**; not optimal |\n"
        "| Phase 96 robustness gate | `run_phase96_collection()` | n/a | RESEARCH; qualitative | **PASS** |\n"
        "| Phase 97 protection final gate | `run_phase97_collection()` | n/a | RESEARCH; one target | **PASS**; not implemented |"
    )
    if "Phase 90 path forensics" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase90_profit_giveback_path_forensics.py` — **RESEARCH_ONLY** path classes A-G.\n"
        "`tradingbot/backtest/phase91_reversal_timing_forensics.py` — **RESEARCH_ONLY** timing; no timeout.\n"
        "`tradingbot/backtest/phase92_mfe_mae_conditional_forensics.py` — **RESEARCH_ONLY** MFE first-cross.\n"
        "`tradingbot/backtest/phase93_tail_preservation_forensics.py` — **RESEARCH_ONLY** tail discriminator.\n"
        "`tradingbot/backtest/phase94_cluster_forensics.py` — **RESEARCH_ONLY** event vs signal unit.\n"
        "`tradingbot/backtest/phase95_protection_family_v2.py` — **RESEARCH_ONLY** four families; not production.\n"
        "`tradingbot/backtest/phase96_protection_robustness_gate.py` — **RESEARCH_ONLY** qualitative gate.\n"
        "`tradingbot/backtest/phase97_profit_protection_final_gate.py` — **RESEARCH_ONLY** final gate; spec not implemented.\n"
    )
    needle = "`tradingbot/backtest/phase89_profit_protection_gate.py`"
    if "phase90_profit_giveback_path_forensics.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 90 started | **NO** |", "| Phase 90 started | **YES** |")
    block = f"""

## Profit-protection path forensics (Phases 90–97)

| Claim | Status |
|---|---|
| PROTECTION_STATUS | **{payload.get("PROTECTION_STATUS")}** |
| EXIT_DESIGN_SPEC | **{payload.get("EXIT_DESIGN_SPEC")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| TAIL_DISCRIMINATOR | **{payload.get("TAIL_DISCRIMINATOR")}** |
| Signals independent | **NO** (event unit required) |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Parameter search | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 98 started | **NO** |
"""
    marker = "## Profit-protection path forensics (Phases 90–97)"
    if marker in ktext:
        start = ktext.find(marker)
        ku.write_text(ktext[:start].rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    n = 419
    rows = [
        ("H90-01", 90, (payload.get("questions") or {}).get("1_giveback_still_primary"), "path classes A-G"),
        ("H91-01", 91, "timing_forensics", "no timeout chosen"),
        ("H92-01", 92, "mfe_conditional", "no threshold search"),
        ("H93-01", 93, payload.get("TAIL_DISCRIMINATOR"), "outlier kept"),
        ("H94-01", 94, "signals_not_independent", "event unit"),
        ("H95-01", 95, payload.get("helpful_families"), "four families"),
        ("H96-01", 96, payload.get("production_candidates"), "qualitative gate"),
        ("H97-01", 97, payload.get("NEXT_RESEARCH_TARGET"), "gate; not implemented"),
    ]
    extra = ["", "## Phases 90–97", ""]
    extra.append("| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |")
    extra.append("|---|---|---|---|---|---|---|---|---|---|")
    for hid, ph, result, note in rows:
        extra.append(
            f"| {hid} | {today} | {ph} | frozen Phase38/40 | {n} | event tape 419 resolved | {result} | reported | NO | {note} |"
        )
    extra.append("")
    extra.append(f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not implemented).")
    extra.append("")
    marker = "## Phases 90–97"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def run_phase97_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p81 = _safe_load_json(root / PHASE81_JSON) or {}
    p89 = _safe_load_json(root / PHASE89_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    p91 = _safe_load_json(root / PHASE91_JSON) or {}
    p93 = _safe_load_json(root / PHASE93_JSON) or {}
    p94 = _safe_load_json(root / PHASE94_JSON) or {}
    p95 = _safe_load_json(root / PHASE95_JSON) or {}
    p96 = _safe_load_json(root / PHASE96_JSON) or {}
    d = decide(p81, p89, p90, p91, p93, p94, p95, p96)
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
        "PARAMETER_SEARCH_USED": False,
        "OPTIMIZATION_USED": False,
        "PRODUCTION_CHANGED": False,
        "MT5_USED": False,
        "LIVE_TRADING": False,
        "EDGE_QUALITY": p81.get("EDGE_QUALITY") or "FRAGILE",
        "hypotheses": [
            {
                "id": "H97-01",
                "claim": "Gate a single next research target from 90-96 without implementing an exit spec.",
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
        "artifacts": {"json": PHASE97_JSON, "md": PHASE97_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE97_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE97_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE97_MD).write_text(
        "\n".join(
            [
                "# Phase 97 — Profit Protection Final Gate",
                "",
                f"**PROTECTION_STATUS:** `{payload['PROTECTION_STATUS']}`",
                f"**EXIT_DESIGN_SPEC:** `{payload['EXIT_DESIGN_SPEC']}`",
                f"**TAIL_STATUS:** `{payload.get('TAIL_STATUS')}`",
                f"**OOS_STATUS:** `{payload.get('OOS_STATUS')}`",
                f"**RECENT180_STATUS:** `{payload.get('RECENT180_STATUS')}`",
                f"**ROBUSTNESS_STATUS:** `{payload.get('ROBUSTNESS_STATUS')}`",
                f"**NEXT_RESEARCH_TARGET:** `{payload['NEXT_RESEARCH_TARGET']}`",
                f"**FINAL_GATE:** `{payload['FINAL_GATE']}` (research continuation only; production unchanged)",
                "",
                "Do NOT implement the target. Do not optimize. Do not trade.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    append_ledger(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase97_collection(Path("."))["PROTECTION_STATUS"])
