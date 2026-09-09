# Documentation Memory Operationalization (verification-only)

**Status:** VERIFIED (inspection; weaknesses recorded, **not repaired**)  
**Last verified:** 2026-09-01  
**Live impact:** none  

JSON: `data/ml/reports/documentation_operationalization/verification.json`

This file does **not** change owners, bootstrap, freshness WATCHED lists, or production code.

---

## Session-load contract (A–R)

| Item | Class | Notes |
|------|-------|--------|
| A What the robot is | **A** DOCUMENTED FACT | Entry + bootstrap; `factory.build_strategy_registry` |
| B What runs live | **A** | PA + router + lock |
| C Exact live path | **A** | Path block; hops owner `LIVE_RUNTIME_PATH.md` |
| D Active strategy | **A** | `priceaction` |
| E Symbol | **A** | `PRIMARY_SYMBOL` |
| F Timeframe | **A** | `5m` when router on |
| G PA preset | **A** | `gold_ny_sweep` |
| H PA SL/TP logic | **B** DERIVED | Numbers live in `PRICE_ACTION_LIVE_SPEC.md`, not bootstrap |
| I RiskGate role/order | Role **A**; full 1–13 order **B** | Owner `RISKGATE_SPEC.md` |
| J Execution boundary | **A** modes; commission **C** UNKNOWN | |
| K ML state | **A** kernel off | operator env **C** |
| L v41 | **A** inactive / 1.0; class C is **RESEARCH-ONLY** | |
| M research/live boundary | **A** | |
| N known unknowns | **A** as UNKNOWN (success) | |
| O contradictions | **E** named, not reconciled | CX registry |
| P maintenance rules | **A/B** | protocol + impact map |
| Q never assume | **A** | bootstrap §17 |
| R subsystem owners | **A** | ownership matrix |

## Minimum document set

Always: `PROJECT_SOURCE_OF_TRUTH.md` + `CHATGPT_BOOTSTRAP.md`.  
Then **one owner** for the decision (PA spec, RiskGate spec, ML state, contradictions, impact map).  
Code inspection required after any production file change, or for P0 evidence.

Bootstrap is an **index/operational memory**, not a copy of all owners. SL/TP and RiskGate hop table correctly remain owner-only (**B**, not a gap).

## Misleading-risk (not fixed)

- Heading “Current live system” can be mistaken for **operator runtime**. Values are **code default / daemon-if-unset**. Operator column is UNKNOWN.
- `SignalStage.exclude_forming_bar` is shorthand (**INFERENCE** if taken as a real symbol).
- Superseded-keep files still exist; bootstrap forbids treating them as live.
- CX-001–016 remain named.

## Ownership weaknesses (not fixed)

- **Safety** has no single owner row (bootstrap §15 + protocol).
- LIVE_RUNTIME split: `CURRENT_RUNTIME_STATE` vs `LIVE_RUNTIME_PATH` vs factory→`SYSTEM_ARCHITECTURE`.
- Derived bootstrap tables not labeled DERIVED per section (matrix says they are derived).

## Freshness weaknesses (not fixed)

- `calibration_policy.py` is on the **impact map** but **not** in `WATCHED` → production edit can **bypass STALE**.
- Also unwatched: `gold_strategies/router.py`, `pa_hardening.py`, `pipeline/signal_stage.py`, `__main__.py`, `START_BOT.bat`, `risk_types.py`.
- `test_documentation_freshness.py` **rewrites** `snapshot.json` → can reset the baseline and produce **false PASS**.
- Doc-only edits do not change SHA of watched code (correct: not STALE for code).
- Missing snapshot → UNKNOWN (correct).

## Production/research

`bootstrap.py` does not import `ml.research` or documentation verifiers. **VERIFIED FACT** from file text.

## Contract result

ChatGPT can use canonical docs as **persistent working memory for architecture/runtime/safety planning** without a full rediscovery.

ChatGPT **cannot** use docs as authority for production activation or live economics. Those remain **UNKNOWN** / Cursor+operator evidence.

Highest remaining bottleneck: **D broker evidence** (with operator `.env` as co-equal P0), not more documentation.
