# Documentation Update Protocol

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of CHANGE_CONTROL procedure.  
**Operator-effective state:** UNKNOWN  

Rule: **No important code change without documentation impact analysis.**

ChatGPT reads canonical docs. Cursor changes code, then updates docs, then verifies.

---

## 1. Ownership

| Asset | Owner |
|-------|--------|
| Canonical `docs_v2` (this memory layer) | Cursor after code-cited verification |
| `PROJECT_SOURCE_OF_TRUTH.md` | Single entry — update if live owner/path/ML/lock/symbol/TF changes |
| Research evidence `V41_*`, `PA_LIVE_EDGE_AUDIT` | Frozen; add **new** files for new phases |
| Historical `docs/` | Do not delete; optional pointer only |
| Production Python | Not documentation. Do not change production to simplify docs. |

## 2. Canonical hierarchy

1. `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md` (**only** `Canonical-Entry: true`)  
2. Subsystem canonical files listed in `documentation_system_audit/run.py::CANONICAL`  
3. Supporting audits and research  
4. Superseded-keep / historical  

Code > tests > canonical docs > supporting > historical.

## 3. Update triggers

Any change to: factory selection, router, PA lock, RiskGate, execution, live config, PA presets, symbols/TFs, ML flags/ids/calibration, startup scripts, meta gating.

**A production-code change makes documentation untrusted until verification completes.** ChatGPT must treat owner/derived docs as STALE until Cursor reports freshness + consistency PASS (or explicit UNKNOWN/BROKEN).

Required sequence:

```text
CODE CHANGE
→ identify affected domain
→ identify owner
→ update owner
→ update derived documents
→ run consistency
→ run freshness
→ verify safety
→ produce Cursor handoff report
```

## 4. Required evidence

Every changed factual claim: `path` + `symbol`. Runtime env values: “code default X; operator override UNKNOWN” unless a sanitized dump exists.

## 5. Citation format

`` `tradingbot/config/live.py::PRIMARY_SYMBOL` ``

## 6. Contradiction handling

Add/update an ID in `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`. Do not rewrite history to hide the conflict.

## 7. Historical artifacts

Do not delete. Do not rewrite `data/ml/reports/phase15_*` JSON.

## 8. Research artifacts

Remain research-only. Do not import into `build_kernel_live`.

## 9. Production change documentation

If production functional files change (forbidden in 1.5.62–70): update entry + affected spec + contradiction registry + run verifier. This batch must report **NONE**.

## 10. Verification checklist

- [ ] Canonical entry still unique (`Canonical-Entry: true` once)  
- [ ] Referenced canonical paths exist  
- [ ] `PA_PRODUCTION_LOCK` default true  
- [ ] `USE_ML_KERNEL` default off  
- [ ] `TREND_MODEL_ID` still `trend_rf_v40`  
- [ ] v41 still inactive / 1.0 fallback  
- [ ] `pytest tests/test_documentation_consistency.py tests/test_documentation_system_audit.py`  
- [ ] No `.env` read/write; no MT5/bot start  

## 11. Cursor handoff report (formal)

Every Cursor report to ChatGPT after a production or documentation-memory change **must** contain:

1. Changed files
2. Production vs research classification
3. Behavioral impact
4. Owner docs changed
5. Derived docs changed
6. Freshness result
7. Consistency result
8. Tests
9. Git status
10. Safety status
11. Remaining UNKNOWNs
12. Remaining contradictions
13. Recommended next step

This is the ChatGPT↔Cursor handoff contract (also `CHATGPT_CURSOR_WORKFLOW.md` STEP 8).

## 12. Tooling

```text
python -m tradingbot.ml.research.documentation_consistency.run
python -m tradingbot.ml.research.documentation_system_audit.run
python -m tradingbot.ml.research.documentation_freshness.run
python -m tradingbot.ml.research.documentation_freshness.run --regenerate-baseline
python -m tradingbot.ml.research.documentation_verification.run
```

`--regenerate-baseline` is the **only** allowed rewrite of `data/ml/reports/documentation_freshness/snapshot.json`. Pytest must not call it. Missing snapshot = UNKNOWN, not PASS.
