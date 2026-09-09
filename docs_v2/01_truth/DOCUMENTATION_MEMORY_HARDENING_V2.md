# Documentation Memory Hardening V2

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** AUDIT / protocol summary of the ChatGPT memory layer after hardening v2. Not a second source of truth.  
**Operator-effective state:** UNKNOWN

This document answers how the ChatGPT-facing memory contract works. It does **not** claim whole-repository knowledge.

---

## What is the canonical entry?

`docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md` is the only file with `Canonical-Entry: true`. Duplicate true markers are CONTRADICTED.

## What is the ChatGPT bootstrap?

`docs_v2/01_truth/CHATGPT_BOOTSTRAP.md` is a **DERIVED** session index. It is not operator-effective state. Subsystem numbers live in owner documents.

## What is authoritative?

```text
CODE > CANONICAL DOCS > AUDIT ARTIFACT > MEMORY / ASSUMPTION
```

Owner documents redefine domain facts. Entry and bootstrap may only copy them as DERIVED FACT.

## How is freshness detected?

`tradingbot/ml/research/documentation_freshness/scanner.py` hashes **watched** production files (SHA-256) and compares them to `data/ml/reports/documentation_freshness/snapshot.json`.

No TTL. Missing snapshot = **UNKNOWN**, not PASS. Missing/deleted watched source = **BROKEN**. Hash mismatch = **STALE**. Duplicate canonical entry = **CONTRADICTED**.

## What makes docs stale?

A watched production file's content hash differs from the canonical snapshot, or a canonical doc is missing Status / last-verified metadata. Documentation-only edits do **not** by themselves create code STALE.

## What does UNKNOWN mean?

The fact is not established by code or by a sanitized operator evidence dump. Correct ChatGPT answer: UNKNOWN. Guessing is a failure.

P0 examples: operator `.env`, XAUUSD vs `XAUUSD_i` identity, round-trip costs.

## What is a contradiction?

Two evidenced claims that cannot both be operator-simple (CX-001–CX-016). They stay named. They are not silently reconciled.

## What is derived?

A copy or summary of an owner fact in entry, bootstrap, or another non-owner file. Derived copies must not add numbers. Drift is STALE/CONTRADICTED.

## Which domains have owners?

See `DOCUMENT_OWNERSHIP_MATRIX.md`. Named unique owners include PROJECT_IDENTITY, SESSION_LOAD, LIVE_CONTRACT, LIVE_PATH, CONFIGURATION, ARCHITECTURE, PA_STRATEGY, STRATEGY_LIST, RISKGATE, EXECUTION, DATA_CONTRACTS, ML, CALIBRATION, PRODUCTION_BOUNDARY, UNKNOWNS_CONTRADICTIONS, SAFETY_INVARIANTS, CHANGE_CONTROL, IMPACT_MAP, HANDOFF.

SAFETY_INVARIANTS owner is `KNOWLEDGE_CONTRACT.md`. Bootstrap §15 is derived.

## What must Cursor do after code changes?

Inspect `path::symbol` → update owner doc → refresh derived entry/bootstrap if needed → run freshness + consistency tests → report the 14-point handoff. Explicit `--regenerate-baseline` only after the owner docs match code. Pytest must not rewrite the canonical snapshot.

## What can ChatGPT conclude?

Documented default live path (PA, `XAUUSD_i`, M5, `gold_ny_sweep`, NY 15–16, ML off, v41 C / 1.0 / inactive), named unknowns, named contradictions, where to read next.

## What can ChatGPT NOT conclude?

Operator-effective env, current daemon/MT5/account/orders/spread/commission, symbol economic identity, that docs remain current after unseen code edits, that class B/C research is a size-up.

## What still requires Cursor?

Any production-code change, freshness/consistency status, `path::symbol` verification, git status of production files.

## What still requires operator/MT5?

Sanitized flag dump, `symbol_info` identity, tickets/costs, whether the daemon is actually running.

## What files are deliberately excluded from ChatGPT session load?

- Historical `docs/` and superseded-keep bodies (`SOURCE_OF_TRUTH.md`, `CURRENT_STATE.md`, `STARTUP.md`, …)
- `FULL_REPOSITORY_SOURCE_OF_TRUTH.md` (1.5.61 inventory snapshot)
- Research evidence `V41_*`, `PA_LIVE_EDGE_AUDIT.md` except when the question is research class
- `tradingbot/ml/research/**` auditors
- Whole-repository file lists / dirty-tree history

Load: entry → bootstrap → **one** owner. Not the entire repo.
