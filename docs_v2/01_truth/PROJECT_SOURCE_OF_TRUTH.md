# Project Source of Truth

**Canonical-Entry:** true  
**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of PROJECT_IDENTITY and canonical navigation. Other sections below are **DERIVED FACT** indexes into owner documents. Not operator-effective state.  
**Operator-effective state:** UNKNOWN  
**Verification method:** executable code + Phase 1.5.61/62–70 documentation consolidation  
**Live impact of this file:** none  
**Knowledge kinds:** VERIFIED FACT (code-cited) · DOCUMENTED FACT · DERIVED FACT · UNKNOWN · CONTRADICTION · INFERENCE (forbidden as runtime truth)

This is the **only** top-level canonical entry for ChatGPT. Every session should then load `docs_v2/01_truth/CHATGPT_BOOTSTRAP.md`. Deeper files are linked below. Executable code still outranks this document.

**Not this file:** `SOURCE_OF_TRUTH.md` (superseded keep), `FULL_REPOSITORY_SOURCE_OF_TRUTH.md` (supporting 1.5.61 snapshot).

---

## 1. What the robot is

A Python MetaTrader 5 trading system. Default live owner is **Price Action** on broker symbol **`XAUUSD_i`**, kernel timeframe **`5m`**, preset **`gold_ny_sweep`**, NY window **15–16 UTC**.

Evidence: `tradingbot/config/live.py::PRIMARY_SYMBOL`, `get_live_config()`, `tradingbot/config/pa_symbol_tf_presets.py` (`XAUUSD`/`M5`).

## 2. How it starts (default Windows path)

```text
start/START_BOT.bat
  → scripts/start_bot.py
  → scripts/start_live_daemon.ps1
  → scripts/run_live_watchdog.py --execute
  → python -m tradingbot --loop --execute
  → live_runner.run_live_loop
  → bootstrap.build_kernel_live
```

Evidence: `start/START_BOT.bat`, `scripts/start_bot.py`, `scripts/start_live_daemon.ps1`, `scripts/run_live_watchdog.py`, `tradingbot/__main__.py`, `tradingbot/application/live_runner.py`, `tradingbot/application/bootstrap.py::build_kernel_live`.

Detail: `docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md`, `LIVE_RUNTIME_PATH.md`.

## 3. What runs live

`TradingKernel` six stages: Data → Indicators → Signal → SignalFilter → Risk → Execution.

Signal owner: `factory.build_strategy_registry` → `MultiEngineRouterRegistry` → PA only while production lock holds → `LegacyStrategyRegistry` → `PriceActionStrategy` → `evaluate_gold_setup` → `evaluate_m5_london_sweep` → `RiskGate.evaluate` → `Mt5ExecutionAdapter.execute`.

Forming bar dropped: `SignalStage.run` calls `exclude_forming_bar` (`tradingbot/domain/ohlcv.py`).

## 4. What is shadow

- VOL and Adaptive **signals are generated** on the router and **not selected** when `is_pa_production_lock` is true (`multi_engine_router.py`).
- `ENABLE_ML_SHADOW`: code default **false**; daemon sets **true** if unset. Wrap is log-only (`factory._maybe_wrap_shadow`).
- `META_OBSERVER_MODE` default **false**; if true, meta never rejects.

## 5. What is research

`tradingbot/ml/research/**`, isolated v41/PA/full-repo/documentation audits, `scripts/run_phase*`. Research scripts may set `USE_ML_KERNEL=1` **in-process**. That is not the daemon default.

Phase 28.0–28.4 (`docs_v2/02_research/PHASE28_*.md`) are RESEARCH ONLY performance validation on canonical `XAUUSD_i` M5. They do not authorize live trading and do not satisfy `COMPLETE_COSTS_REQUIRED`. TRAIN/VALIDATION in Phase 28.2 are descriptive only. Phase 28.3 Monte Carlo uses stored baseline trades only; spread/slippage shocks are MODELED, not realized. Phase 28.4 diagnoses the 24 RAW setups without changing strategy, RiskGate, RR, or parameters.

Phase 29 (`docs_v2/02_research/PHASE29_RESEARCH_TAPE.md`) is RESEARCH/data-engineering: longest defensible `XAUUSD_i` tape. It does not overwrite the Phase 28 M5 snapshot, does not merge logical `XAUUSD`, and does not authorize live trading.

Phase 30 (`docs_v2/02_research/PHASE30_UNCHANGED_STRATEGY_EVALUATION.md`) replays unchanged production `gold_ny_sweep` on that canonical tape. RAW / EXECUTABLE / FILLED stay separate. Conclusion is INDETERMINATE. Not live authorization.

