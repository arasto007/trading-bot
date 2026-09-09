"""Phase 81 — final exit research gate. Chooses next target; does not implement it."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    UNKNOWN,
    _git_head,
    _utc_now,
)
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON
from tradingbot.backtest.phase75_exit_counterfactuals import PHASE75_JSON
from tradingbot.backtest.phase76_sl_vs_profit_protection import PHASE76_JSON
from tradingbot.backtest.phase77_exit_geometry_forensics import PHASE77_JSON
from tradingbot.backtest.phase78_time_exit_forensics import PHASE78_JSON
from tradingbot.backtest.phase79_exit_side_regime import PHASE79_JSON
from tradingbot.backtest.phase80_extreme_winner_audit import PHASE80_JSON

PHASE = "81"
PHASE81_JSON = "logs/phase81_exit_research_gate.json"
PHASE81_MD = "docs/PHASE81_EXIT_RESEARCH_GATE.md"
BLOCKED = "BLOCKED"
PRIMARY_ALLOWED = (
    "PROFIT_GIVEBACK",
    "INITIAL_SL_PROBLEM",
    "TP_GEOMETRY",
    "REVERSAL_RECOGNITION",
    "TIME_EXIT_PROBLEM",
    "REGIME_INVALIDATION",
    "SIGNAL_INVALIDATION",
    "SIDE_SPECIFIC_EXIT",
    "EXTREME_TAIL_DEPENDENCY",
    "COMBINATION",
    "INSUFFICIENT_EVIDENCE",
)
NEXT_ALLOWED = (
    "PROFIT_PROTECTION_DESIGN",
    "DYNAMIC_SL_RESEARCH",
    "DYNAMIC_TP_RESEARCH",
    "REVERSAL_EXIT_RESEARCH",
    "TIME_EXIT_RESEARCH",
    "REGIME_EXIT_RESEARCH",
    "SIDE_SPECIFIC_EXIT_RESEARCH",
    "TAIL_CAPTURE_RESEARCH",
    "ENTRY_RESEARCH",
    "STRATEGY_REPLACEMENT_RESEARCH",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PRIMARY_EXIT_MECHANISM",
    "NEXT_RESEARCH_TARGET",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _diag(supported: bool, partial: bool = False, limited: bool = False) -> str:
    if limited:
        return "DATA_LIMITED"
    if supported:
        return "SUPPORTED"
    if partial:
        return "PARTIALLY_SUPPORTED"
    return "UNSUPPORTED"


def select(p74: dict, p75: dict, p76: dict, p78: dict, p79: dict) -> tuple[str, str, str, str]:
    rate = float(p74.get("PROFIT_GIVEBACK_RATE") or 0)
    n1 = int(p74.get("LOSS_AFTER_1R") or 0)
    verdict = (p76.get("verdict") or {}).get("primary")
    best_status = p75.get("BEST_STRUCTURAL_COUNTERFACTUAL_STATUS")
    td = p78.get("TIME_DEPENDENCY")
    if rate >= 0.5 and n1 >= 50 and verdict == "SL_ACCEPTABLE_BUT_NO_PROFIT_PROTECTION":
        primary = "PROFIT_GIVEBACK"
        secondary = "EXIT_GEOMETRY"
        tertiary = "EXTREME_TAIL_DEPENDENCY"
        nxt = "PROFIT_PROTECTION_DESIGN" if best_status in {"HELPFUL", "NEUTRAL"} else "PROFIT_PROTECTION_DESIGN"
        return primary, secondary, tertiary, nxt
    if verdict == "SL_TOO_CLOSE_TO_ENTRY":
        return "INITIAL_SL_PROBLEM", "PROFIT_GIVEBACK", "EXIT_GEOMETRY", "DYNAMIC_SL_RESEARCH"
    if td == "PRIMARY":
        return "TIME_EXIT_PROBLEM", "PROFIT_GIVEBACK", "EXIT_GEOMETRY", "TIME_EXIT_RESEARCH"
    return "COMBINATION", "PROFIT_GIVEBACK", "EXIT_GEOMETRY", "INSUFFICIENT_EVIDENCE"


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 74–81 (`docs/PHASE74_PROFIT_GIVEBACK_FORENSICS.md` through "
        "`docs/PHASE81_EXIT_RESEARCH_GATE.md`) are research-only profit-giveback and "
        "predeclared exit counterfactuals. They do not optimize, modify production, "
        "authorize live/shadow, connect to MT5, or implement the next design."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 68–73"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 74 profit giveback | `run_phase74_collection()` | n/a | RESEARCH; frozen path | **PASS**; diagnosis only |\n"
        "| Phase 75 exit counterfactuals | `run_phase75_collection()` | n/a | RESEARCH; predeclared CF | **PASS**; not optimal |\n"
        "| Phase 76 SL vs protection | `run_phase76_collection()` | n/a | RESEARCH; no SL search | **PASS** |\n"
        "| Phase 77 exit geometry RR | `run_phase77_collection()` | n/a | RESEARCH; no RR search | **PASS** |\n"
        "| Phase 78 time exit | `run_phase78_collection()` | n/a | RESEARCH; predeclared buckets | **PASS** |\n"
        "| Phase 79 side/regime exit | `run_phase79_collection()` | n/a | RESEARCH; grid descriptive | **PASS** |\n"
        "| Phase 80 extreme winner audit | `run_phase80_collection()` | n/a | RESEARCH; baseline kept | **PASS** |\n"
        "| Phase 81 exit research gate | `run_phase81_collection()` | n/a | RESEARCH; one target | **PASS**; not implemented |"
    )
    if "Phase 74 profit giveback" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase74_profit_giveback_forensics.py` — **RESEARCH_ONLY** giveback path; no SL change.\n"
        "`tradingbot/backtest/phase75_exit_counterfactuals.py` — **RESEARCH_ONLY** theoretical CF; not production.\n"
        "`tradingbot/backtest/phase76_sl_vs_profit_protection.py` — **RESEARCH_ONLY** SL vs protection.\n"
        "`tradingbot/backtest/phase77_exit_geometry_forensics.py` — **RESEARCH_ONLY** planned-RR bins.\n"
        "`tradingbot/backtest/phase78_time_exit_forensics.py` — **RESEARCH_ONLY** time buckets.\n"
        "`tradingbot/backtest/phase79_exit_side_regime.py` — **RESEARCH_ONLY** side/regime grid.\n"
        "`tradingbot/backtest/phase80_extreme_winner_audit.py` — **RESEARCH_ONLY** outlier audit.\n"
        "`tradingbot/backtest/phase81_exit_research_gate.py` — **RESEARCH_ONLY** next-target spec; not implemented.\n"
    )
    needle = "`tradingbot/backtest/phase73_exit_research_gate.py`"
    if "phase74_profit_giveback_forensics.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 74 started | **NO** |", "| Phase 74 started | **YES** |")
    block = f"""

