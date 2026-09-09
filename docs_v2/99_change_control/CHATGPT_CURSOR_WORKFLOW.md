# ChatGPT ↔ Cursor Workflow

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of HANDOFF procedure.  
**Operator-effective state:** UNKNOWN  
**Human remains the bridge.** ChatGPT does not write to the repo. Cursor does not silently change production while “updating docs.”

---

## STEP 1 — Read

ChatGPT reads:

1. `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`
2. `docs_v2/01_truth/CHATGPT_BOOTSTRAP.md`
3. `docs_v2/01_truth/PROJECT_DECISION_BASELINE.md` (planning; not SOT)
4. Only the **owner** subsystem file from `DOCUMENT_OWNERSHIP_MATRIX.md`

ChatGPT is **not** allowed to assume documentation is current merely because it exists. If the task follows a code change, require Cursor freshness output. Watched SHA-256 change → **STALE**.

## STEP 2 — Decide

Architectural/research decision only. Classify: documentation-only / research-only / production-affecting / evidence collection / unsafe.

## STEP 3 — Prompt Cursor

Precise implementation **or** verification prompt. Include safety: no MT5/bot/`.env` unless the human explicitly authorized evidence collection.

## STEP 4 — Inspect

Cursor inspects **actual code** (`path::symbol`). Docs are hypotheses.

## STEP 5 — Implement

Only authorized changes. Documentation-only phases must not edit RiskGate, execution, router, factory runtime, lock, calibrator IDs, bundle.

## STEP 6 — Update docs

Update **owner** documents. Refresh derived summaries in entry/bootstrap if the owned fact changed. Add CX/UNK rather than silently resolving.

## STEP 7 — Verify

Run `tests/test_documentation_consistency.py`, `tests/test_documentation_freshness.py`, `tests/test_documentation_memory_hardening_v2.py`, and domain tests named in the prompt. Freshness tests must **not** rewrite `data/ml/reports/documentation_freshness/snapshot.json`.

## STEP 8 — Report (required Cursor → ChatGPT handoff)

Cursor's final report **must** contain:

1. VERDICT
2. SCOPE
3. FILES INSPECTED
4. FILES MODIFIED
5. PRODUCTION FILES MODIFIED?
6. DOCUMENTATION FILES MODIFIED?
7. TESTS
8. FRESHNESS STATUS
9. CONSISTENCY STATUS
10. UNKNOWNs
11. CONTRADICTIONS
12. SAFETY CHECKS
13. GIT STATUS
14. EXACT NEXT RECOMMENDATION

For any production code modification, each changed file must also appear as:

```text
CODE CHANGE
→ AFFECTED DOMAIN
→ OWNER DOC
→ DERIVED DOCS
→ FRESHNESS RESULT
→ CONSISTENCY RESULT
```

ChatGPT may then make the next architectural decision without asking Cursor to rediscover unrelated repository facts. ChatGPT must still require Cursor after the next production-code change.

## STEP 9 — Review

ChatGPT compares the report to canonical owners. If docs and report disagree, believe **code + tests**, mark docs STALE.

## STEP 10 — Next phase

Only after 9. Do not auto-start unauthorized phases.

---

## Forbidden

| Actor | Must not |
|-------|----------|
| ChatGPT | Invent broker costs, activate ML, treat historical `docs/` as live, treat code defaults as operator-effective state |
| Cursor | Modify production behavior under a documentation prompt; read/write secrets; commit unasked; silently regenerate freshness snapshot from pytest |
| Human | Skip transferring Cursor’s safety block back to ChatGPT |
