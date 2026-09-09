# Knowledge Contract

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of SAFETY_INVARIANTS and the claim schema. Not operator-effective state.  
**Operator-effective state:** UNKNOWN  
**Verification method:** static_code_inspection + canonical docs from 1.5.62–70  
**Machine-readable:** `docs_v2/01_truth/knowledge_contract.json`

Hierarchy for **runtime truth**:

```text
CODE > CANONICAL DOCUMENTATION > AUDIT ARTIFACT > MEMORY/ASSUMPTION
```

Canonical documentation is the **primary ChatGPT knowledge layer**. When code changes, documentation must be updated and reverified. Documentation must never invent runtime facts.

Owner of truth for executable behavior: **code**.  
Owner of ChatGPT session memory: **canonical docs**, kept in sync by Cursor.

---

## Domains

| Domain | Owner document | Runtime owner |
|--------|----------------|---------------|
| SYSTEM_IDENTITY / PROJECT_IDENTITY | PROJECT_SOURCE_OF_TRUTH.md | `live.py::PRIMARY_SYMBOL`, factory, PA preset |
| LIVE_RUNTIME / LIVE_CONTRACT | CURRENT_RUNTIME_STATE.md | kernel + factory + router |
| STARTUP | STARTUP_AND_SHUTDOWN.md | `start_bot.py`, daemon, watchdog |
| CONFIGURATION | CONFIGURATION_TRUTH.md | dotenv / live / daemon-if-unset |
| STRATEGY / PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | PA + presets |
| RISK / RISKGATE | RISKGATE_SPEC.md | `RiskGate.evaluate` |
| EXECUTION | EXECUTION_FLOW.md | `Mt5ExecutionAdapter.execute` |
| DATA | DATA_CONTRACTS.md | MT5 adapter + research parquet |
| ML | ML_SYSTEM_STATE.md | flags, calibrator, bundles |
| RESEARCH / PRODUCTION_BOUNDARY | PRODUCTION_RESEARCH_BOUNDARY.md | `ml/research/**` |
| TESTING | docs_v2/08_testing/TESTING.md | `tests/` |
| DOCUMENTATION / CHANGE_CONTROL | DOCUMENTATION_UPDATE_PROTOCOL.md | docs_v2 |
| UNKNOWN / CONTRADICTIONS | KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md | n/a |
| SAFETY_INVARIANTS | KNOWLEDGE_CONTRACT.md | listed constants; bootstrap §15 is DERIVED |
| GIT_STATE | Cursor report only | git (do not clean) |

Minimum claims are in `knowledge_contract.json`. Selected FACTS:

| Claim | Status | Evidence | Confidence | Affected runtime |
|-------|--------|----------|------------|------------------|
| Default live owner is Price Action | FACT | `factory.build_strategy_registry` + `is_pa_production_lock` | HIGH | live signals |
| Symbol `XAUUSD_i` | FACT | `live.py::PRIMARY_SYMBOL` | HIGH | MT5 |
| Kernel TF `5m` when router on | FACT | `get_live_config()` | HIGH | loop |
| Preset `gold_ny_sweep`, NY 15–16, London off | FACT | `PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]` | HIGH | PA |
| `USE_ML_KERNEL` defaults false unless env set | FACT | `is_ml_kernel_enabled` | HIGH | factory |
| `PA_PRODUCTION_LOCK` default true | FACT | `LIVE_TRADING_CONFIG` | HIGH | router select |
| Lock is also `not adaptive and not vol` | FACT | `is_pa_production_lock` | HIGH | selection |
| Missing tick → spread 999 reject | FACT | `RiskGate._live_spread_pips` | HIGH | entries |
| v41 inactive on default daemon | FACT | kernel off | HIGH | none |
| v41 factor 1.0 | FACT | `engine_calibration_factor` else-branch | HIGH | ML path only |
| v41 class C | RESEARCH-ONLY | V41_DECISION_AUDIT.md | HIGH for research | none |
| Operator `.env` | UNKNOWN | not read | n/a | maybe live |
| Demo `XAUUSD_i` vs Real `XAUUSD` economics | UNKNOWN | names are expected mapping; EV-EQ-01 INSUFFICIENT EVIDENCE (specs NOT COLLECTED) | n/a | sizing/costs |
| Broker round-trip cost | UNKNOWN | no class-A tape | n/a | economics |
| `london_sweep` means London hours | CONTRADICTION | name vs preset | — | operator error |

`historical_or_current`: claims above are **current** unless marked RESEARCH-ONLY or HISTORICAL.

Do not use ASSUMPTION as a substitute for UNKNOWN.
