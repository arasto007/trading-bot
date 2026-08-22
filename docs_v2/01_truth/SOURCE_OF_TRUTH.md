# TradingBot Source of Truth

**Document Status:** PARTIAL  
**System Status:** BASELINE ESTABLISHED (source-code audit complete; runtime evidence partial)  
**Last Updated:** 2026-08-22  
**Baseline commit:** `57bf778c23cefffe508bb49079688b177796f67e`

---

## 1. Purpose

This document defines the authoritative baseline for determining the actual current state of the TradingBot repository.

Its purpose is to establish a single evidence-based reference for:

- what exists
- what is implemented
- what is active
- what is reachable
- what is disabled
- what is partial
- what is planned
- what is deprecated
- what is unknown
- what is proven by source code
- what requires runtime evidence

This document describes the repository.

It does not define what the repository should become.

---

## 2. Core Principle

The executable repository is the primary source of truth.

Documentation is a representation of repository reality.

The following hierarchy applies:

```text
EXECUTABLE SOURCE CODE
        ↓
RUNTIME EVIDENCE
        ↓
TEST EVIDENCE
        ↓
GENERATED ANALYSIS
        ↓
VERIFIED DOCUMENTATION
        ↓
HISTORICAL DOCUMENTATION

Documentation must never override executable behavior.

If documentation conflicts with source code:

```text
CODE > DOCUMENTATION
```

If source code alone cannot prove runtime behavior:

```text
SOURCE CODE + RUNTIME EVIDENCE
```

If sufficient evidence does not exist:

```text
UNKNOWN
```

---

## 3. Current Repository Baseline

The current repository baseline must be established through an evidence-based audit.

The baseline must identify:

1. Repository structure
2. Runtime entry points
3. Application startup chain
4. Configuration system
5. Pipeline architecture
6. Strategy architecture
7. Signal generation
8. Risk controls
9. Execution layer
10. Position management
11. Data pipeline
12. Machine learning components
13. Testing infrastructure
14. Operational services
15. Monitoring and observability
16. Generated artifacts
17. Historical artifacts
18. Known conflicts
19. Unknown states

No section may be marked VERIFIED until the corresponding repository evidence has been inspected.

---

## 4. Evidence Requirements

Every important current-state claim should be traceable to evidence.

Preferred evidence sources:

### Level 1 — Source Code

Examples:

```text
Python modules
classes
functions
configuration implementation
pipeline implementation
strategy implementation
risk implementation
execution implementation
startup implementation
```

### Level 2 — Tests

Examples:

```text
unit tests
integration tests
end-to-end tests
test fixtures
test configuration
```

### Level 3 — Runtime Evidence

Examples:

```text
runtime logs
MT5 state
execution reports
broker responses
heartbeat files
runtime_truth.json
startup reports
trade journals
monitoring output
```

### Level 4 — Generated Analysis

Examples:

```text
module inventory
symbol inventory
dependency graph
configuration inventory
strategy registry inventory
pipeline inventory
```

### Level 5 — Documentation

Documentation may explain evidence but must not become the only evidence for a current-state claim.

---

## 5. Status Vocabulary

Every important component should have one of the following statuses.

### IMPLEMENTED

The implementation exists in source code and the relevant functionality is supported by evidence.

### ACTIVE

The implementation exists and is reachable through the current runtime execution path.

### AVAILABLE

The implementation exists and can potentially be used, but current runtime execution does not prove that it is active.

### PARTIAL

Only part of the intended functionality exists.

### SHADOW

The component exists and may execute or observe behavior, but does not control the final runtime decision.

### DISABLED

The component exists but is explicitly prevented from executing.

### UNREACHABLE

The component exists but the current runtime path cannot reach it.

### PLANNED

The capability is described or intended but does not currently exist as a working implementation.

### DEPRECATED

The component is no longer intended for active use.

### UNKNOWN

Available evidence is insufficient to determine the actual state.

### UNVERIFIED

A claim may be plausible but has not yet been verified against sufficient evidence.

---

## 6. Repository Identity

The following information must be established from the actual repository.

```yaml
repository_name: TradingBot new
repository_root: .
git_branch: master
git_revision: 57bf778c23cefffe508bb49079688b177796f67e
baseline_date: 2026-08-22
commit_message: Initial snapshot - TradingBot New
commit_count: 1
primary_package: tradingbot
evidence: E001
```

`repository_name` is the Git repository root directory name (verified via `git rev-parse --show-toplevel`).

These values must not be guessed beyond repository inspection evidence.

---

## 7. Runtime Entry Points

The Source of Truth must identify every known runtime entry point.

Examples may include:

```text
python -m ...
scripts/*.py
scripts/start_*.py
scripts/run_*.py
*.ps1
*.bat
application entry points
CLI entry points
service entry points
```

For each entry point document:

```yaml
entry_point:
  path: UNKNOWN
  symbol: UNKNOWN
  purpose: UNKNOWN
  status: UNKNOWN
  reaches_runtime: UNKNOWN
  evidence: UNKNOWN
```

The existence of an entry-point file does not prove that it is the production entry point.

### Verified Production Entry Points (default Windows path)

Evidence: docs_v2/03_runtime/STARTUP.md; E001–E004.

```yaml
entry_points:
  - path: start/START_BOT.bat
    symbol: batch launcher
    purpose: Primary operator start
    status: ACTIVE
    reaches_runtime: true
    evidence: E001

  - path: scripts/start_bot.py
    symbol: main()
    purpose: MT5 wait, spawn daemon
    status: ACTIVE
    reaches_runtime: true
    evidence: E002

  - path: scripts/start_live_daemon.ps1
    symbol: PowerShell script
    purpose: Set engine env defaults; spawn watchdog
    status: ACTIVE
    reaches_runtime: true
    evidence: E003

  - path: scripts/run_live_watchdog.py
    symbol: main()
    purpose: Supervise python -m tradingbot --loop --execute
    status: ACTIVE
    reaches_runtime: true
    evidence: E004

  - path: tradingbot/__main__.py
    symbol: main()
    purpose: CLI entry (--loop, --execute, --live, --backtest, etc.)
    status: ACTIVE
    reaches_runtime: true
    evidence: E005

  - path: tradingbot/application/bootstrap.py
    symbol: run_demo_cycle, run_live_cycle, run_strategies_cycle
    purpose: Single-cycle alternate entries (not default production loop)
    status: AVAILABLE
    reaches_runtime: true
    evidence: E005
```

Alternate entry points (not default production): `start/GO_LIVE_FULL.bat`, `start/2_dry_run_once.bat`, direct `python -m tradingbot --loop` without watchdog.

---

## 8. Startup Chain

The actual startup chain must be traced from the executable entry point.

Expected investigation pattern:

```text
ENTRY POINT
    ↓
CONFIGURATION
    ↓
INITIALIZATION
    ↓
SERVICES
    ↓
TRADING KERNEL
    ↓
PIPELINE
    ↓
STRATEGY
    ↓
FILTERS
    ↓
RISK
    ↓
EXECUTION
    ↓
POSITION MANAGEMENT
    ↓
MONITORING / RECOVERY
    ↓
SHUTDOWN
```

This diagram is a model for investigation.

It must not be treated as proof that every stage exists.

Each stage must be verified against actual source code.

### Verified Production Startup Chain

Evidence: E001–E006; docs_v2/03_runtime/STARTUP.md.

```text
start/START_BOT.bat
  → start/_load_env.bat (.env if present)
  → scripts/start_bot.py
  → scripts/start_live_daemon.ps1
  → scripts/run_live_watchdog.py --execute
  → python -m tradingbot --loop --execute
  → LiveRunner._run()
  → startup_validator.validate_startup()
  → TradingKernel.run_forever()
```

Background services started by `LiveRunner` before loop: `KillSwitchService`, optional `BackgroundServices` (protector/recovery disabled on default router path), `LiveOpsService` (live execute only).

---

## 9. Configuration Truth

Configuration must be analyzed separately from documentation.

For every important configuration value determine:

```text
DEFINED
DEFAULT
ENVIRONMENT OVERRIDE
RUNTIME VALUE
ACTIVE
DISABLED
SHADOW
UNREACHABLE
UNKNOWN
```

Example:

```yaml
configuration:
  key: UNKNOWN
  defined_in: UNKNOWN
  default_value: UNKNOWN
  environment_override: UNKNOWN
  runtime_value: UNKNOWN
  status: UNKNOWN
  evidence: UNKNOWN
```

The following must never be treated as proof of live configuration:

```text
.env.example
README examples
sample config files
old configuration files
comments
documentation
```

### Verified Configuration Baseline (code defaults; operator `.env` UNKNOWN)

Evidence: E009, E003; docs_v2/03_runtime/CONFIGURATION.md.

| Key | Defined in | Code default | Daemon default (if unset) | Status |
|-----|------------|--------------|---------------------------|--------|
| `MULTI_ENGINE_ROUTER_ENABLED` | `live.py` | `true` | `true` | ACTIVE |
| `USE_ML_KERNEL` | `ml/integration/config.py` | env must be set for ML | `false` | DISABLED |
| `ENABLE_ML_SHADOW` | `ml/integration/config.py` | `false` | `true` | SHADOW |
| `ADAPTIVE_REGIME_ENABLED` | not in dict; `.get()` false | false | `false` | DISABLED |
| `VOL_REGIME_ENABLED` | `live.py` | `false` | `false` | DISABLED |
| `PA_PRODUCTION_LOCK` | `live.py` | `true` | not set by daemon | ACTIVE |
| `PRIMARY_SYMBOL` | `live.py` | `XAUUSD_i` | — | ACTIVE |
| `LOOP_INTERVAL` | `live.py` | 30 | — | ACTIVE |
| `TRADINGBOT_SIGNAL_FILTER` | `signal_filter_mode.py` | OFF | — | DISABLED |

Configuration precedence (verified): CLI-implied env in `LiveRunner` → process environment → `dotenv_loader` (keys not already in env) → `get_live_config()` → `load_legacy_config()` → module defaults.

Evidence: `tradingbot/config/dotenv_loader.py`, `tradingbot/adapters/legacy_loader.py`, `tradingbot/application/live_runner.py`.

Operator-specific runtime values in `.env` remain **UNKNOWN** (not inspected; may contain secrets).

---

## 10. Pipeline Truth

The actual pipeline must be discovered from source code.

Potential stages may include:

```text
DataStage
IndicatorStage
SignalStage
SignalFilterStage
RiskStage
ExecutionStage
```

However, these names must not be assumed to exist without source verification.

For every stage determine:

```yaml
stage:
  name: UNKNOWN
  implementation: UNKNOWN
  caller: UNKNOWN
  predecessor: UNKNOWN
  successor: UNKNOWN
  active: UNKNOWN
  reachable: UNKNOWN
  evidence: UNKNOWN
```

The documented pipeline must reflect the actual call graph.

### Verified Pipeline (TradingKernel)

Evidence: E006; docs_v2/02_architecture/PIPELINE.md.

Six stages registered in `TradingKernel.__init__` (L84–91):

| Order | Stage | Implementation | Active (default live) | Evidence |
|-------|-------|----------------|----------------------|----------|
| 1 | DataStage | `pipeline/data_stage.py` | ACTIVE | E006 |
| 2 | IndicatorStage | `pipeline/indicator_stage.py` | ACTIVE | E006 |
| 3 | SignalStage | `pipeline/signal_stage.py` | ACTIVE | E006 |
| 4 | SignalFilterStage | `pipeline/signal_filter_stage.py` | BYPASSED (WPSQF default OFF) | E006, E021 |
| 5 | RiskStage | `pipeline/risk_stage.py` | ACTIVE | E006, E010 |
| 6 | ExecutionStage | `pipeline/execution_stage.py` | ACTIVE | E006, E012 |

Caller: `TradingKernel.run_market_cycle()`. Global cycle also runs `_manage_positions()` outside the per-market pipeline.

---

## 11. Strategy Truth

Every strategy must have an explicit status.

Allowed statuses:

```text
ACTIVE
AVAILABLE
SHADOW
DISABLED
UNREACHABLE
DEPRECATED
PLANNED
UNKNOWN
```

For each strategy determine:

```yaml
strategy:
  name: UNKNOWN
  implementation: UNKNOWN
  registry: UNKNOWN
  selector: UNKNOWN
  caller: UNKNOWN
  active: UNKNOWN
  reachable: UNKNOWN
  shadow: UNKNOWN
  disabled: UNKNOWN
  evidence: UNKNOWN
```

The existence of a strategy class does not prove strategy execution.

The existence of a strategy registry does not prove that the registry is used by the live runtime.

The presence of configuration does not prove that the configured strategy is actually selected.

### Verified Strategy Status (default production path)

Evidence: E007, E008, E016, E017; docs_v2/04_strategy/STRATEGY.md.

| Strategy / Engine | Implementation | Registry | Status | Evidence |
|-------------------|----------------|----------|--------|----------|
| Price Action (SMC) | `engine/strategies/price_action_strategy.py` | `LegacyStrategyRegistry` (router inner) | ACTIVE (selected) | E016, E017 |
| MultiEngineRouter | `adapters/multi_engine_router.py` | `MultiEngineRouterRegistry` | ACTIVE | E008 |
| VOL_REGIME | `adapters/vol_regime_strategy_registry.py` | Router inner | SHADOW (probed, not selected under PA lock) | E008 |
| ADAPTIVE_REGIME | `adapters/adaptive_regime_strategy_registry.py` | Router inner | SHADOW | E008 |
| ML Kernel | `ml/integration/ml_kernel_registry.py` | `MLKernelRegistry` | DISABLED | E007 |
| ML Shadow | `adapters/shadow_strategy_registry.py` | Wrapper | SHADOW | E007 |
| Disabled names in ACTIVE_STRATEGIES | N/A | N/A | DISABLED (only `priceaction: True`) | E017 |
| UnconfiguredEngineRegistry | `factory.py` | Fallback | UNREACHABLE (with daemon env) | E007 |

---

## 12. Strategy Selection Path

The Source of Truth must identify the complete strategy selection path.

Example investigation:

```text
CONFIGURATION
    ↓
STRATEGY REGISTRY
    ↓
STRATEGY FACTORY
    ↓
STRATEGY SELECTOR
    ↓
SIGNAL ENGINE
    ↓
TRADING KERNEL
```

The actual implementation may differ.

The verified path must be based on source-code calls.

The following must be identified:

```text
Who selects the strategy?
Who calls the strategy?
Who receives the signal?
Who can reject the signal?
Who has final authority?
```

### Verified Selection Path (default production)

Evidence: E007, E008; docs_v2/04_strategy/SIGNAL_FLOW.md.

```text
load_legacy_config() / get_live_config()
  → build_strategy_registry()                    [factory.py]
  → MultiEngineRouterRegistry                    [when router on, ML off]
  → LegacyStrategyRegistry → StrategyManager
  → PriceActionStrategy.generate_signals()
  → SignalStage (closed bar only)
  → [SignalFilterStage pass-through if OFF]
  → RiskGate.evaluate()                          [final entry authority]
  → ExecutionStage → Mt5ExecutionAdapter
```

| Question | Answer | Evidence |
|----------|--------|----------|
| Who selects the strategy? | `MultiEngineRouterRegistry` (PA under production lock) | E008 |
| Who calls the strategy? | `SignalStage` → registry `generate_signal()` | E006 |
| Who receives the signal? | `RiskStage` / `RiskGate` | E010, E011 |
| Who can reject the signal? | PA internal gates, SignalFilter (if ON), RiskGate | E016, E021, E010 |
| Final entry authority? | `RiskGate` | E010 |

---

## 13. Signal Truth

The signal system must identify:

```text
signal source
signal type
signal format
signal validation
signal filters
signal confidence
signal combination
signal rejection
signal conversion
signal handoff to risk
```

For every signal-producing component determine:

```yaml
signal:
  producer: UNKNOWN
  input: UNKNOWN
  output: UNKNOWN
  confidence: UNKNOWN
  filters: UNKNOWN
  consumer: UNKNOWN
  active: UNKNOWN
  evidence: UNKNOWN
```

### Verified Signal Baseline (default PA path)

Evidence: E016, E006; docs_v2/04_strategy/SIGNAL_FLOW.md.

```yaml
signal:
  producer: PriceActionStrategy via MultiEngineRouterRegistry
  input: closed M5 OHLCV (enriched)
  output: TradingSignal (BUY/SELL/HOLD) via signal_helpers.build_trading_signal
  confidence: strategy metadata + SMA/ATR/volume heuristics
  filters: PA session/kill-zone/hardening; WPSQF default OFF
  consumer: RiskStage → RiskGate
  active: true
  evidence: E016, E006
```

---

## 14. Risk Authority

Risk controls must have a clearly identified final authority.

The audit must determine who controls:

```text
entry approval
position sizing
stop loss
take profit
exposure
maximum positions
daily loss
drawdown
spread protection
slippage protection
kill switch
emergency shutdown
position protection
position recovery
```

Potential components must not automatically be considered authoritative merely because their names suggest risk functionality.

The actual call path must determine authority.

### Verified Risk Authority (default production path)

Evidence: E010–E014; docs_v2/05_risk/RISK.md.

| Responsibility | Owner | Status | Evidence |
|----------------|-------|--------|----------|
| Entry approval (new trades) | `RiskGate` via `RiskStage` | ACTIVE | E010, E011 |
| Position sizing | `RiskGate._compute_lot()` | ACTIVE | E010 |
| Stop loss / take profit at entry | `signal_helpers.compute_sl_tp()` (preset) | ACTIVE | E016 |
| Max positions | `RiskGate._live_gates()` | ACTIVE | E010 |
| Daily loss / trade caps | `LiveRiskTracker` + RiskGate | ACTIVE | E010 |
| Spread / news / Friday gates | `domain/live_gates.py` via RiskGate | ACTIVE | E010 |
| Drawdown emergency | `KillSwitchService` (separate from entry gate) | ACTIVE | E014 |
| Open position trailing/EOD | `Mt5PositionManager` | ACTIVE | E013 |
| PositionProtector / Recovery | Background services | DISABLED (default router path) | E006 |
| Meta-labeler reject (PA) | `MetaLabeler` in RiskGate | PARTIAL (code wired; `.pkl` UNKNOWN) | E018 |

Kill switch can flatten positions without RiskGate approval — intentional emergency authority.

---

## 15. RiskGate

If a component named `RiskGate` exists, the audit must determine:

```yaml
risk_gate:
  implementation: tradingbot/adapters/risk_gate.py::RiskGate
  caller: tradingbot/pipeline/risk_stage.py::RiskStage.run
  called_before_execution: true
  final_authority: true (for new entries on kernel path)
  position_sizing: true (adjusted_lot on signal)
  stop_loss: set at signal construction; tier adaptation in RiskGate
  take_profit: set at signal construction
  exposure_control: max positions enforced; commented exposure limits DISABLED in live.py
  daily_loss_control: true (LiveRiskTracker + kill switch)
  drawdown_control: true (KillSwitchService)
  kill_switch_integration: separate service; not called from evaluate()
  evidence: E010, E011, E014
```

Multiple risk systems must be explicitly documented.

If multiple components can independently approve or reject a trade, their relationship must be documented.

---

## 16. Execution Truth

Execution documentation must identify the actual owner of order submission.

Determine:

```text
order creation
order validation
order sizing
SL/TP assignment
broker submission
broker response handling
retry logic
fill handling
partial fill handling
rejection handling
execution logging
```

For each execution component:

```yaml
execution:
  implementation: tradingbot/adapters/mt5_execution.py::Mt5ExecutionAdapter
  caller: tradingbot/pipeline/execution_stage.py::ExecutionStage.run
  broker: MetaTrader 5 (mt5.order_send)
  order_submission: guarded_order_send; magic 234000
  response_handling: retcode check; journal + telemetry
  retry_logic: up to 2 attempts with price refresh
  active: true (when --execute and not dry-run/paper)
  evidence: E012
```

---

## 17. Position Lifecycle

The complete position lifecycle must be verified.

Expected conceptual lifecycle:

```text
SIGNAL
    ↓
RISK APPROVAL
    ↓
ORDER SUBMISSION
    ↓
BROKER RESPONSE
    ↓
POSITION OPEN
    ↓
POSITION MANAGEMENT
    ↓
POSITION MODIFICATION
    ↓
POSITION CLOSE
    ↓
CLOSE VERIFICATION
    ↓
JOURNAL / METRICS
```

The actual lifecycle may differ.

The Source of Truth must document the real implementation.

Verified lifecycle: docs_v2/05_risk/POSITION_LIFECYCLE.md. Evidence: E010, E012, E013.

---

## 18. Position Management Authority

The audit must determine who controls an open position after execution.

Possible responsibilities include:

```text
stop loss management
take profit management
trailing stop
break-even
partial close
time-based exit
strategy exit
emergency exit
recovery
reconciliation
```

For each responsibility identify:

```yaml
position_management:
  responsibility: UNKNOWN
  owner: UNKNOWN
  implementation: UNKNOWN
  active: UNKNOWN
  evidence: UNKNOWN
```

### Verified Position Management (default production)

Evidence: E013; docs_v2/05_risk/POSITION_LIFECYCLE.md.

| Responsibility | Owner | Implementation | Active | Evidence |
|----------------|-------|----------------|--------|----------|
| Trailing stop | `Mt5PositionManager` | ATR-based SL modify | ACTIVE | E013 |
| Partial close | `Mt5PositionManager` | R-multiple targets | DISABLED for M5 preset | E013 |
| EOD / Friday close | `Mt5PositionManager` | Time-based close | ACTIVE (if enabled in config) | E013 |
| Emergency max loss pips | `Mt5PositionManager` | Close deal | ACTIVE | E013 |
| Emergency flatten (drawdown) | `KillSwitchService` | Close all positions | ACTIVE | E014 |
| Recovery / protector | `PositionRecoveryService`, `PositionProtector` | Background | DISABLED (default router path) | E006 |
| Startup reconciliation | `LiveRunner._startup_position_reconciliation` | One-shot manage_all | ACTIVE | E006 |

---

## 19. Kill Switch

The kill switch must be independently verified.

Determine:

```text
implementation
caller
trigger conditions
scope
what it blocks
whether it closes existing positions
whether it prevents new orders
whether it persists state
whether it survives restart
```

Status:

```yaml
kill_switch:
  implementation: tradingbot/services/kill_switch.py::KillSwitchService
  active: true (background thread on default live path)
  final_authority: true (emergency flatten; bypasses RiskGate for closes)
  persistence: emergency stop state persisted; restored in TradingKernel.__init__
  evidence: E014
```

---

## 20. Data Pipeline

The actual market-data pipeline must be identified.

Determine:

```text
data source
broker
symbol
timeframe
tick data
OHLCV
volume
spread
historical data
live data
cache
data validation
missing data handling
data synchronization
```

Potential stages:

```text
MT5
    ↓
Market Data Adapter
    ↓
Cache
    ↓
Data Stage
    ↓
Indicators
    ↓
Features
```

This is only an investigation model.

Actual implementation must be verified.

### Verified Data Pipeline (live path)

Evidence: E015; docs_v2/06_data/DATA_PIPELINE.md.

```text
MetaTrader 5
  → Mt5MarketDataAdapter.ensure_connected / update_all
  → normalize_ohlcv + normalize_mt5_bar_index
  → ParquetCache (data/*.parquet, gitignored)
  → DataStage → IndicatorStage
```

| Field | Verified value | Evidence |
|-------|----------------|----------|
| Data source | MT5 `copy_rates_from_pos` | E015 |
| Broker symbol | `XAUUSD_i` (PRIMARY_SYMBOL) | E009 |
| Signal timeframe | M5 only on default kernel loop | E009 |
| HTF context | H4 fetched for bias map only | E006 |
| Tick data | Used for spread/execution/health, not OHLCV signal series | E015 |
| Cache | Parquet under `data/` | E015 |

---

## 21. Timeframes

Every timeframe used by the actual runtime must be identified.

For example:

```text
M1
M5
M15
H1
H4
```

Do not assume a timeframe is active because:

```text
it exists in configuration
it exists in code
it exists in documentation
it exists in historical experiments
```

The runtime path must be verified.

### Verified Timeframe Usage (default production)

Evidence: E009, E006; docs_v2/06_data/DATA_PIPELINE.md.

| Timeframe | Role | Status |
|-----------|------|--------|
| M5 | Kernel market cycle; PA signal generation | ACTIVE |
| H4 | HTF bias map for M5 entries | ACTIVE (context only) |
| M15 | Presets exist; not in kernel loop when TIMEFRAMES forced to `["5m"]` | AVAILABLE, not cycled |
| M1 | Adapter mapping only | NOT USED on default live path |
| H1 | Adapter mapping only | NOT USED on default live path |

`get_live_config()` forces `TIMEFRAMES = ["5m"]` when router/adaptive/vol enabled.

---

## 22. Indicators

Every indicator must be classified.

Possible statuses:

```text
ACTIVE
AVAILABLE
SHADOW
DISABLED
UNREACHABLE
DEPRECATED
UNKNOWN
```

For each indicator determine:

```yaml
indicator:
  name: UNKNOWN
  implementation: UNKNOWN
  inputs: UNKNOWN
  timeframe: UNKNOWN
  consumer: UNKNOWN
  active: UNKNOWN
  evidence: UNKNOWN
```

---

## 23. Feature Engineering

The feature engineering system must identify:

```text
feature source
feature calculation
feature normalization
feature validation
feature storage
feature consumer
```

Every feature must be traceable to:

```text
source data
calculation
consumer
runtime usage
```

Unused features must not be described as active trading features.

---

## 24. Machine Learning Truth

The ML system must distinguish between:

```text
implemented
trained
saved
loaded
inference-enabled
reachable
active
shadow
disabled
planned
unknown
```

The presence of:

```text
model files
ML classes
training scripts
imports
configuration keys
```

does not prove that ML affects live trading decisions.

### Verified ML Baseline (default production)

Evidence: E007, E018, E019; docs_v2/07_ml/ML_STATUS.md.

| Component | Status | Live decision impact |
|-----------|--------|---------------------|
| ML Kernel (`USE_ML_KERNEL`) | DISABLED | None |
| ML Shadow (`ENABLE_ML_SHADOW`) | SHADOW | Log-only; no signal change |
| Meta-labeler | PARTIAL | Can reject PA entries when gating active and models loaded |
| XGBoost / LightGBM training code | IMPLEMENTED | OFFLINE / research |
| DQN / PPO / TFT / FinBERT | NOT PRESENT in repository | N/A |
| `tradingbot/ml/research/phase*` | IMPLEMENTED | UNREACHABLE on default live path |

Meta-labeler `.pkl` artifacts: **UNKNOWN** in workspace snapshot (`models/meta_labeler_info.json` exists; `models/*.pkl` not found).

---

## 25. ML Model Status

For every model determine:

```yaml
model:
  name: meta_labeler (per-TF)
  framework: pickle-loaded sklearn-style models (inferred from meta_labeler.py)
  implementation: tradingbot/services/meta_labeler.py
  training_pipeline: offline scripts (e.g. start/10_retrain_meta.bat)
  artifact: models/meta_labeler_info.json (present); models/*.pkl (UNKNOWN in repo snapshot)
  loading_path: models/ directory via MetaLabeler
  inference_path: RiskGate.evaluate() for PA signals
  runtime_consumer: RiskGate
  active: PARTIAL
  shadow: false
  evidence: E018, E019
```

Other ML models (XGBoost, LightGBM, phase15a engines): **IMPLEMENTED** for research/backtest; **DISABLED** on default live signal path unless `USE_ML_KERNEL=true`.

---

## 26. Meta-Labeling

If a meta-labeler exists, determine:

```text
implementation
training
artifact
loading
inference
decision impact
runtime reachability
```

The existence of a meta-labeler must not be interpreted as proof that it modifies live decisions.

Verified wiring: `MetaLabeler` called from `RiskGate` for PA signals. Gating active only when `should_gate()` true (model loaded + live win rate threshold). Enforcement on deployment machine: **PARTIAL / UNKNOWN** without runtime evidence.

Evidence: E018, E019. See KI-005 in docs_v2/01_truth/KNOWN_ISSUES.md.

---

## 27. Backtesting Truth

Backtesting must be documented separately from live trading.

Determine:

```text
backtest engine
data source
initial balance
commission
spread
slippage
position sizing
risk model
execution simulation
metrics
```

Backtest results must never be treated as proof of live profitability.

---

## 28. Live Trading Truth

Live trading status must be established independently.

Determine:

```text
live entry point
broker connection
account connection
symbol
timeframe
signal path
risk path
execution path
position management
monitoring
recovery
```

A successful backtest does not prove live functionality.

### Verified Live Trading Baseline (source-code path)

Evidence: E001–E014; docs_v2/01_truth/CURRENT_STATE.md.

| Field | Verified value |
|-------|----------------|
| Live entry point | `start/START_BOT.bat` → watchdog → `python -m tradingbot --loop --execute` |
| Broker connection | MT5 via `Mt5MarketDataAdapter` |
| Symbol | `XAUUSD_i` |
| Timeframe | M5 (kernel loop) |
| Signal path | Router → PA → SignalStage |
| Risk path | RiskGate via RiskStage |
| Execution path | Mt5ExecutionAdapter via ExecutionStage |
| Position management | Mt5PositionManager each global cycle |
| Monitoring | Heartbeat, trade journal, runtime_truth, rejection JSONL |
| Recovery | PositionRecoveryService **DISABLED** on default path |

Whether live trading is **currently profitable or production-ready**: **UNKNOWN** (requires runtime evidence).

---

## 29. Profitability Claims

The Source of Truth must never claim profitability merely from:

```text
backtest results
demo results
isolated trades
short-term performance
paper trading
historical simulation
```

Any profitability claim must identify:

```text
data period
market
broker
execution environment
cost assumptions
sample size
metrics
verification method
```

Otherwise the claim must be:

```text
UNVERIFIED
```

---

## 30. Testing Truth

Testing infrastructure must be inventoried.

Determine:

```text
test framework
test directories
unit tests
integration tests
end-to-end tests
fixtures
mocking
coverage
CI execution
```

The existence of a test does not automatically prove that the corresponding production behavior is active.

Tests provide evidence but must be interpreted in context.

### Verified Testing Baseline

Evidence: docs_v2/08_testing/TESTING.md.

| Field | Value | Status |
|-------|-------|--------|
| Test framework | pytest (inferred from `.pytest_cache/`, test file patterns) | PARTIAL |
| Test directory | `tests/` | VERIFIED |
| Test file count | 231 `test_*.py` files | VERIFIED (static count) |
| CI execution | Not found in repository | UNKNOWN |
| Pass/fail rate | Not executed in baseline audit | UNKNOWN |

---

## 31. Operational Truth

Operational components must be identified.

Examples:

```text
startup scripts
watchdogs
monitoring
logging
alerts
health checks
recovery services
dashboards
notifiers
scheduled jobs
```

For each component determine:

```yaml
operation:
  name: UNKNOWN
  implementation: UNKNOWN
  entry_point: UNKNOWN
  active: UNKNOWN
  scheduled: UNKNOWN
  reachable: UNKNOWN
  evidence: UNKNOWN
```

### Verified Operational Components (default production)

Evidence: E001–E004, E014; docs_v2/09_operations/RUNBOOK.md, OBSERVABILITY.md.

| Operation | Implementation | Entry point | Active (default) | Evidence |
|-----------|----------------|-------------|------------------|----------|
| Production start | `start_bot.py` + daemon | `start/START_BOT.bat` | ACTIVE | E001, E002 |
| Watchdog supervisor | `run_live_watchdog.py` | daemon spawn | ACTIVE | E004 |
| Kill switch | `KillSwitchService` | LiveRunner background | ACTIVE | E014 |
| Heartbeat | `live_loop_health.py` | LiveRunner 60s loop | ACTIVE | E006 |
| Trade journal | `TradeJournal` SQLite | kernel cycles | ACTIVE | E006 |
| Dashboard | `live_dashboard.hta` | `RUN_DASHBOARD.bat` | AVAILABLE (optional) | — |
| Position recovery | `PositionRecoveryService` | BackgroundServices | DISABLED | E006 |

---

## 32. Observability

The system must identify how runtime behavior is observed.

Determine:

```text
logs
metrics
health checks
heartbeat
trade journal
error reports
execution reports
monitoring dashboards
alerts
```

Observability evidence must not be confused with source-code evidence.

Verified observability artifacts (paths under gitignored `data/` at runtime): `data/trade_journal.db`, `data/runtime_truth.json`, `data/live_heartbeat.json`, `data/startup_report.json`, `logs/rejection_events.jsonl`, `logs/watchdog*.log`.

Evidence: docs_v2/09_operations/OBSERVABILITY.md. Runtime file contents: **UNKNOWN** in repository-only audit.

---

## 33. Runtime Truth vs Repository Truth

Repository truth answers:

```text
What does the code implement?
```

Runtime truth answers:

```text
What actually happened during execution?
```

These are related but different.

Example:

```text
Source code:
RiskGate exists and is called.

Runtime:
RiskGate actually approved 120 trades.
```

The first is repository evidence.

The second is runtime evidence.

Both may be useful.

---

## 34. Known Issues

Known issues must be documented separately from normal current-state facts.

Each issue should contain:

```yaml
issue:
  title: UNKNOWN
  subsystem: UNKNOWN
  description: UNKNOWN
  evidence: UNKNOWN
  severity: UNKNOWN
  reproducibility: UNKNOWN
  status: UNKNOWN
```

Known issues must never be silently removed when they become inconvenient.

They should be resolved, superseded, or moved to historical documentation with evidence.

Known issues catalogued in **docs_v2/01_truth/KNOWN_ISSUES.md** (KI-001 through KI-013). Summary of P0 conflicts:

- KI-001: Legacy docs claim ADAPTIVE_REGIME default; code uses router + PA lock
- KI-002: `start_bot.py` banner says VOL_REGIME LIVE; daemon sets VOL off
- KI-003: UnconfiguredEngineRegistry silent no-trade misconfiguration path

Full issue records with evidence remain in KNOWN_ISSUES.md.

---

## 35. Contradictions

When two sources disagree, the contradiction must be explicitly documented.

Example:

```text
DOCUMENTATION:
Strategy X is active.

SOURCE CODE:
Strategy X is never called.

STATUS:
CONFLICT
```

The system must then investigate the actual runtime path.

The conflict must not be hidden by rewriting one side without investigation.

### Documented Contradictions (verified)

| Source A | Source B | Status | Issue |
|----------|----------|--------|-------|
| `docs/robot_behavior_audit/` — ADAPTIVE default live | Code: router + PA lock | CONFLICT | KI-001 |
| `docs/CAPABILITIES.md` — M5+M15+H4 simultaneous | `get_live_config()` forces M5 only | CONFLICT | KI-008 |
| `start_bot.py` banner — VOL_REGIME LIVE | `start_live_daemon.ps1` — VOL off | CONFLICT | KI-002 |
| Legacy 5-stage pipeline docs | Code: 6 stages (SignalFilterStage) | CONFLICT | KI-001 area |
| `factory.py` docstring — VOL default | Selection logic: router first | CONFLICT | KI-009 |

Resolution authority: **executable source code** (Section 2).

---

## 36. Unknowns

The following must remain UNKNOWN until evidence exists:

```text
runtime behavior that cannot be observed
actual live configuration when inaccessible
broker-side behavior not represented in repository evidence
unverified strategy activation
unverified ML influence
unverified profitability
unverified production readiness
```

Unknown is an acceptable state.

Guessing is not.

---

## 37. Production Readiness

Production readiness must never be inferred from:

```text
project size
number of modules
number of tests
successful startup
successful backtest
successful demo
presence of monitoring
presence of risk controls
```

Production readiness requires explicit evidence.

Current status:

```yaml
production_readiness: UNKNOWN
```

Source-code baseline audit completed 2026-08-22 at commit `57bf778`. Live profitability, operator deployment state, and sustained live operation remain unverified.

---

## 38. Security Truth

Security-sensitive configuration must be identified.

Examples:

```text
broker credentials
API keys
tokens
passwords
database credentials
environment variables
secret files
private keys
```

The audit must identify whether credentials are:

```text
hardcoded
environment-based
external-secret based
encrypted
unknown
```

Secrets must never be copied into documentation.

Verified credential handling (no secret values documented):

| Credential type | Method | Evidence |
|-----------------|--------|----------|
| MT5 login/password/server | Environment variables | E009, `live.py` docstring |
| Email / Telegram | Environment variables | `live.py`, `live_ops_service.py` |
| `.env` file | Loaded via `dotenv_loader` (non-overriding) | `tradingbot/config/dotenv_loader.py` |

Hardcoded production credentials in source: **not verified** (not exhaustively audited). Operator `.env` contents: **UNKNOWN**.

---

## 39. Configuration Precedence

The actual configuration precedence must be verified.

Possible precedence:

```text
CLI
    ↓
ENVIRONMENT
    ↓
CONFIG FILE
    ↓
DEFAULT
```

This is only an example.

The actual precedence must be determined from source code.

**Verified precedence** (see Section 9): CLI-implied env in `LiveRunner` → process environment → `dotenv_loader` → `get_live_config()` → `load_legacy_config()` → module defaults.

Evidence: `tradingbot/application/live_runner.py`, `tradingbot/config/dotenv_loader.py`, `tradingbot/adapters/legacy_loader.py`.

---

## 40. Repository Drift

The Source of Truth must detect potential drift between:

```text
source code
configuration
tests
runtime evidence
generated documentation
verified documentation
historical documentation
```

Potential drift must be reported.

Documentation must not silently continue to claim VERIFIED status when evidence has changed.

---

## 41. Verification Metadata

Every verified current-state document should eventually contain:

```yaml
verification:
  status: PARTIAL
  verified_against_commit: 57bf778c23cefffe508bb49079688b177796f67e
  verified_at: 2026-08-22
  verifier: docs_v2 baseline audit (static source analysis)
  evidence_sources:
    - docs_v2/01_truth/CURRENT_STATE.md
    - docs_v2/01_truth/KNOWN_ISSUES.md
    - docs_v2/02_architecture/*
    - docs_v2/03_runtime/*
    - docs_v2/04_strategy/*
    - docs_v2/05_risk/*
    - docs_v2/06_data/*
    - docs_v2/07_ml/*
    - docs_v2/08_testing/*
    - docs_v2/09_operations/*
```

Subsystem documents marked VERIFIED in docs_v2 reflect **source-code** verification unless explicitly noted PARTIAL.

---

## 42. Baseline Audit Requirement

Before declaring this Source of Truth document VERIFIED, the repository must undergo a baseline audit.

The audit should inspect:

```text
1. repository tree
2. Git state
3. runtime entry points
4. startup chain
5. configuration
6. pipeline
7. strategy registry
8. strategy selection
9. signal flow
10. risk controls
11. execution
12. position management
13. data pipeline
14. ML
15. testing
16. operations
17. monitoring
18. generated artifacts
19. known issues
20. contradictions
```

The audit must produce evidence.

---

## 43. Current Baseline Status

The audit must produce evidence.

**Audit status:** Completed 2026-08-22 at commit `57bf778`. Method: static source-code and script tracing. Live MT5 session and test execution not performed.

---

## 43. Current Baseline Status

Baseline statuses after repository inspection (2026-08-22):

```yaml
repository_baseline: VERIFIED
runtime_baseline: PARTIAL          # source path verified; live session not observed
configuration_baseline: PARTIAL     # code defaults verified; operator .env UNKNOWN
pipeline_baseline: VERIFIED
strategy_baseline: VERIFIED         # default production selection path
risk_baseline: VERIFIED
execution_baseline: VERIFIED
position_management_baseline: VERIFIED
data_baseline: VERIFIED
ml_baseline: PARTIAL                # meta-labeler artifact/runtime enforcement UNKNOWN
testing_baseline: PARTIAL           # 231 test files counted; pass rate UNKNOWN
operations_baseline: VERIFIED
production_readiness: UNKNOWN
known_conflicts: VERIFIED           # see KNOWN_ISSUES.md
```

These values reflect repository source evidence. Runtime-dependent claims remain PARTIAL or UNKNOWN until runtime artifacts are inspected.

---

## 44. Evidence Ledger

Evidence ledger for baseline audit. All paths are relative to repository root.

```yaml
evidence:
  - id: E001
    type: SOURCE
    path: start/START_BOT.bat
    symbol: batch entry
    claim: Primary production operator entry point
    status: VERIFIED

  - id: E002
    type: SOURCE
    path: scripts/start_bot.py
    symbol: main
    claim: MT5 wait and daemon spawn orchestration
    status: VERIFIED

  - id: E003
    type: SOURCE
    path: scripts/start_live_daemon.ps1
    symbol: PowerShell script
    claim: Engine env defaults; watchdog process spawn
    status: VERIFIED

  - id: E004
    type: SOURCE
    path: scripts/run_live_watchdog.py
    symbol: _bot_cmd
    claim: Supervises python -m tradingbot --loop --execute
    status: VERIFIED

  - id: E005
    type: SOURCE
    path: tradingbot/__main__.py
    symbol: main
    claim: CLI entry for --loop --execute and alternate modes
    status: VERIFIED

  - id: E006
    type: SOURCE
    path: tradingbot/application/live_runner.py
    symbol: LiveRunner, _ReliabilityKernel
    claim: Live loop wiring, services, kernel subclass
    status: VERIFIED

  - id: E007
    type: SOURCE
    path: tradingbot/ml/integration/factory.py
    symbol: build_strategy_registry
    claim: Strategy/engine selection priority
    status: VERIFIED

  - id: E008
    type: SOURCE
    path: tradingbot/adapters/multi_engine_router.py
    symbol: MultiEngineRouterRegistry
    claim: PA/VOL/Adaptive probe; PA selected under production lock
    status: VERIFIED

  - id: E009
    type: SOURCE
    path: tradingbot/config/live.py
    symbol: get_live_config, PRIMARY_SYMBOL, PA_PRODUCTION_LOCK
    claim: Live symbol, timeframe forcing, engine flags
    status: VERIFIED

  - id: E010
    type: SOURCE
    path: tradingbot/adapters/risk_gate.py
    symbol: RiskGate.evaluate
    claim: Mandatory entry gate; sizing and live gates
    status: VERIFIED

  - id: E011
    type: SOURCE
    path: tradingbot/pipeline/risk_stage.py
    symbol: RiskStage.run
    claim: RiskGate called before execution stage
    status: VERIFIED

  - id: E012
    type: SOURCE
    path: tradingbot/adapters/mt5_execution.py
    symbol: Mt5ExecutionAdapter.execute
    claim: Broker order submission on live execute path
    status: VERIFIED

  - id: E013
    type: SOURCE
    path: tradingbot/adapters/mt5_position_manager.py
    symbol: Mt5PositionManager.manage_all
    claim: Open position management each global cycle
    status: VERIFIED

  - id: E014
    type: SOURCE
    path: tradingbot/services/kill_switch.py
    symbol: KillSwitchService
    claim: Drawdown/daily loss emergency flatten
    status: VERIFIED

  - id: E015
    type: SOURCE
    path: tradingbot/adapters/mt5_market_data.py
    symbol: Mt5MarketDataAdapter
    claim: MT5 OHLCV fetch and cache pipeline
    status: VERIFIED

  - id: E016
    type: SOURCE
    path: engine/strategies/price_action_strategy.py
    symbol: PriceActionStrategy
    claim: Active PA signal generation implementation
    status: VERIFIED

  - id: E017
    type: SOURCE
    path: tradingbot/config/strategies.py
    symbol: ACTIVE_STRATEGIES
    claim: Only priceaction enabled
    status: VERIFIED

  - id: E018
    type: SOURCE
    path: tradingbot/services/meta_labeler.py
    symbol: MetaLabeler
    claim: Meta scoring wired into RiskGate for PA signals
    status: VERIFIED

  - id: E019
    type: SOURCE
    path: models/meta_labeler_info.json
    symbol: metadata file
    claim: Meta-labeler training metadata present
    status: VERIFIED

  - id: E020
    type: SOURCE
    path: tradingbot/kernel/trading_kernel.py
    symbol: TradingKernel.__init__
    claim: Six-stage pipeline registration
    status: VERIFIED

  - id: E021
    type: SOURCE
    path: tradingbot/services/signal_filter_mode.py
    symbol: resolve_signal_filter_mode
    claim: WPSQF signal filter default OFF
    status: VERIFIED

  - id: E022
    type: SOURCE
    path: tradingbot/services/pa_production_lock.py
    symbol: is_pa_production_lock_enabled
    claim: PA-only selection under production lock
    status: VERIFIED

  - id: E023
    type: SOURCE
    path: tests/
    symbol: test_*.py (231 files)
    claim: Test inventory exists
    status: PARTIAL
```

Evidence IDs should be referenced by important claims whenever practical.

---

## 45. Source Dependency Model

Important documentation should eventually declare dependencies.

Example:

```yaml
document:
  path: docs_v2/01_truth/SOURCE_OF_TRUTH.md

dependencies:
  - docs_v2/01_truth/CURRENT_STATE.md
  - docs_v2/01_truth/KNOWN_ISSUES.md
  - docs_v2/02_architecture/ARCHITECTURE.md
  - docs_v2/02_architecture/MODULE_MAP.md
  - docs_v2/02_architecture/PIPELINE.md
  - docs_v2/03_runtime/STARTUP.md
  - docs_v2/03_runtime/LIVE_LOOP.md
  - docs_v2/03_runtime/CONFIGURATION.md
  - docs_v2/04_strategy/STRATEGY.md
  - docs_v2/04_strategy/SIGNAL_FLOW.md
  - docs_v2/05_risk/RISK.md
  - docs_v2/05_risk/POSITION_LIFECYCLE.md
  - docs_v2/06_data/DATA_PIPELINE.md
  - docs_v2/07_ml/ML_ARCHITECTURE.md
  - docs_v2/07_ml/ML_STATUS.md
  - docs_v2/08_testing/TESTING.md
  - docs_v2/09_operations/OBSERVABILITY.md
  - docs_v2/09_operations/RUNBOOK.md
  - docs_v2/10_history/CHANGELOG.md
```

Primary source dependencies (executable evidence): E001–E022 file paths in Section 44.

Dependencies must be re-verified when any listed source file changes.

---

## 46. Change Verification

When source code changes, the following questions must be answered:

```text
What changed?

Which subsystem changed?

Which runtime paths changed?

Which strategies changed?

Which risk controls changed?

Which configuration changed?

Which tests changed?

Which documentation is affected?

Does current-state documentation require re-verification?

Does generated documentation require regeneration?

Does CHANGELOG.md require an entry?
```

---

## 47. AI Agent Requirement

Any AI agent modifying this repository must:

```text
1. Read docs_v2/README.md
2. Read docs_v2/01_truth/SOURCE_OF_TRUTH.md
3. Inspect relevant source code
4. Verify the requested behavior
5. Identify documentation impact
6. Modify code only when requested/required
7. Update affected documentation
8. Run relevant tests
9. Run documentation validation when available
10. Report unknowns and conflicts
```

AI agents must not treat this document as proof of behavior.

This document itself must be verified against source code.

---

## 48. Documentation Does Not Define Architecture

This document does not authorize any architecture.

It does not require the repository to contain:

```text
TradingKernel
RiskGate
DataStage
SignalStage
ExecutionStage
LightGBM
XGBoost
TFT
PPO
FinBERT
```

unless these components are actually discovered in the repository.

Names appearing in this document are investigation targets or examples only.

---

## 49. Planned Architecture vs Current Architecture

The project may contain planned architecture that differs from current implementation.

These must be separated:

```text
CURRENT
```

vs:

```text
PLANNED
```

vs:

```text
HISTORICAL
```

A planned architecture must never be documented as current architecture.

---

## 50. Final Authority

The final authority for current repository behavior is:

```text
EXECUTABLE SOURCE CODE
+
VERIFIED RUNTIME EVIDENCE WHERE NECESSARY
```

Documentation exists to make that evidence understandable.

Documentation is not the system.

Documentation describes the system.

---

## 51. Final Rules

When evidence exists:

```text
DOCUMENT IT.
```

When evidence conflicts:

```text
REPORT THE CONFLICT.
```

When evidence is incomplete:

```text
USE UNKNOWN.
```

When code changes:

```text
CHECK DOCUMENTATION IMPACT.
```

When runtime behavior differs from documentation:

```text
TRUST VERIFIED RUNTIME / SOURCE EVIDENCE.
```

When a feature exists but is not proven reachable:

```text
DO NOT CALL IT ACTIVE.
```

When a feature is planned:

```text
CALL IT PLANNED.
```

When historical behavior is discovered:

```text
PRESERVE IT AS HISTORY.
```

When an AI agent is uncertain:

```text
DO NOT GUESS.
```

The objective of this document is to establish a trustworthy, traceable, evidence-based baseline for the actual TradingBot repository.

