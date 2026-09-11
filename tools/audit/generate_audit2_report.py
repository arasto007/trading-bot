#!/usr/bin/env python3
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
rows = json.loads((ROOT / "tools/audit/out/audit2_rows.json").read_text(encoding="utf-8"))
junit_list = json.loads((ROOT / "tools/audit/out/audit2_junit_failures.json").read_text(encoding="utf-8"))
counts = Counter(r["cls"] for r in rows)

def find_tb(node: str) -> str:
    parts = node.split("::")
    name = parts[-1]
    mod = parts[0].replace("tests/", "").replace(".py", "").replace("/", ".")
    for f in junit_list:
        if f.get("name") != name:
            continue
        cls = f.get("classname", "")
        if mod not in cls.replace("tests.", "") and not cls.endswith(mod):
            continue
        if len(parts) == 3 and parts[1] not in cls:
            continue
        return (f.get("traceback_tail") or f.get("message") or "").strip()
    for f in junit_list:
        if f.get("name") == name:
            return (f.get("traceback_tail") or f.get("message") or "").strip()
    return ""

def section_notes(node: str, name: str, cls: str) -> list[str]:
    lines: list[str] = []
    if "project_decision" in node or name == "test_owner_docs_have_epistemic_role":
        lines += [
            "- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.",
            "- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).",
            "- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.",
        ]
    elif name == "test_documentation_verification_gate":
        lines += [
            "- **Expects vs actual:** failed_gates=[]; got derived_labels + freshness_baseline(STALE) + operator_state_separated.",
            "- **Why:** Cascading empty owner docs + stale freshness.",
            "- **Minimal fix:** Restore docs; refresh freshness snapshot deliberately; keep gate strict.",
        ]
    elif "ml_base_dir" in node:
        lines += [
            "- **Expects vs actual:** MLKernelRegistry under USE_ML_KERNEL=true; got MultiEngineRouterRegistry (ML shadow-gated).",
            "- **Why:** STALE_TEST — PA-primary multi-engine router is intentional live wiring.",
            "- **Safe update:** Assert MultiEngineRouterRegistry, or MLKernelRegistry only when router off and ML gate open.",
        ]
    elif "phase15b" in node:
        lines += [
            "- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.",
            "- **Why:** FLAKY_OR_ENV (load/timing).",
            "- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.",
        ]
    elif any(x in node for x in ("phase25e", "phase27_11", "phase27_18")):
        lines += [
            "- **Expects vs actual:** bidask_dataset_count==0; actual 1 (XAUUSD_i_ticks_phase38.parquet).",
            "- **Why:** STALE_TEST inventory drift after Phase 38 ticks.",
            "- **Safe update:** Identify tick file; assert it must not alone complete M5 OHLC historical spread (see overclaim REAL_BUG).",
        ]
    elif "phase26o" in node:
        lines += [
            "- **Expects vs actual:** equivalence_claims==[]; got NOT_PROVEN language flagged as claims.",
            "- **Why:** REAL_BUG tooling false positive.",
            "- **Minimal fix:** Tighten detector; keep test.",
        ]
    elif "phase27_15" in node or name == "test_evidence_gaps_recorded":
        lines += [
            "- **Expects vs actual:** Spread/historical M5 still blocked/missing; collectors mark COMPLETE/True from ticks while notes say No M5 tape.",
            "- **Why:** REAL_BUG evidence/epistemic overclaim — tests correctly refuse.",
            "- **Minimal fix:** Fix collector classification; keep tests.",
        ]
    elif "phase27_16" in node:
        lines += [
            "- **Expects vs actual:** blocker key historical_spread present; absent in current matrix.",
            "- **Why:** STALE_TEST schema evolution.",
            "- **Safe update:** Align keys after confirming spread still blocked in 27.15/27.32.",
        ]
    elif "phase27_19" in node:
        lines += [
            "- **Expects vs actual:** status PASS; artifact FAIL (complete_applicability_can_be_accepted=False).",
            "- **Why:** REAL_BUG in commission applicability self-check path.",
            "- **Minimal fix:** Repair accept/self-check; do not force PASS in the test.",
        ]
    elif "phase27_20" in node or name == "test_contract_and_inventory":
        lines += [
            "- **Expects vs actual:** canonical/direct_XAUUSD_i count 2; actual 6.",
            "- **Why:** STALE_TEST hard-coded census.",
            "- **Safe update:** Expect 6 or bind to phase27_27 totals; keep maps_inserted=false.",
        ]
    elif "phase27_21" in node:
        lines += [
            "- **Expects vs actual:** PASS with A=PROVEN/B=BLOCKED; artifact FAIL with A/B inverted.",
            "- **Why:** STALE_ARTIFACT — needs human re-spec then regenerate.",
            "- **Safe update:** Update collector required_ok + tests together; regenerate JSON/MD.",
        ]
    elif "phase27_30" in node or "phase27_31" in node or ("phase27_32" in node and "schema" in name):
        lines += [
            "- **Expects vs actual:** account_type REAL; artifact UNKNOWN after offline regenerate.",
            "- **Why:** STALE_ARTIFACT identity provenance not reattached.",
            "- **Safe update:** Restore identity from immutable prior REAL evidence without upgrading cost completeness.",
        ]
    elif "phase27_32" in node and "no_component" in name:
        lines += [
            "- **Expects vs actual:** swap grade CURRENT_BROKER_RATE_ONLY; actual REALIZED_ZERO_NOT_PROVEN; gate still BLOCKED.",
            "- **Why:** STALE_TEST label drift.",
            "- **Safe update:** Accept new label if meaning unchanged; keep not-COMPLETE / BLOCKED asserts.",
        ]
    elif "phase27_33" in node and "schema" in name:
        lines += [
            "- **Expects vs actual:** status PASS/PASS_WITH_DEFERRAL; FAILED because required_ok still demands direct_XAUUSD_i==2.",
            "- **Why:** STALE_ARTIFACT coupled to census hard-code.",
            "- **Safe update:** Update collector+tests census; regenerate; keep EV-EQ NOT_PROVEN / FINAL_GATE BLOCKED.",
        ]
    else:
        lines.append(f"- **Why:** {cls}.")
    return lines