Phase 31 (`docs_v2/02_research/PHASE31_EVENT_INDEPENDENCE.md`) audits whether those RAW signals are independent market events. Official event = (UTC date, Asian high, Asian low, side). Conclusion is HIGH_DEPENDENCE. Not a strategy failure. Not live authorization.

Phase 32 (`docs_v2/02_research/PHASE32_WALK_FORWARD.md`) is chronological 60/20/20 walk-forward of the unchanged strategy. TRAIN/VALIDATION are descriptive. Conclusion is INSUFFICIENT_SAMPLE. Not live authorization.

Phase 33 (`docs_v2/02_research/PHASE33_ROBUSTNESS.md`) is pre-declared diagnostic robustness on that baseline. Not optimization. Conclusion is INSUFFICIENT_SAMPLE. Not live authorization.

Phase 34 (`docs_v2/02_research/PHASE34_STATISTICAL_VALIDATION.md`) is bootstrap/Monte Carlo on Phase 30 RAW and Phase 31 events. Signal-level is not independent evidence. Conclusion is INSUFFICIENT_SAMPLE. Not live authorization.

Phase 35 (`docs_v2/02_research/PHASE35_EXECUTION_REALITY.md`) audits broker cost and execution evidence against the existing AND-gate. Completeness is INCOMPLETE. MODELED is not VERIFIED. No live orders.

Phase 36 (`docs_v2/02_research/PHASE36_STRATEGY_VERDICT.md`) is the research verdict on unchanged `gold_ny_sweep` using Phases 28.0–35. Verdict is INSUFFICIENT_EVIDENCE. Not optimization. Not live authorization. Production remains BLOCKED.

Phase 37 (`docs_v2/02_research/PHASE37_LONG_HORIZON_TAPE.md`) is attach-only long-horizon `XAUUSD_i` tape acquisition. It does not overwrite the Phase 28/30 canonical M5 snapshot, does not merge logical `XAUUSD`, and does not authorize live trading.

Phase 38 (`docs_v2/02_research/PHASE38_INTELLIGENT_EVIDENCE_ACQUISITION.md`) is intelligent evidence acquisition. It may launch an identified MT5 terminal. It does not start the bot, read `.env`, overwrite the frozen M5 snapshot, or authorize live trading.

Phase 39 (`docs_v2/02_research/PHASE39_BROKER_ECONOMICS_EXECUTION.md`) is research-only broker economics and execution evidence resolution on the Phase 38 XAUUSD_i tape. It does not authorize live trading, overwrite the frozen M5 snapshot, or change production.

Phase 40 (`docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`) is research-only full-horizon unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape. It does not authorize live trading, overwrite the frozen M5 snapshot, or optimize.

Phase 41 (`docs_v2/02_research/PHASE41_FINAL_EVIDENCE_CLOSURE.md`) is research-only final evidence closure and production-readiness audit. It does not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 42.

Phase 42 (`docs_v2/02_research/PHASE42_BROKER_COST_EXECUTION_CLOSURE.md`) is research-only broker-cost and execution-telemetry closure. It does not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 43.

Phase 43 (`docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md`) is research-only account-specific broker-cost and executable-readiness closure. It does not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 44.

Phases 44–46 (`docs_v2/02_research/PHASE44_EXECUTABLE_BACKTEST_READINESS.md`, `PHASE45_EVENT_OOS_REGIME_ROBUSTNESS.md`, `PHASE46_PRODUCTION_LIVE_PARITY_AUDIT.md`) are research-only executable-readiness, robustness, and live-parity layers. They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 47.

Phases 47–50 (`docs_v2/02_research/PHASE47_BLOCKER_CLOSURE.md`, `PHASE48_EXECUTABLE_BACKTEST.md`, `PHASE49_FINAL_EVENT_OOS_VALIDATION.md`, `PHASE50_FINAL_PRODUCTION_PARITY.md`) are research-only final blocker/executable/robustness/parity layers. They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start shadow trading.

Phases 51–53 (`docs_v2/02_research/PHASE51_FINAL_EVIDENCE_CLOSURE.md`, `PHASE52_OPTIMIZATION_GATE.md`, `PHASE53_SHADOW_READINESS.md`) are research-only final evidence, optimization-gate, and shadow-specification layers. They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading.

Phases 54–56 (`docs/PHASE54_ACCOUNT_BROKER_EVIDENCE.md`, `docs/PHASE55_COST_SCENARIO_ANALYSIS.md`, `docs/PHASE56_SYMBOL_MAPPING_FINAL_GATE.md`) are research-only account/broker discovery, cost scenarios, and information-value ranking. They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading.

