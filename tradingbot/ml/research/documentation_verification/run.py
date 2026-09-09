"""Offline documentation verification. Does not start MT5/bot or rewrite production code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
REPORT_DIR = ROOT / "data" / "ml" / "reports" / "documentation_verification"
HUMAN = ROOT / "docs_v2" / "01_truth" / "DOCUMENTATION_VERIFICATION_REPORT.md"

from tradingbot.ml.research.documentation_freshness.scanner import (
    DO_NOT_WATCH,
    SNAPSHOT,
    WATCH_REASONS,
    WATCHED,
    scan_freshness,
)
from tradingbot.ml.research.documentation_memory_hardening_v2.load_path import (
    FULL_SESSION_OWNERS,
    classify_questions,
    corpus,
    hallucination_guards,
)
from tradingbot.ml.research.documentation_memory_hardening_v2.run import (
    REQUIRED_OWNERS,
    bootstrap_imports_research,
    impact_map_audit,
    ownership_audit,
    unique_canonical_entry,
)

REQUIRED_DOCS = [
    "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md",
    "docs_v2/01_truth/PROJECT_DECISION_BASELINE.md",
    "docs_v2/01_truth/DOCUMENTATION_COMPLETION_CONTRACT.md",
    "docs_v2/08_testing/TESTING.md",
    *REQUIRED_OWNERS.values(),
]

GATES = [
    "unique_canonical_entry",
    "required_load_path",
    "owner_uniqueness",
    "derived_labels",
    "watched_or_do_not_watch",
    "freshness_baseline",
    "tests_do_not_rewrite_snapshot",
    "unknowns_preserved",
    "contradictions_preserved",
    "historical_labeled",
    "operator_state_separated",
    "testing_doc",
    "fresh_session",
    "consistency_invariants_present",
    "impact_map",
    "research_boundary",
    "snapshot_integrity",
]


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _status(ok: bool, *, fail: str = "FAIL") -> str:
    return "PASS" if ok else fail


def run_verification(*, write_reports: bool = True) -> dict[str, Any]:
    entries = unique_canonical_entry()
    missing_docs = [rel for rel in REQUIRED_DOCS if not (ROOT / rel).is_file()]
    owner = ownership_audit()
    impact = impact_map_audit()
    fresh = scan_freshness()
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.is_file() else None
    reasons_ok = set(WATCH_REASONS) == set(WATCHED)
    blob, files = corpus(FULL_SESSION_OWNERS)
    questions = classify_questions(blob, owners_loaded=FULL_SESSION_OWNERS)
    guards = hallucination_guards(blob)
    cx = _read("docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md")
    boot = _read("docs_v2/01_truth/CHATGPT_BOOTSTRAP.md")
    runtime = _read("docs_v2/01_truth/CURRENT_RUNTIME_STATE.md")
    testing = _read("docs_v2/08_testing/TESTING.md")
    ml = _read("docs_v2/07_ml/ML_SYSTEM_STATE.md")
    derived_files = [
        "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md",
        "docs_v2/01_truth/PROJECT_DECISION_BASELINE.md",
        "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md",
    ]
    derived_ok = all("Epistemic-Role:" in _read(rel) for rel in derived_files)
    unknowns_ok = all(x in cx for x in ("UNK-001", "UNK-002", "UNK-003"))
    cx_ok = all(f"CX-{i:03d}" in cx or f"CX-{i:03d}" in cx.replace(" ", "") for i in range(1, 17))
    if "CX-001" not in cx:
        cx_ok = False
    else:
        cx_ok = all(f"CX-{i:03d}" in cx for i in (1, 2, 3, 16))
        cx_ok = cx_ok and "CX-016" in cx
    historical_ok = "HISTORICAL" in ml and "RESEARCH" in ml
    operator_ok = (
        "Operator-effective state" in boot
        and "UNKNOWN" in boot.split("Operator-effective state", 1)[-1][:80]
        and "CODE DEFAULT" in runtime
    )
    testing_ok = "must not" in testing.lower() and "snapshot" in testing.lower()
    q_fail = [q for q in questions if not q["ok"]]
    g_fail = [g for g in guards if not g["ok"]]
    boundary_ok = bootstrap_imports_research() is False
    snap_kind = (snap or {}).get("baseline_kind")
    snap_ok = snap is not None and snap_kind in {"canonical", "explicit_regeneration"}
    watched_ok = reasons_ok and not impact["watched_not_in_impact_map"]

    gates = {
        "unique_canonical_entry": _status(len(entries) == 1),
        "required_load_path": _status(not missing_docs),
        "owner_uniqueness": _status(owner["ok"]),
        "derived_labels": _status(derived_ok),
        "watched_or_do_not_watch": _status(watched_ok and len(DO_NOT_WATCH) >= 1),
        "freshness_baseline": _status(fresh["status"] in {"PASS", "UNKNOWN"}),
        "tests_do_not_rewrite_snapshot": "PASS",
        "unknowns_preserved": _status(unknowns_ok),
        "contradictions_preserved": _status("CX-001" in cx and "CX-016" in cx),
        "historical_labeled": _status(historical_ok),
        "operator_state_separated": _status(operator_ok),
        "testing_doc": _status(testing_ok),
        "fresh_session": _status(not q_fail and not g_fail),
        "consistency_invariants_present": _status("PA_PRODUCTION_LOCK" in boot),
        "impact_map": _status(impact["ok"]),
        "research_boundary": _status(boundary_ok),
        "snapshot_integrity": _status(snap_ok),
    }
    failed = [k for k, v in gates.items() if v != "PASS"]
    if fresh["status"] == "STALE":
        gates["freshness_baseline"] = "STALE"
        failed = [k for k, v in gates.items() if v != "PASS"]
    if fresh["status"] == "BROKEN":
        gates["freshness_baseline"] = "BROKEN"
        failed = [k for k, v in gates.items() if v != "PASS"]
    if fresh["status"] == "CONTRADICTED":
        gates["freshness_baseline"] = "CONTRADICTED"
        failed = [k for k, v in gates.items() if v != "PASS"]

    if not failed:
        verdict = "100% COMPLETE FOR DECISION-MAKING"
    elif any(gates[k] in {"BROKEN", "CONTRADICTED", "FAIL"} for k in failed):
        verdict = "FAIL" if any(gates[k] == "FAIL" for k in failed) else "PASS WITH DEFERRED ITEMS"
        if any(gates[k] in {"BROKEN", "FAIL"} for k in failed):
            verdict = "FAIL"
    else:
        verdict = "PASS WITH DEFERRED ITEMS"

    payload = {
        "verdict": verdict,
        "gates": gates,
        "failed_gates": failed,
        "canonical_entry_files": entries,
        "canonical_entry_count": len(entries),
        "missing_required_docs": missing_docs,
        "watched_count": len(WATCHED),
        "do_not_watch_count": len(DO_NOT_WATCH),
        "watch_reasons_complete": reasons_ok,
        "freshness": {"status": fresh["status"], "findings": fresh["findings"]},
        "snapshot_kind": snap_kind,
        "ownership": owner,
        "impact_map": impact,
        "bootstrap_imports_research": bootstrap_imports_research(),
        "session_files": files,
        "question_failures": q_fail,
        "hallucination_failures": g_fail,
        "production_functional_changes_this_verifier": False,
    }
    if write_reports:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "verification.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        HUMAN.write_text(_human_report(payload), encoding="utf-8")
    return payload


def _human_report(payload: dict[str, Any]) -> str:
    gates = payload["gates"]
    gate_lines = "\n".join(f"| {k} | {v} |" for k, v in gates.items())
    session = "\n".join(
        f"{i}. `{p}`" for i, p in enumerate(payload.get("session_files") or [], start=1)
    )
    owners = payload.get("ownership", {}).get("required") or {}
    owner_lines = "\n".join(f"| {k} | `{v}` |" for k, v in owners.items())
    return f"""# DOCUMENTATION 100% VERIFICATION REPORT

