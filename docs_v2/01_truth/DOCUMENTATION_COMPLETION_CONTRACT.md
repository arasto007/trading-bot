# Documentation Completion Contract

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of the Definition of Done for ChatGPT decision-memory. Not a runtime SOT.  
**Operator-effective state:** UNKNOWN  

**100% complete** means: a fresh ChatGPT session can make **safe architectural / trading-system decisions** from the canonical load path without Cursor rediscovering the repository.

It does **not** mean every repository file is documented. It does **not** mean broker economics, `.env`, or current process state are known.

---

## Knowledge kinds (allowed uses)

| Kind | Meaning | Allowed as decision basis? |
|------|---------|----------------------------|
| VERIFIED FACT | Code `path::symbol` inspected this verification | Yes for code-defined behavior |
| DOCUMENTED FACT | Owner document states it with citation | Yes if owner is current (not STALE) |
| DERIVED FACT | Copy/summary of an owner fact | Yes only if it matches owner |
| UNKNOWN | Evidence does not exist or was not collected | Yes — **UNKNOWN is success** |
| CONTRADICTION | Two evidenced claims conflict (CX-*) | Yes — keep both; do not pick |
| INFERENCE | Guess, “probably”, unstated default | **Never** as runtime truth |

Forbidden conversions:

- not checked → false  
- UNKNOWN → probably false / default  
- HISTORICAL → CURRENT  
- CODE DEFAULT → OPERATOR EFFECTIVE  
- DAEMON IF UNSET → CURRENT PROCESS  
- USER-PROVIDED FACT (Demo/Real names) → economic equivalence  

Must never manufacture: broker economics, `.env` values, daemon PID, orders, account, trading performance.

---

## Coverage checklist (decision domains)

| # | Domain | Owner / artifact | Done when |
|---|--------|------------------|-----------|
| 1 | Project identity | PROJECT_SOURCE_OF_TRUTH.md (ENTRY = derived index + identity) | Unique Canonical-Entry |
| 2 | Canonical entry | same | Count = 1 |
| 3 | ChatGPT bootstrap | CHATGPT_BOOTSTRAP.md (DERIVED session index) | Load after entry |
| 4 | Live runtime contract | CURRENT_RUNTIME_STATE.md | Symbol/TF/flags code vs daemon-if-unset |
| 5 | Live execution path | LIVE_RUNTIME_PATH.md | BAT → execute hops |
| 6 | Configuration precedence | CONFIGURATION_TRUTH.md | Layers; operator UNKNOWN |
| 7 | Active strategy state | ACTIVE_STRATEGIES.md | priceaction only |
| 8 | PA specification | PRICE_ACTION_LIVE_SPEC.md | Preset, session, SL/TP |
| 9 | RiskGate | RISKGATE_SPEC.md | Role + hop order |
| 10 | Execution boundary | EXECUTION_FLOW.md | dry-run/paper/execute |
| 11 | Data contracts | DATA_CONTRACTS.md | Names mapped; economics UNKNOWN |
| 12 | ML state | ML_SYSTEM_STATE.md | Off default; v41 C / 1.0 |
| 13 | Production/research boundary | PRODUCTION_RESEARCH_BOUNDARY.md | research not in bootstrap |
| 14 | Unknowns | KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md | P0/P1 kept UNKNOWN |
| 15 | Contradictions | same | CX-001–016 preserved unless RESOLVED with evidence |
| 16 | Safety invariants | KNOWLEDGE_CONTRACT.md | Never-assume / never-activate |
| 17 | Ownership | DOCUMENT_OWNERSHIP_MATRIX.md | One owner per Domain ID |
| 18 | Change impact | DOCUMENTATION_IMPACT_MAP.md | CODE → owner → derived → verifier |
| 19 | Freshness | scanner WATCHED + snapshot | STALE/BROKEN/UNKNOWN/PASS |
| 20 | ChatGPT↔Cursor workflow | CHATGPT_CURSOR_WORKFLOW.md | 14-point + production chain |
| 21 | Testing entry | docs_v2/08_testing/TESTING.md | Offline commands; no MT5 |
| 22 | Historical/research artifacts | labeled HISTORICAL / RESEARCH-ONLY | Not treated as live |
| 23 | Derived-document rules | this contract + matrix | Derived never competes |
| 24 | Operator-state separation | LIVE_CONTRACT + CONFIGURATION | Four columns distinct |
| 25 | Final handoff protocol | UPDATE_PROTOCOL + WORKFLOW | Code change → docs untrusted until verified |

---

## Gate: 100% COMPLETE FOR DECISION-MAKING

All items in `python -m tradingbot.ml.research.documentation_verification.run` must be PASS (UNKNOWN allowed only for operator/broker facts, not for missing owners or broken refs).

If a documentation invariant fails: **not 100%**. Use PASS WITH DEFERRED ITEMS or FAIL.