lines: list[str] = []
a = lines.append
a("# AUDIT_2 — Failing Test Triage")
a("")
a(f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}")
a("**Phase:** REPORT ONLY — diagnosis only; no fixes applied.")
a("**Sources:** AUDIT_1 baseline + junit; isolation re-runs (docs/phase15b/ml_base_dir/phase25e); logs/phase27_*.json inspection.")
a("")
a("## Epistemic / evidence-gate REAL_BUG flags (read first)")
a("")
a("Do **not** casually mark these stale or delete them. They catch missing memory or overstated evidence.")
a("")
a("| Test | Note |")
a("|------|------|")
for r in rows:
    if r["cls"] != "REAL_BUG":
        continue
    if any(x in r["node"] for x in ("project_decision", "documentation_", "phase27_", "phase26o")):
        a(f"| `{r['node'].split('::')[-1]}` | {r['reason']} |")
a("")
a("Highest severity: `PROJECT_DECISION_BASELINE.md` and `CURRENT_RUNTIME_STATE.md` are **0 bytes in git HEAD** (`0898515`).")
a("Overclaim severity: `data/XAUUSD_i_ticks_phase38.parquet` counted as historical bid/ask, flipping spread COMPLETE / historical_m5_bidask=True while notes still say No M5 tape.")
a("")
a("## 1. Summary table")
a("")
a("| # | Test | Classification | One-line reason |")
a("|---|------|----------------|-----------------|")
for i, r in enumerate(rows, 1):
    short = r["node"].replace("tests/", "")
    a(f"| {i} | `{short}` | **{r['cls']}** | {r['reason']} |")
a("")
a("## 2. Per-test sections")
a("")
for r in rows:
    node = r["node"]
    name = node.split("::")[-1]
    tb = find_tb(node)
    a(f"### `{node}`")
    a("")
    a(f"- **Classification:** **{r['cls']}**")
    a(f"- **One-line:** {r['reason']}")
    a("- **AUDIT_1 error (trimmed):**")
    a("```")
    a(tb[:1200] if tb else "(see logs/audit1_junit.xml)")
    a("```")
    for line in section_notes(node, name, r["cls"]):
        a(line)
    a("")

a("## 3. Classification counts")
a("")
a("| Classification | Count |")
a("|----------------|------:|")
for k in ["REAL_BUG", "STALE_TEST", "STALE_ARTIFACT", "FLAKY_OR_ENV", "UNCLEAR"]:
    a(f"| {k} | {counts.get(k, 0)} |")
a(f"| **Total** | **{sum(counts.values())}** |")
a("")
a("### REAL_BUG breakdown")
a("")
a("- Evidence/epistemic **gaps** (empty docs): 8 (owner + verification + 6 baseline)")
a("- Evidence/epistemic **overclaim** (27.15 x3 + 27.8): 4")
a("- Tooling false positive (26O): 1")
a("- Commission self-check FAIL (27.19): 1")
a("- Ordinary strategy/RiskGate code defects in this set: **0**")
a("")
a("## 4. Integrity")
a("")
a("- Deliverable for this phase: `docs/AUDIT_2_FAILING_TEST_TRIAGE.md`.")
a("- No intentional production/test source fixes.")
a("- No MT5, .env credentials, live orders, or Phase 40 tape access.")
a("")

out = ROOT / "docs" / "AUDIT_2_FAILING_TEST_TRIAGE.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote {out} ({out.stat().st_size} bytes) counts={dict(counts)}")

