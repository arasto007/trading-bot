# ChatGPT Bootstrap

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** DERIVED session index. Not a second source of truth. Not operator-effective state.  
**Operator-effective state:** UNKNOWN  
**Knowledge kinds:** VERIFIED FACT (code-cited) · DOCUMENTED FACT · DERIVED FACT · UNKNOWN · CONTRADICTION · INFERENCE (forbidden as runtime truth)

Navigation owner remains `PROJECT_SOURCE_OF_TRUTH.md`. Subsystem numbers live in owner documents (`DOCUMENT_OWNERSHIP_MATRIX.md`).

Hierarchy: **CODE > CANONICAL DOCS > this derived index > memory**. If this file and code disagree, **code wins** and this file is STALE.

Verification method: static_code_inspection of cited symbols (2026-09-01). Operator `.env`, whether a daemon process exists, MT5 account/orders/spread: **UNKNOWN**.

---

## 1. What this repository is

Python MetaTrader 5 trading bot. Default live owner is **Price Action**, not ML.

Evidence: `tradingbot/ml/integration/factory.py::build_strategy_registry`, `tradingbot/services/pa_production_lock.py::is_pa_production_lock`.

## 2. Documented default live path (code-defined)

**Kind:** DERIVED FACT from `CURRENT_RUNTIME_STATE.md` and PA/config owners.  
**Operator-effective state:** UNKNOWN (not a live probe).

| Item | Code-defined value | Evidence |
|------|--------|----------|
| Symbol | `XAUUSD_i` | `tradingbot/config/live.py::PRIMARY_SYMBOL` |
| Timeframe | `5m` when router on | `get_live_config()` |
| Strategy | `priceaction` only | `tradingbot/config/strategies.py::ACTIVE_STRATEGIES` |
| Preset | `gold_ny_sweep` | `pa_symbol_tf_presets.py` `XAUUSD.M5` |
| Session | NY 15–16 UTC; London **off** | same preset `M5_USE_NY_SESSION`, `M5_USE_LONDON_SESSION` |
| Mode name | `london_sweep` (name ≠ London hours) | `GOLD_STRATEGY_MODE` → `evaluate_m5_london_sweep` |

## 3. Documented default startup chain (code-defined)

```text
start/START_BOT.bat → scripts/start_bot.py → scripts/start_live_daemon.ps1
  → scripts/run_live_watchdog.py --execute
  → python -m tradingbot --loop --execute
  → live_runner.run_live_loop → bootstrap.build_kernel_live
  → factory.build_strategy_registry → MultiEngineRouterRegistry
  → PA lock → LegacyStrategyRegistry → PriceActionStrategy
  → evaluate_gold_setup → evaluate_m5_london_sweep
  → SignalStage.run → ohlcv.exclude_forming_bar → RiskGate.evaluate
  → Mt5ExecutionAdapter.execute
```

Hops: `docs_v2/03_runtime/LIVE_RUNTIME_PATH.md`.

## 4. Active strategy

Live selected: **PA M5 NY sweep**. VOL/Adaptive: **generated, not selected** under lock (`multi_engine_router.py::generate_signal`). Spec: `PRICE_ACTION_LIVE_SPEC.md`.

## 5. Code / daemon-if-unset configuration (not operator-effective)

**Kind:** DERIVED FACT from `CONFIGURATION_TRUTH.md`. Operator column is UNKNOWN.

| Flag | Code default | Daemon if unset | Operator |
|------|----------------|-----------------|----------|
| `USE_ML_KERNEL` | unset → false (`is_ml_kernel_enabled`) | `"false"` | **UNKNOWN** |
| `PA_PRODUCTION_LOCK` | true | not set by daemon | **UNKNOWN** |
| `MULTI_ENGINE_ROUTER_ENABLED` | true | true | **UNKNOWN** |
| `ENABLE_ML_SHADOW` | false | true | **UNKNOWN** |
| `VOL_REGIME_ENABLED` | false | false | **UNKNOWN** |
| `ADAPTIVE_REGIME_ENABLED` | absent from dict; factory False | false | **UNKNOWN** |
| `PIPELINE_TIMEOUT_MS` | 500.0 | unused on PA | n/a |

`is_pa_production_lock` = lock **and** Adaptive off **and** VOL off.

Owner: `CONFIGURATION_TRUTH.md`.

## 6. RiskGate position

Mandatory on kernel path: `RiskGate.evaluate`. Missing tick → `_live_spread_pips` returns **999.0** → spread gate can reject. Meta **can** reject PA if `should_gate()`; today **NOT PROVEN**. Owner: `RISKGATE_SPEC.md`.

## 7. Execution boundary

`Mt5ExecutionAdapter.execute`: dry-run / paper / live `--execute`. Daemon passes `--execute`. Dry-run/paper env: **UNKNOWN**. Commission/partial fills: **UNKNOWN**. Owner: `EXECUTION_FLOW.md`.

## 8. Data reality