Phases 57–60 (`docs/PHASE57_ACCOUNT_PRODUCT_FORENSICS.md`, `docs/PHASE58_COMMISSION_ACCOUNTABILITY.md`, `docs/PHASE59_SYMBOL_EQUIVALENCE_FORENSICS.md`, `docs/PHASE60_UNIFIED_EVIDENCE_GATE.md`) are research-only G1–G3 forensics and a unified gate. They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading.

Phases 61–63 (`docs/PHASE61_EDGE_SURVIVAL_FORENSICS.md`, `docs/PHASE62_OPERATOR_ACTION_ECONOMICS.md`, `docs/PHASE63_NEXT_STEP_GATE.md`) are research-only edge-survival and next-step economics. They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading.

Phases 64–67 (`docs/PHASE64_STRATEGY_EVENT_FORENSICS.md`, `docs/PHASE65_DIAGNOSTIC_EXPERIMENTS.md`, `docs/PHASE66_STRATEGY_ROOT_CAUSE.md`, `docs/PHASE67_NEXT_RESEARCH_GATE.md`) are research-only causal diagnosis of the frozen strategy edge. They do not optimize, modify production strategy/RiskGate/Execution, authorize live/shadow, or restart broker forensics.

Phases 68–73 (`docs/PHASE68_EXIT_FORENSICS.md`, `docs/PHASE69_EXIT_GEOMETRY.md`, `docs/PHASE70_EXIT_COUNTERFACTUALS.md`, `docs/PHASE71_EXTREME_WINNER.md`, `docs/PHASE72_EXIT_ROOT_CAUSE.md`, `docs/PHASE73_EXIT_RESEARCH_GATE.md`) are research-only exit forensics on the frozen tape. They do not optimize, modify production strategy/RiskGate/Execution, authorize live/shadow, connect to MT5, or restart broker forensics.

Phases 74–81 (`docs/PHASE74_PROFIT_GIVEBACK_FORENSICS.md` through `docs/PHASE81_EXIT_RESEARCH_GATE.md`) are research-only profit-giveback and predeclared exit counterfactuals. They do not optimize, modify production, authorize live/shadow, connect to MT5, or implement the next design.

Phases 82–89 (`docs/PHASE82_PROFIT_PROTECTION_DESIGN.md` through `docs/PHASE89_PROFIT_PROTECTION_GATE.md`) are research-only profit-protection taxonomy, predeclared counterfactuals, and a design gate. They do not optimize, modify production, authorize live/shadow, connect to MT5, or implement the spec.

Phases 90–97 (`docs/PHASE90_PROFIT_GIVEBACK_PATH_FORENSICS.md` through `docs/PHASE97_PROFIT_PROTECTION_FINAL_GATE.md`) are research-only path/timing/MFE forensics and v2 protection families. They do not optimize, modify production, authorize live/shadow, connect to MT5, or implement an exit spec.

Phases 98–105 (`docs/PHASE98_FIRST_FAVORABLE_STATE.md` through `docs/PHASE105_DISCRIMINATOR_GATE.md`) are research-only causal-state, persistence, retracement, entry, cluster, and discriminator-gate forensics. They do not optimize, modify production, authorize live/shadow, connect to MT5, or implement an exit spec.

Phases 106–113 (`docs/PHASE106_NON_OHLC_DATA_INVENTORY.md` through `docs/PHASE113_NON_OHLC_FINAL_GATE.md`) are research-only non-OHLC data inventory and discriminator gates. They do not download data, connect to MT5, optimize, modify production, or implement an exit spec.

Phase 114 (`docs/PHASE114_NON_OHLC_ACQUISITION_CONTRACT.md`) is a research-only acquisition contract. It does not download data, connect to MT5, read .env, modify production, or implement an exit spec.

Phase 115 (`docs/PHASE115_NON_OHLC_DATA_ACQUISITION.md`) is research-only local XAUUSD_i ingest. It does not connect to MT5, read .env, synthesize ticks, modify production, or implement an exit spec. Phase 116 is source-planning only; data was not downloaded.

Phase 116 (`docs/PHASE116_DATA_SOURCE_RESEARCH.md`) is research-only source planning for full-horizon XAUUSD_i ticks. It does not download data, connect to MT5, read .env, modify production, or claim Phase 117 acquisition without an operator export.

Phase 117 (`docs/PHASE117_OPERATOR_SOURCE_RESOLUTION.md`) is research-only operator source resolution for full-horizon XAUUSD_i ticks. It does not connect to MT5, read .env, download remotely, modify production, implement an exit spec, or start Phase 118.