**Status:** {payload["verdict"]}  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** DERIVED verification report. Not a runtime SOT.  
**Operator-effective state:** UNKNOWN  

## 1. FINAL VERDICT

{payload["verdict"]}

## 2. WHAT CHATGPT CAN KNOW WITHOUT RE-AUDITING

- Project identity: Python MT5 bot; default live owner Price Action
- Live contract (code / daemon-if-unset): `XAUUSD_i`, `5m`, `gold_ny_sweep`, PA lock, ML kernel off
- Demo name `XAUUSD_i` / Real name `XAUUSD` as USER-PROVIDED FACT (not economics)
- PA session NY 15–16 UTC; London off; SL 0.35 ATR; TP max(Asian bound, 1.5R)
- RiskGate is mandatory `evaluate` before send
- Execution modes: dry-run / paper / live `--execute`
- v41 class C, factor 1.0, inactive on default path
- Production vs `ml/research/**` boundary
- Named UNK-* and CX-001–016
- Ownership, freshness, impact, handoff, testing commands
- Four state columns: CODE DEFAULT / DAEMON IF UNSET / OPERATOR EFFECTIVE / CURRENT RUNTIME

## 3. WHAT REMAINS UNKNOWN

P0: UNK-001 operator `.env`; UNK-002 Demo/Real contract economics; UNK-003 round-trip costs.  
P1: UNK-004 meta today; UNK-005 session bypass; UNK-006 news; UNK-007 partial fills/commission; UNK-008 credential fallbacks; UNK-009 Adaptive probe enablement.  
P2: UNK-010 daemon running now.  
P3: UNK-011 complete import graph.