Live: MT5 `XAUUSD_i` M5 (demo name, USER-PROVIDED FACT); forming bar dropped (`ohlcv.py::exclude_forming_bar`). Real gold name: `XAUUSD` (USER-PROVIDED FACT). Research: typically `XAUUSD` parquet. **Naming ≠ automatic contradiction.** Contract/economic equivalence **NOT PROVEN**. Dataset `spread_pips` ≠ live tick. Owner: `DATA_CONTRACTS.md`.

## 9. ML reality

ML kernel **off** on default daemon. Shadow wrap log-only if enabled. `data/ml/live/` is **HISTORICAL**, not current owner. Owner: `ML_SYSTEM_STATE.md`.

## 10. v41 status

Inactive. Class **C** (research). Factor **1.0** (`engine_calibrator.py::engine_calibration_factor` else-branch; `TREND_MODEL_ID` is `trend_rf_v40`). Bundle sha256 `a433fa41…153eb6b` must not change. Do not copy v40 factors.

## 11. Research status

`tradingbot/ml/research/**` including v41 isolated, PA audit, doc audits. PA uncosted replay class **B** — not a size-up. Scripts may set `USE_ML_KERNEL=1` in-process only.

## 12. Production / research boundary

PRODUCTION: kernel, factory, router, PA, RiskGate, MT5 adapters, dotenv/live/presets, kill-switch.  
SHADOW: VOL/Adaptive probe; ML shadow.  
RESEARCH: `ml/research/**`.  
Owner: `PRODUCTION_RESEARCH_BOUNDARY.md`.

## 13. Critical unknowns (P0)

Operator env; Demo/Real gold **contract economics** (`XAUUSD_i` vs `XAUUSD` names are expected mapping); round-trip costs. P1: meta today; session bypass; news calendar; credential fallbacks used.

## 14. Open contradictions

`london_sweep` vs NY; backtest M1 vs live M5; Adaptive-as-default `docs/`; `DEMO_MODE` vs `--execute`; lock flag vs Adaptive/VOL env; Adaptive class default True vs factory False; spread proxy vs tick; silent `_i` symbol fallback (CX-017). Registry: `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`.

## 15. Documented safety locks (DERIVED from KNOWLEDGE_CONTRACT)

**Kind:** DERIVED FACT. **Operator-effective state:** UNKNOWN.

Do not: start MT5/bot/daemon; send orders; modify `.env`; open ML gate; change PA lock, RiskGate, execution, router, factory runtime, calibrator IDs, `PIPELINE_TIMEOUT_MS`, frozen v41 bundle. WPSQF default OFF. PositionProtector default off.

## 16. Documentation rules

Read `PROJECT_SOURCE_OF_TRUTH.md` then this file then one subsystem spec. CODE > docs. Unique `Canonical-Entry: true`. Protocol: `DOCUMENTATION_UPDATE_PROTOCOL.md`. Impact: `DOCUMENTATION_IMPACT_MAP.md`. Workflow: `CHATGPT_CURSOR_WORKFLOW.md`.

After a watched production file SHA-256 changes, freshness status is **STALE** until Cursor updates the owner document and explicitly regenerates the canonical snapshot. Pytest must not rewrite that snapshot. ChatGPT must not treat stale docs as current.

## 17. What ChatGPT must NEVER assume

- London hours from `london_sweep`
- ML owns live because files/logs exist
- v41 metrics apply to v40 or to live PA
- Research/real `XAUUSD` and demo `XAUUSD_i` share tick value, contract size, spread, or commission (names differ by design; economics UNKNOWN)
- Dataset spread = broker spread
- `DEMO_MODE=true` blocks `--execute`
- Documentation is current without Cursor verification after code changes
- `.env` equals code defaults
- Class B PA replay or class C v41 is a production size-up

## 18. What ChatGPT should ask Cursor to verify

Sanitized env flags; whether daemon/MT5 running; `symbol_info` identity; current meta journal; git diff of production files vs impact map; freshness verifier; tests listed in the prompt.

## 19. How to classify a proposed change

| Class | Means | Allowed without extra safety? |
|-------|--------|-------------------------------|
| documentation-only | docs/tests/research auditors | yes if no production edits |
| research-only | `ml/research/**`, isolated JSON | yes; must not import into `build_kernel_live` |
| production-affecting | factory, RiskGate, execution, router, presets, live.py, startup | **blocked** unless explicitly authorized |
| evidence collection | read-only MT5/env | needs operator; this batch forbids MT5 |
| unsafe / blocked | activate ML, change lock/calibration/bundle, send orders | **never from ChatGPT assumption** |

## 20. Where to start reading

1. `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`  
2. This file  
3. `docs_v2/01_truth/PROJECT_DECISION_BASELINE.md` (planning; not a second SOT)
4. Only the subsystem owner in `DOCUMENT_OWNERSHIP_MATRIX.md`
5. Operator evidence templates (values NOT COLLECTED): `docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md`
6. Demo/Real design review (no implementation): `docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md`