Phase 118 (`docs/PHASE118_TICK_FORENSIC_VALIDATION.md`) is research-only ingestion and forensic validation of the operator-supplied LiteFinance XAUUSD_i tick export. It does not connect to MT5, read .env, modify production, design exits, or start Phase 119. DATA_ACQUIRED=True; HISTORY_RANGE_STATUS=PARTIAL.

Phase 119 (`docs/PHASE119_HISTORICAL_TICK_RECOVERY.md`) is research-only source resolution for missing pre-2026-07-23 LiteFinance XAUUSD_i ticks. It does not connect to MT5, read .env, download remote data, modify production, design exits, or start Phase 120. CANONICAL_SOURCE_AVAILABLE=False; DATA_ACQUIRED=False.

Phase 120 (`docs/PHASE120_TICK_EXPORT_VERIFICATION.md`) verifies newly supplied operator LiteFinance XAUUSD_i tick exports and measures union coverage with Phase 118. It does not connect to MT5, read .env, modify raw exports, alter production, design exits, or start Phase 121. TICK_EVENT_COVERAGE=27; OUTLIER_COVERED=False.

Phase 121 (`docs/PHASE121_TICK_EXPORT_VERIFICATION.md`) verifies newly supplied operator LiteFinance XAUUSD_i tick exports (Jan-2026 window), unions with Phase118/120, and tests +31.84R tick coverage. No MT5, no .env, raw untouched, no production changes, Phase 122 not started. TICK_EVENT_COVERAGE=61; OUTLIER_COVERED=True.

Phase 122 (`docs/PHASE122_TICK_EXPORT_VERIFICATION.md`) verifies newly supplied operator LiteFinance XAUUSD_i tick exports (Jan-2026 window), unions with Phase118/120, and tests +31.84R tick coverage. No MT5, no .env, raw untouched, no production changes, Phase 123 not started. TICK_EVENT_COVERAGE=77; OUTLIER_COVERED=True.

Phase 123 (`docs/PHASE123_ENGINEERING_DECISION_REVIEW.md`) freezes the tick-export campaign and records the engineering decision: FREEZE_CURRENT_SYSTEM_AND_BUILD_RESEARCH_V2 (event-level foundation before ML/exit redesign). No MT5, no .env, no production changes, no new tick request, Phase 124 not auto-started.

## 6. Active strategies

Only `ACTIVE_STRATEGIES["priceaction"] = True` (`tradingbot/config/strategies.py`). Fourteen other named strategies are **false**.

M15/H4 gold evaluators exist in code but `get_live_config()` forces `TIMEFRAMES=["5m"]` when the router is on.

Spec: `docs_v2/04_strategy/ACTIVE_STRATEGIES.md`, `PRICE_ACTION_LIVE_SPEC.md`.

## 7. Risk architecture

`create_risk_gate` → `RiskGate.evaluate` is mandatory on the kernel path. Missing live tick → spread **999** → reject.

Spec: `docs_v2/05_risk/RISKGATE_SPEC.md`.

## 8. Execution architecture

`Mt5ExecutionAdapter.execute`: dry-run (no order) / paper (simulated) / live `--execute` (broker `order_send`). Daemon starts with `--execute`. Operator `.env` may still set dry-run/paper — **UNKNOWN** (not read).

Spec: `docs_v2/03_runtime/EXECUTION_FLOW.md`, `docs_v2/05_risk/RISK_AND_EXECUTION_BOUNDARY.md`.

## 9. Data architecture

Live bars from MT5 via `Mt5MarketDataAdapter`. Code default live symbol **`XAUUSD_i`** (demo, USER-PROVIDED FACT). Real-account gold name **`XAUUSD`** (USER-PROVIDED FACT). Research candles typically **XAUUSD** parquet. **Naming is expected DEMO/REAL mapping. Contract/economic equivalence is NOT PROVEN.**

Spec: `docs_v2/06_data/DATA_PIPELINE.md`, `DATA_CONTRACTS.md`.

## 10. ML status

| Item | State |
|------|--------|
| `USE_ML_KERNEL` | Default **off** unless env explicitly truthy (`is_ml_kernel_enabled`) |
| Live gate | `evaluate_ml_live_gate` — N/A while kernel off |
| `trend_rf_v40` | Frozen rollback / `TREND_MODEL_ID` — not live selector |
| `trend_rf_v41` | Default **active ML id if kernel used**; **inactive** on daemon; class **C**; factor **1.0** (`engine_calibration_factor` falls through to neutral when engine ≠ `trend_rf_v40`) |
| Meta-labeler | Wired in RiskGate; **can reject** PA; current-day enforcement **NOT PROVEN** |

