# Project Decision Baseline

**Canonical-Entry:** false  
**Status:** VERIFIED (derived planning baseline; code outranks this file)  
**Last verified:** 2026-09-09  
**Epistemic-Role:** DERIVED planning baseline. Not a second source of truth. Not operator-effective state.  
**Operator-effective state:** UNKNOWN  
**Machine twin:** `data/ml/reports/project_decision_baseline/baseline.json`  
**Hierarchy:** CODE > CANONICAL DOCS > AUDIT ARTIFACT > MEMORY/ASSUMPTION  

This file does **not** claim full repository knowledge. It records planning decisions that must stay aligned with executable code and owner docs. If this file and code disagree, **code wins**.

---

## 1. Role and limits

- **CODE > CANONICAL DOCS** (see `PROJECT_SOURCE_OF_TRUTH.md`, `CHATGPT_BOOTSTRAP.md`).
- Full repository knowledge claimed: **false** (aligned with `baseline.json`).
- **Production-ready?** **No** (`baseline.json` `production_ready=false`).
- **MT5 live activation authorized?** **No** (`baseline.json` `mt5_live_activation_authorized=false`).
- Secrets: none in this file or the JSON twin (`secrets_included=false`).

---

## 2. Project goal (DERIVED)

| Layer | Statement | Source |
|-------|-----------|--------|
| Original | Kernel-based MT5 automatic gold trading robot; live and backtest share one pipeline | `baseline.json` `project_goal.original` |
| Current implementation | PA M5 `gold_ny_sweep` live path with RiskGate and MT5 adapters; ML off by default | `baseline.json`; `PROJECT_SOURCE_OF_TRUTH.md` §1–3 |
| Future target | Same architecture with known operator config, known broker economics, evidence-backed strategy, explicit activation gate | `baseline.json` `project_goal.future_target` |

---

## 3. Live environment (CODE DEFAULT)

**Kind:** CODE DEFAULT from executable config. **OPERATOR EFFECTIVE STATE:** UNKNOWN (operator `.env` is UNKNOWN — UNK-001).

| Item | CODE DEFAULT | Evidence |
|------|--------------|----------|
| Symbol | `XAUUSD_i` | `live.py::PRIMARY_SYMBOL`; `CONFIGURATION_TRUTH.md` |
| Timeframe | `5m` when router on | `get_live_config()` in `tradingbot/config/live.py`; `PROJECT_SOURCE_OF_TRUTH.md` §1 |
| Strategy | `priceaction` | `ACTIVE_STRATEGIES`; `factory.py::build_strategy_registry` |
| Preset | `gold_ny_sweep` | `pa_symbol_tf_presets.py`; `CHATGPT_BOOTSTRAP.md` §2 |
| Session | NY 15–16 UTC; London off | same preset; `PRICE_ACTION_LIVE_SPEC.md` |
| PA lock | `PA_PRODUCTION_LOCK` default **true** | `is_pa_production_lock`; `CONFIGURATION_TRUTH.md` |
| ML kernel | `USE_ML_KERNEL` default **off** | `is_ml_kernel_enabled`; `baseline.json` `ml_status` |
| v41 | inactive; class **C**; calibration_factor **1.0** | `baseline.json` `v41_status`; `CHATGPT_BOOTSTRAP.md` §10 |

Mandatory risk path: `RiskGate.evaluate`. Sizing / order value path cites `order_logic.py::order_value` (see `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md` CX-006). Workflow handoff: `CHATGPT_CURSOR_WORKFLOW.md`. Spec: `PRICE_ACTION_LIVE_SPEC.md`.

---

## 4. DEMO/REAL symbol naming (USER-PROVIDED FACT)

| Account | Symbol name | Kind |
|---------|-------------|------|
| Demo | `XAUUSD_i` | USER-PROVIDED FACT |
| Real | `XAUUSD` | USER-PROVIDED FACT |

Source: `PROJECT_SOURCE_OF_TRUTH.md` §9; `CHATGPT_BOOTSTRAP.md` §8; `baseline.json` `demo_symbol` / `real_symbol` / `symbol_naming`.

- DEMO/REAL naming is an expected mapping.
- This is **not** an automatic identity contradiction (`baseline.json` `automatic_identity_contradiction=false`; `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md` EV-EQ-01 / CX-003).
- Contract / economic equivalence: **UNKNOWN** / **NOT PROVEN** (economics OPEN). Do not treat name equality as EV-EQ-01 proof.

---

## 5. CODE DEFAULT vs OPERATOR EFFECTIVE STATE

| Column | Value | Source |
|--------|-------|--------|
| CODE DEFAULT | Documented above from `live.py` / factory / lock | `CONFIGURATION_TRUTH.md` |
| OPERATOR EFFECTIVE STATE | **UNKNOWN** | `baseline.json` `operator_effective_state`; operator `.env` is UNKNOWN (UNK-001) |
| Round-trip costs | **UNKNOWN** / incomplete | UNK-003; `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md` Cost evidence |
| Current process / MT5 session | **UNKNOWN — needs operator input** | not probed by this document |

---

## 6. What is complete / partial / blocked (planning view)

Completed (code path exists): trading kernel pipeline; PA router lock live path; RiskGate code; MT5 execution adapter code; documentation memory layer (`baseline.json` `completed_items`).

Partial: backtest/live parity; meta continuous enforcement; real-account symbol switch; cost model (`baseline.json` `partial_items`).

Blockers (P0): UNK-001 operator_env; UNK-002 demo/real contract economics; UNK-003 round-trip costs (`baseline.json` `blockers`).

---

## 7. Must Not Be Done Yet

Do **not**: Start MT5 / start the bot / send orders; weaken cost gates; assume EV-EQ-01; treat PROXY OHLC spread as historical bid/ask; authorize production from research phases alone.

Source: `CHATGPT_BOOTSTRAP.md` §15; `PRODUCTION_RESEARCH_BOUNDARY.md`; `baseline.json` `forbidden_actions` / `mt5_live_activation_authorized=false`.

---

## 8. Workflow

- ChatGPT: strategic / reasoning (`baseline.json` `workflow.chatgpt`).
- Cursor: implementation / code-verification.
- Human: bridge. Automatic API integration: **false**.
- Handoff contract: `CHATGPT_CURSOR_WORKFLOW.md`.