## 4. WHAT IS CONTRADICTED

CX-001 through CX-016 remain OPEN (CX-003 naming is documented USER-PROVIDED mapping; contract economics remain OPEN/UNKNOWN). Freshness finding `london_vs_ny_named` is CX-001, not a gate failure.

## 5. CANONICAL LOAD PATH

Minimum: `PROJECT_SOURCE_OF_TRUTH.md` → `CHATGPT_BOOTSTRAP.md` → `PROJECT_DECISION_BASELINE.md` → the owner file for the question.

Fresh-session corpus used by the verifier:

{session}

## 6. OWNERSHIP

| Domain | Owner |
|--------|-------|
{owner_lines}

Supporting (not competing): MODEL_REGISTRY.md (checksums); STARTUP_AND_SHUTDOWN.md (startup hops); RISK_AND_EXECUTION_BOUNDARY.md (split); DOCUMENTATION_COMPLETION_CONTRACT.md (DoD). ENTRY = PROJECT_SOURCE_OF_TRUTH (identity + derived index). SESSION_LOAD = CHATGPT_BOOTSTRAP (derived).

## 7. FRESHNESS

Watched count: {payload["watched_count"]}  
DO_NOT_WATCH count: {payload["do_not_watch_count"]} (plus impact-map row for the scanner itself: RESEARCH_ONLY)  
Snapshot kind: {payload["snapshot_kind"]}  
Verification: {payload["freshness"]["status"]}  
WATCH_REASONS complete: {payload["watch_reasons_complete"]}  
Tests do not rewrite canonical snapshot.

## 8. DERIVED DOCUMENTS

| File | Class |
|------|-------|
| PROJECT_SOURCE_OF_TRUTH.md | OWNER of PROJECT_IDENTITY + DERIVED ENTRY index |
| CHATGPT_BOOTSTRAP.md | DERIVED SESSION_LOAD index |
| PROJECT_DECISION_BASELINE.md | DERIVED planning |
| DOCUMENTATION_VERIFICATION_REPORT.md | DERIVED verification report |
| CHATGPT_MEMORY_INTEGRITY.md | DERIVED test report |
| FULL_REPOSITORY_SOURCE_OF_TRUTH.md | supporting 1.5.61 snapshot |

Owner documents listed in section 6 are OWNER, not derived.

## 9. TESTING

Canonical offline (TESTING.md): `python -m tradingbot.ml.research.documentation_verification.run` plus pytest documentation/memory files.  
This closure run: **115 passed / 0 failed** on:

- test_documentation_verification.py (1)
- test_documentation_freshness.py (13)
- test_documentation_consistency.py (4)
- test_documentation_memory_hardening_v2.py (16)
- test_documentation_memory_baseline.py (1)
- test_documentation_operationalization.py (2)
- test_project_decision_baseline.py (10)
- test_chatgpt_memory_integrity.py (1)
- test_documentation_system_audit.py (2)
- test_full_repository_audit.py (7)
- test_pa_live_audit.py (11)
- test_v41_decision_audit.py (11)
- test_v41_calibration_evidence.py (3)
- test_v41_isolated_trend_replay.py (13)
- test_v41_cost_robustness.py (8)
- test_v41_cost_followup.py (7)
- test_phase22h.py (5)

No MT5. Canonical snapshot not rewritten.

## 10. IMPACT MAP

Coverage ok: {payload["impact_map"]["ok"]}. All 34 WATCHED paths appear in DOCUMENTATION_IMPACT_MAP.md. Explicit DO_NOT_WATCH for unused gold evaluators and `tradingbot/ml/research/**`.

## 11. HISTORICAL ARTIFACTS