Spec: `docs_v2/07_ml/ML_SYSTEM_STATE.md`, `MODEL_REGISTRY.md`, `CALIBRATION_STATE.md`.

## 11. Important configuration (code / daemon-if-unset)

**Kind:** DERIVED FACT from `CONFIGURATION_TRUTH.md`. **Operator-effective state:** UNKNOWN.

| Name | Code default | Daemon if unset | Operator `.env` |
|------|----------------|-----------------|-----------------|
| `PA_PRODUCTION_LOCK` | true | not set by daemon (code default applies) | UNKNOWN |
| `MULTI_ENGINE_ROUTER_ENABLED` | true | true | UNKNOWN |
| `USE_ML_KERNEL` | unset → false | `"false"` | UNKNOWN |
| `ENABLE_ML_SHADOW` | false | true | UNKNOWN |
| `VOL_REGIME_ENABLED` | false | false | UNKNOWN |
| `ADAPTIVE_REGIME_ENABLED` | **absent** from `LIVE_TRADING_CONFIG`; factory `.get(..., False)` | false | UNKNOWN |
| `PIPELINE_TIMEOUT_MS` | 500.0 | unused on PA path | n/a |
| `PRIMARY_SYMBOL` | `XAUUSD_i` | n/a | n/a |
| CLI `--tf` | M15 | **not used by daemon** | n/a |

Full map: `docs_v2/01_truth/CONFIGURATION_TRUTH.md`.

## 12. Known unknowns (P0/P1)

P0: operator env overrides; Demo `XAUUSD_i` vs Real `XAUUSD` **contract/economic** equivalence (names are expected mapping); round-trip spread/commission.  
P1: meta gating today; `DEMO_DISABLE_SESSION_FILTER`; news calendar populated; `engine_settings` credential fallbacks used?; partial fills.

Registry: `docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`.

## 13. Known contradictions (do not “fix” in prose)

- `GOLD_STRATEGY_MODE=london_sweep` but London session **off**, NY 15–16 UTC.
- `BacktestConfig.timeframe` default **M5** (Phase 25B; was **M1** pre-25B) — aligned with live **M5**.
- Legacy `docs/` Adaptive-as-default vs router + PA lock.
- `DEMO_MODE=true` in `LIVE_TRADING_CONFIG` vs daemon `--execute`.
- `is_pa_production_lock` is `lock and not adaptive and not vol` — Adaptive env true **defeats** the lock flag.
- `AdaptiveRegimeStrategyRegistry` defaults `_enabled=True` if key missing; factory uses False.
- Dataset `spread_pips` OHLC proxy vs live tick.

## 14. Where deeper documentation lives

| Topic | Canonical file |
|-------|----------------|
| Session load | `docs_v2/01_truth/CHATGPT_BOOTSTRAP.md` |
| Runtime hops | `docs_v2/03_runtime/LIVE_RUNTIME_PATH.md` |
| Architecture | `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md` |
| Boundary | `docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md` |
| Ownership | `docs_v2/01_truth/DOCUMENT_OWNERSHIP_MATRIX.md` |
| Testing | `docs_v2/08_testing/TESTING.md` |
| Documentation DoD | `docs_v2/01_truth/DOCUMENTATION_COMPLETION_CONTRACT.md` |
| Decision baseline (planning; not SOT) | `docs_v2/01_truth/PROJECT_DECISION_BASELINE.md` |
| Knowledge contract | `docs_v2/01_truth/KNOWLEDGE_CONTRACT.md` |
| How to update docs | `docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md` |
| Code→doc map | `docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md` |
| ChatGPT↔Cursor | `docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md` |
| 1.5.61 exhaustive audit | `docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md` |
| v41/PA research evidence | `docs_v2/07_ml/V41_*.md`, `docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md` |
| Production readiness audit (2026-09-02) | `docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md` (RESEARCH-ONLY) |
| Operator / broker evidence templates | `docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md` (templates only; values NOT COLLECTED) |
| Demo/Real symbol & cost design review | `docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md` (DESIGN-ONLY; EV-EQ-01 INSUFFICIENT EVIDENCE) |
| Final broker/cost validation gate | `docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md` — **FINAL_GATE=BLOCKED** (not strategy, profitability, or real-money approval) |

## 15. How documentation is maintained

`docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md`.  
Verifier: `tradingbot/ml/research/documentation_consistency/`.  
Tests: `tests/test_documentation_consistency.py`.

**Do not start a trading-research phase from this file.**
