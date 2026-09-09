# Document Ownership Matrix

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of document-ownership facts only. Runtime truth remains CODE.  
**Operator-effective state:** UNKNOWN  

Exactly one **authoritative owner** may redefine a named domain. Other files may **reference** or **summarize** and must mark copies as **DERIVED FACT**.

`PROJECT_SOURCE_OF_TRUTH.md` is the **ENTRY** (derived navigation/index **and** PROJECT_IDENTITY owner). It must not compete with subsystem owners for SL/TP, RiskGate hops, or flag tables.

`CHATGPT_BOOTSTRAP.md` is **SESSION_LOAD** (derived session-load index). It must not redefine owner numbers.

---

## Named domain → unique owner

| Domain ID | Role | Domain | Owner (redefines) | Derived summaries allowed in | Historical / do not own |
|-----------|------|--------|-------------------|------------------------------|-------------------------|
| PROJECT_IDENTITY | OWNER + ENTRY index | What the robot is; canonical navigation | `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md` | README.md, PROJECT_DECISION_BASELINE.md | `SOURCE_OF_TRUTH.md` |
| SESSION_LOAD | DERIVED INDEX | Fast session index | `docs_v2/01_truth/CHATGPT_BOOTSTRAP.md` | none (this file is itself derived) | — |
| LIVE_CONTRACT | OWNER | What the runtime contract is (symbol/TF/flags/daemon-if-unset) | `docs_v2/01_truth/CURRENT_RUNTIME_STATE.md` | entry, bootstrap | `CURRENT_STATE.md` |
| LIVE_PATH | OWNER | How execution travels through components | `docs_v2/03_runtime/LIVE_RUNTIME_PATH.md` | entry path block, bootstrap §3 | `LIVE_LOOP.md` |
| CONFIGURATION | OWNER | Precedence and flag tables | `docs_v2/01_truth/CONFIGURATION_TRUTH.md` | bootstrap tables | `CONFIGURATION.md` |
| ARCHITECTURE | OWNER | Component/layer structure | `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md` | COMPONENT_BOUNDARIES | `ARCHITECTURE.md` |
| PA_STRATEGY | OWNER | PA live rules including SL/TP | `docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md` | bootstrap §2–4 | PA_LIVE_EDGE_AUDIT (research) |
| STRATEGY_LIST | OWNER | Which strategy ids are true | `docs_v2/04_strategy/ACTIVE_STRATEGIES.md` | entry | `STRATEGY.md` |
| RISKGATE | OWNER | RiskGate hop order | `docs_v2/05_risk/RISKGATE_SPEC.md` | bootstrap §6 | `RISK.md` |
| EXECUTION | OWNER | Dry-run / paper / live send | `docs_v2/03_runtime/EXECUTION_FLOW.md` | bootstrap §7 | — |
| DATA_CONTRACTS | OWNER | Live vs research identity | `docs_v2/06_data/DATA_CONTRACTS.md` | DATA_FLOW, DATA_PIPELINE | — |
| ML | OWNER | Kernel/shadow/v41 live status | `docs_v2/07_ml/ML_SYSTEM_STATE.md` | bootstrap §9–10 | `ML_STATUS.md`, `data/ml/live/` |
| CALIBRATION | OWNER | Factor meaning / v41 1.0 | `docs_v2/07_ml/CALIBRATION_STATE.md` | MODEL_REGISTRY | — |
| PRODUCTION_BOUNDARY | OWNER | Research vs live import boundary | `docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md` | bootstrap §12 | — |
| UNKNOWNS_CONTRADICTIONS | OWNER | UNK-* and CX-* registry | `docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md` | entry lists | `KNOWN_ISSUES.md` |
| SAFETY_INVARIANTS | OWNER | What must never be assumed or activated | `docs_v2/01_truth/KNOWLEDGE_CONTRACT.md` | bootstrap §15 | — |
| CHANGE_CONTROL | OWNER | How to update docs | `docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md` | — | — |
| IMPACT_MAP | OWNER | CODE → owner → derived → verifier | `docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md` | protocol | — |
| HANDOFF | OWNER | ChatGPT ↔ Cursor steps | `docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md` | bootstrap §16 | — |
| FRESHNESS | OWNER | Watched files, STALE/BROKEN/UNKNOWN, snapshot rules | `docs_v2/01_truth/DOCUMENTATION_WATCHED_CODE_AUDIT.md` | protocol §12 | — |
| TESTING | OWNER | Which tests run offline; snapshot rules | `docs_v2/08_testing/TESTING.md` | protocol | historical inventory in same file |

Supporting (not competing live owners): `MODEL_REGISTRY.md` owns checksum rows; `STARTUP_AND_SHUTDOWN.md` owns startup/shutdown procedure (LIVE_PATH hops 1–6 and 21–22); `RISK_AND_EXECUTION_BOUNDARY.md` owns the risk-vs-execution split; `DOCUMENTATION_COMPLETION_CONTRACT.md` owns the documentation DoD; `PRODUCTION_READINESS_AUDIT.md` is RESEARCH-ONLY (2026-09-02) and must not replace LIVE_CONTRACT / DATA_CONTRACTS / RISKGATE owners; `OPERATOR_BROKER_EVIDENCE_COLLECTION.md` owns operator-evidence **templates** (what to collect, P0 closure evidence, safe methods) and must not replace DATA_CONTRACTS / CONFIGURATION / LIVE_CONTRACT / UNKNOWNS owners or invent broker economics; `DEMO_REAL_SYMBOL_COST_DESIGN.md` owns this design-review artifact only (2026-09-02) and must not replace DATA_CONTRACTS / CONFIGURATION / EXECUTION / RISKGATE or treat proposed `ACCOUNT_ENVIRONMENT` as live.

`Canonical-Entry: true` belongs **only** to `PROJECT_SOURCE_OF_TRUTH.md`.

`PROJECT_DECISION_BASELINE.md` is a **DERIVED** planning document. It does not own runtime facts.

## Split that is not a duplicate owner

| Question | Owner |
|----------|--------|
| What is selected live (symbol, TF, PA, flags)? | LIVE_CONTRACT (`CURRENT_RUNTIME_STATE.md`) |
| What is the hop list from BAT to `order_send`? | LIVE_PATH (`LIVE_RUNTIME_PATH.md`) |
| How are layers wired (factory as architecture)? | ARCHITECTURE (`SYSTEM_ARCHITECTURE.md`) |
| What must ChatGPT never assume / never activate? | SAFETY_INVARIANTS (`KNOWLEDGE_CONTRACT.md`) |

Factory.py changes can stale **all three** of LIVE_CONTRACT, LIVE_PATH, and ARCHITECTURE. That is impact fan-out, not dual ownership of the same fact.

## Rules

1. **Source of truth (runtime):** code.  
2. **References:** cite owner + `path::symbol`.  
3. **Derived summaries:** must not add new numbers/flags. If they drift, freshness/contradiction.  
4. **Historical:** keep; banners; never own current live facts.  
5. **Superseded-keep:** pointer + old body.  
6. **Research evidence** (`V41_*`, `PA_LIVE_EDGE_AUDIT`): own research class only, not live routing.