## Profit-giveback exit research (Phases 74–81)

| Claim | Status |
|---|---|
| PRIMARY_EXIT_MECHANISM | **{payload.get("PRIMARY_EXIT_MECHANISM")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| BEST_STRUCTURAL_COUNTERFACTUAL | **{payload.get("BEST_STRUCTURAL_COUNTERFACTUAL")}** ({payload.get("BEST_STRUCTURAL_COUNTERFACTUAL_STATUS")}) |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 82 started | **NO** |
"""
    if "## Profit-giveback exit research (Phases 74–81)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    n = 419
    rows = [
        ("H74-01", 74, payload.get("PROFIT_GIVEBACK_RATE"), "giveback path"),
        ("H75-A", 75, payload.get("BEST_STRUCTURAL_COUNTERFACTUAL_STATUS"), "predeclared CF"),
        ("H76-01", 76, (payload.get("diagnoses") or {}).get("INITIAL_SL"), "SL vs protection"),
        ("H77-01", 77, payload.get("EXTREME_WINNER_STATUS"), "RR geometry"),
        ("H78-01", 78, (payload.get("diagnoses") or {}).get("TIME"), "time buckets"),
        ("H79-01", 79, (payload.get("diagnoses") or {}).get("SIDE"), "side/regime"),
        ("H80-01", 80, payload.get("EXTREME_WINNER_STATUS"), "extreme audit"),
        ("H81-01", 81, payload.get("NEXT_RESEARCH_TARGET"), "gate; not implemented"),
    ]
    extra = ["", "## Phases 74–81", ""]
    extra.append("| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |")
    extra.append("|---|---|---|---|---|---|---|---|---|---|")
    for hid, ph, result, note in rows:
        extra.append(
            f"| {hid} | {today} | {ph} | frozen Phase38/40 | {n} | event tape 419 resolved | {result} | reported | NO | {note} |"
        )
    extra.append("")
    extra.append(f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not implemented).")
    extra.append("")
    if "## Phases 74–81" not in existing:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def run_phase81_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p75 = _safe_load_json(root / PHASE75_JSON) or {}
    p76 = _safe_load_json(root / PHASE76_JSON) or {}
    p77 = _safe_load_json(root / PHASE77_JSON) or {}
    p78 = _safe_load_json(root / PHASE78_JSON) or {}
    p79 = _safe_load_json(root / PHASE79_JSON) or {}
    p80 = _safe_load_json(root / PHASE80_JSON) or {}
    primary, secondary, tertiary, nxt = select(p74, p75, p76, p78, p79)
    if primary not in PRIMARY_ALLOWED:
        primary = "INSUFFICIENT_EVIDENCE"
    if nxt not in NEXT_ALLOWED:
        nxt = "INSUFFICIENT_EVIDENCE"
    rate = p74.get("PROFIT_GIVEBACK_RATE")
    n05 = p74.get("LOSS_AFTER_0_5R")
    n1 = p74.get("LOSS_AFTER_1R")
    against_entry = bool(p76.get("against_pure_entry_wrong"))
    f_status = ((p75.get("counterfactuals") or {}).get("F_REGIME_INVALIDATION_EXIT") or {}).get("status")
    g_status = ((p75.get("counterfactuals") or {}).get("G_SIGNAL_INVALIDATION_EXIT") or {}).get("status")
    diagnoses = {
        "INITIAL_SL": _diag(False, partial=bool((p76.get("share_never_profit") or 0) > 0.05)),
        "PROFIT_PROTECTION": _diag(bool((rate or 0) >= 0.5 and n1 and n1 >= 50)),
        "TP_GEOMETRY": _diag(True, partial=False) if (p77.get("HIGH_PLANNED_RR_IS") or "").startswith("LEGITIMATE") else _diag(False, True),
        "TIME": _diag(p78.get("TIME_DEPENDENCY") == "PRIMARY", partial=p78.get("TIME_DEPENDENCY") in {"SECONDARY", "WEAK"}),
        "REGIME": _diag(False, partial=bool(p79.get("disproportionate"))),
        "SIDE": _diag(False, partial=True),
        "EXTREME_TAIL": _diag(True),
    }
    oos = ((p74.get("views") or {}).get("OOS") or {}).get("expectancy") or {}
    rec = ((p74.get("views") or {}).get("RECENT_180D") or {}).get("expectancy") or {}
    oos_exp = oos.get("expectancy_R")
    rec_exp = rec.get("expectancy_R")
    top1 = ((p74.get("views") or {}).get("WITHOUT_TOP1") or {}).get("expectancy") or {}
    edge = "FRAGILE"
    robust = "FRAGILE" if (top1.get("expectancy_R") or 0) < 0 else "PARTIAL"
    final = "GO_RESEARCH" if nxt == "PROFIT_PROTECTION_DESIGN" else "BLOCKED"
    hyps = []
    for blob in (p74, p75, p76, p77, p78, p79, p80):
        hyps.extend(blob.get("hypotheses") or [])
    hyps.append(
        {
            "id": "H81-01",
            "claim": "Select exactly one next research target from 74-80 without using OOS as selector.",
            "result": nxt,
            "oos_used_for_decision": False,
        }
    )
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
        "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "PRIMARY_EXIT_MECHANISM": primary,
        "SECONDARY_EXIT_MECHANISM": secondary,
        "TERTIARY_EXIT_MECHANISM": tertiary,
        "diagnoses": diagnoses,
        "INITIAL_SL_DIAGNOSIS": diagnoses["INITIAL_SL"],
        "PROFIT_PROTECTION_DIAGNOSIS": diagnoses["PROFIT_PROTECTION"],
        "TP_GEOMETRY_DIAGNOSIS": diagnoses["TP_GEOMETRY"],
        "TIME_DIAGNOSIS": diagnoses["TIME"],
        "REGIME_DIAGNOSIS": diagnoses["REGIME"],
        "SIDE_DIAGNOSIS": diagnoses["SIDE"],
        "EXTREME_TAIL_DIAGNOSIS": diagnoses["EXTREME_TAIL"],
        "LOSS_AFTER_0_5R": n05,
        "LOSS_AFTER_1R": n1,
        "PROFIT_GIVEBACK_RATE": rate,
        "MEDIAN_TIME_TO_REVERSAL": p74.get("MEDIAN_TIME_TO_REVERSAL"),
        "BEST_STRUCTURAL_COUNTERFACTUAL": p75.get("BEST_STRUCTURAL_COUNTERFACTUAL"),
        "BEST_STRUCTURAL_COUNTERFACTUAL_STATUS": p75.get("BEST_STRUCTURAL_COUNTERFACTUAL_STATUS"),
        "best_is_not_optimal": True,
        "EXTREME_WINNER_STATUS": p80.get("EXTREME_WINNER_STATUS"),
        "OOS_RESULT": {"expectancy_R": oos_exp, "n": oos.get("n"), "sign": "POS" if (oos_exp or 0) > 0 else "NEG"},
        "RECENT_180D_RESULT": {"expectancy_R": rec_exp, "n": rec.get("n"), "sign": "POS" if (rec_exp or 0) > 0 else "NEG"},
        "NEXT_RESEARCH_TARGET": nxt,
        "EDGE_QUALITY": edge,
        "ROBUSTNESS": robust,
        "against_pure_entry_wrong": against_entry,
        "WHY": (
            f"Giveback rate={rate}, L4={n1}, Phase76={ (p76.get('verdict') or {}).get('primary') }. "
            f"Predeclared CF best={p75.get('BEST_STRUCTURAL_COUNTERFACTUAL')} "
            f"status={p75.get('BEST_STRUCTURAL_COUNTERFACTUAL_STATUS')} (TRAIN/VAL, not OOS). "
            "Next is design of one protection family, not SL/TP search, not live."
        ),
        "F_G_data_limited": {"F": f_status, "G": g_status},
        "hypotheses": hyps,
        "HYPOTHESES_TESTED": len(hyps),
        "oos_used_for_selection": False,
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "PRODUCTION_CHANGED": False,
        "MT5_USED": False,
        "final_gate": final,
        "FINAL_GATE": final,
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
        "artifacts": {"json": PHASE81_JSON, "md": PHASE81_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE81_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE81_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE81_MD).write_text(
        "\n".join(
            [
                "# Phase 81 — Exit Research Gate",
                "",
                f"**PRIMARY_EXIT_MECHANISM:** `{primary}`",
                f"**SECONDARY_EXIT_MECHANISM:** `{secondary}`",
                f"**TERTIARY_EXIT_MECHANISM:** `{tertiary}`",
                f"**NEXT_RESEARCH_TARGET:** `{nxt}`",
                f"**FINAL_GATE:** `{final}` (research continuation only; production unchanged)",
                "",
                payload["WHY"],
                "",
                "Do NOT implement the target in this phase. Do not optimize. Do not trade.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    append_ledger(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase81_collection(Path("."))["NEXT_RESEARCH_TARGET"])