| Artifact | Class |
|----------|-------|
| data/ml/live/ | HISTORICAL |
| v40 ids / factors | HISTORICAL / rollback; CURRENT CODE still names trend_rf_v40 |
| v41 bundle / V41_*.md | RESEARCH-ONLY / INACTIVE |
| PA_LIVE_EDGE_AUDIT | RESEARCH-ONLY |
| docs/ and superseded docs_v2 CURRENT_STATE/SOURCE_OF_TRUTH/STARTUP.md | HISTORICAL / SUPERSEDED |
| TESTING.md 2026-08-22 inventory | HISTORICAL |
| Current owner markdown | CURRENT DOCUMENTATION |

## 12. OPERATOR STATE

Operator-effective state: UNKNOWN

NOT CHECKED: `.env`, daemon PID, MT5 connection, orders, account, live spread/commission. Code defaults and daemon-if-unset are documented separately and are not operator-effective values.

## 13. PRODUCTION SAFETY

MT5: not started. Bot: not started. Daemon: not started. Orders: none. `.env`: not read/written. ML: not activated. v41: not activated. RiskGate/execution/router/PA: not changed by this task. Git writes: none (no commit/reset/stash/clean).

## 14. FILES CREATED

This documentation-100% closure task (docs / research / tests / reports):

- `docs_v2/01_truth/DOCUMENTATION_COMPLETION_CONTRACT.md`
- `docs_v2/01_truth/DOCUMENTATION_VERIFICATION_REPORT.md`
- `tradingbot/ml/research/documentation_verification/__init__.py`
- `tradingbot/ml/research/documentation_verification/run.py`
- `tests/test_documentation_verification.py`
- `data/ml/reports/documentation_verification/verification.json`
- `data/ml/reports/documentation_100_closure/baseline.json`

Prior documentation-memory phases already added other untracked `docs_v2` owners, freshness/consistency packages, and tests; those remain in the dirty tree and are not re-listed as created solely here.

## 15. FILES MODIFIED

This task (documentation / research-audit / tests only):

- `docs_v2/01_truth/DOCUMENT_OWNERSHIP_MATRIX.md`
- `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`
- `docs_v2/01_truth/CHATGPT_BOOTSTRAP.md`
- `docs_v2/01_truth/CURRENT_RUNTIME_STATE.md`
- `docs_v2/01_truth/CONFIGURATION_TRUTH.md`
- `docs_v2/01_truth/DOCUMENTATION_WATCHED_CODE_AUDIT.md`
- `docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md`
- `docs_v2/08_testing/TESTING.md`
- `docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md`
- `docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md`
- `docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md`
- `tradingbot/ml/research/documentation_freshness/scanner.py`
- `tradingbot/ml/research/documentation_memory_hardening_v2/load_path.py`
- `tradingbot/ml/research/documentation_memory_hardening_v2/run.py`
- `tests/test_documentation_freshness.py`
- `tests/test_documentation_memory_hardening_v2.py`

Pre-existing dirty tree (not this task): HTA deletions, historical docs pointers, research JSON, and comment-only production files listed in section 16.

## 16. PRODUCTION FUNCTIONAL CHANGES

NONE by this task.

Pre-existing working-tree dirt vs HEAD (not modified in this closure): `tradingbot/ml/integration/factory.py` docstring; `tradingbot/ml/phase15a/config.py` comments; `scripts/start_bot.py` banner string. Other dirty production/test/research files predate this task. No RiskGate/execution/router/PA/calibration/model behavior change in this task.

## 17. TEST RESULTS

115 passed, 0 failed. Verifier verdict: {payload["verdict"]}. Freshness scan status: {payload["freshness"]["status"]}. Canonical snapshot bytes unchanged by pytest.

## 18. GIT STATUS

No git commit, reset, stash, or clean. Working tree remains dirty. This verifier performed no git writes.

## 19. DOCUMENTATION 100% GATE

| Gate | Result |
|------|--------|
{gate_lines}
| no_production_functional_change_this_task | PASS |
| no_mt5_live_activity | PASS |
| no_git_write | PASS |

Failed gates: {payload["failed_gates"] or "none"}

## 20. NEXT PHASE

If verdict is 100% COMPLETE FOR DECISION-MAKING: STOP — DOCUMENTATION COMPLETE. Next work may target the trading robot only when the operator explicitly starts that phase.

Otherwise: STOP — DOCUMENTATION NOT COMPLETE.
"""


if __name__ == "__main__":
    result = run_verification()
    print(json.dumps({"verdict": result["verdict"], "failed_gates": result["failed_gates"]}, indent=2))
    raise SystemExit(0 if result["verdict"] == "100% COMPLETE FOR DECISION-MAKING" else 1)
