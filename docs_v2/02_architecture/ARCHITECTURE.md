# Architecture

> **Canonical architecture (2026-09-01):** `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md`. This file is supporting/superseded-keep.

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Source-code module and call-graph inspection
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

High-level architecture of the TradingBot as implemented in the repository — not planned or historical designs.

## Architectural Style

**Hexagonal / ports-and-adapters** around a central **`TradingKernel`**:

- **Ports:** `IMarketDataProvider`, `IIndicatorEngine`, `IStrategyRegistry`, `IRiskGate`, `IOrderExecutor`, `IPositionManager`
- **Adapters:** MT5, legacy strategy bridge, `RiskGate`, execution, position manager
- **Domain:** Pure logic (indicators, price action, risk formulas, position logic)

**Evidence:** `tradingbot/ports/`, `tradingbot/adapters/`, `tradingbot/domain/`, `tradingbot/kernel/trading_kernel.py`

## Layer Diagram (Verified)

```text
┌─────────────────────────────────────────────────────────┐
│  Entry: __main__.py / start/*.bat / scripts/watchdog    │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Application: live_runner.py, bootstrap.py             │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│  TradingKernel — orchestration, global cycle, emergency │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Pipeline (6 stages): Data → Indicators → Signal →       │
│  SignalFilter → Risk → Execution                        │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌──────────────┬───────────────┬────────────────────────┐
│ Adapters     │ Domain        │ Services (background)    │
│ MT5 data/exec│ indicators, PA│ kill switch, ops, journal│
│ strategies   │ risk_logic    │ telemetry, runtime_truth │
└──────────────┴───────────────┴────────────────────────┘
                           ▼
                    MetaTrader 5 terminal
```

## Central Authority (Verified)

| Concern | Owner on default live path |
|---------|---------------------------|
| Cycle orchestration | `TradingKernel` |
| New entry approval | `RiskGate` via `RiskStage` |
| Order submission (entries) | `Mt5ExecutionAdapter` via `ExecutionStage` |
| Open position management | `Mt5PositionManager` (each global cycle) |
| Emergency flatten | `KillSwitchService` (background) |
| Strategy selection | `build_strategy_registry()` → `MultiEngineRouterRegistry` |

## Parallel / Legacy Package: `engine/`

The `engine/` package hosts **`StrategyManager`** and **`PriceActionStrategy`**. Live path reaches PA through `LegacyStrategyRegistry`, not by calling `engine/` directly from the kernel.

**Evidence:** `tradingbot/adapters/legacy_strategy_registry.py`; `engine/strategy_manager.py`

Only **`priceaction`** is enabled in `ACTIVE_STRATEGIES`. The `engine/strategies/` directory contains only `price_action_strategy.py` plus base classes.

## ML Package: `tradingbot/ml/`

Large research and integration subtree. On default live path:

- **ML kernel:** DISABLED
- **ML shadow:** SHADOW (log-only wrapper)
- **Meta-labeler:** PARTIAL (RiskGate integration; artifact-dependent)

## Backtest Architecture

Separate risk and execution implementations reuse **`TradingKernel`** with simulated broker:

- `BacktestRiskGate` instead of `RiskGate`
- `SimulatedBroker` instead of `Mt5ExecutionAdapter`

**Evidence:** `tradingbot/backtest/engine.py`

## Active Components

- `TradingKernel`, six pipeline stages, MT5 adapters, `RiskGate`, PA strategy chain, watchdog, kill switch

## Disabled Components (default production)

- ML kernel signal path
- Adaptive/VOL as **selected** engines (probed only under router)
- PositionProtector / PositionRecoveryService
- WPSQF filter (default OFF)

## Unreachable Components (default production)

- `UnconfiguredEngineRegistry` — **not** the daemon default. The daemon sets `USE_ML_KERNEL=false` and the router default is on, so factory builds `MultiEngineRouterRegistry`. Unconfigured is only reached when router, adaptive, and VOL are all off **and** `USE_ML_KERNEL` is unset.
- Disabled strategy flags in `ACTIVE_STRATEGIES`
- Most `tradingbot/ml/research/phase*` modules

## Unknowns

- Whether operator enables alternate engines via `.env`
- Full import graph of root `ml/` vs `tradingbot/ml/`

## Evidence

| Claim | File | Symbol |
|-------|------|--------|
| Kernel pipeline list | `tradingbot/kernel/trading_kernel.py` | `TradingKernel.__init__` L84–91 |
| Live runner wiring | `tradingbot/application/live_runner.py` | `LiveRunner.__init__` |
| Strategy factory | `tradingbot/ml/integration/factory.py` | `build_strategy_registry` |
| Ports | `tradingbot/ports/` | `IRiskGate`, `IOrderExecutor`, etc. |

## Change Impact

`tradingbot/kernel/`, `tradingbot/application/`, `tradingbot/adapters/`, `tradingbot/ml/integration/factory.py`, `engine/strategies/`

## Verification

Read `TradingKernel.__init__` pipeline construction and `LiveRunner` dependency injection.
