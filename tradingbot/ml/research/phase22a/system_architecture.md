# Phase 22A — System Architecture

**Scope:** Production system at `TradingBot new` (READ-ONLY audit, 2026-07-04)

## Executive Summary

The production robot is a **hexagonal TradingKernel** with MT5 adapters, optional **ML signal stack** (`USE_ML_KERNEL=true`), **RiskGate + Meta-Labeler**, and **HTA dashboard** launchers. The legacy `run_system_manager.py` **does not exist**; live orchestration is `LiveRunner` + `run_live_watchdog.py`.

## Layered Architecture

```
Market Data (MT5)
       ↓
Feature / Indicator Pipeline
       ↓
Regime + Strategy Router (ML or Legacy PA)
       ↓
ML Models (Trend v41 + Range phase9_9) + Calibration + Quality
       ↓
RiskGate (+ Meta M15/M5/H4)
       ↓
Execution Layer (Mt5ExecutionAdapter → order_send)
```

## Production vs Non-Production Zones

| Zone | Path | Role |
|------|------|------|
| **Kernel (production)** | `tradingbot/kernel/` | Single orchestrator |
| **Pipeline (production)** | `tradingbot/pipeline/` | **6-stage** cycle (Data→Indicator→Signal→**SignalFilter**→Risk→Execution); SignalFilter default OFF |

> **Reconciliation note (2026-09-10):** This Phase 22A audit originally said "5-stage". Current
> `tradingbot/kernel/trading_kernel.py` registers six stages including `SignalFilterStage`.
> Default live TIMEFRAMES are forced to `["5m"]` by `get_live_config()` when the multi-engine
> router (default on) is enabled — not concurrent M5/M15/H4 every cycle.
| **Adapters (production)** | `tradingbot/adapters/` | MT5, risk, legacy bridge |
| **Application (production)** | `tradingbot/application/` | LiveRunner, bootstrap |
| **ML integration (production)** | `tradingbot/ml/integration/` | KernelAdapter, factory, cache |
| **ML engines (production)** | `tradingbot/ml/phase15a/`, `decision_engine/` | Registry, orchestrator |
| **Services (production)** | `tradingbot/services/` | Journal, meta, kill switch |
| **Legacy engine (fallback)** | `engine/` | StrategyManager, PriceAction |
| **Research (isolated)** | `tradingbot/ml/research/` | 409+ files — NOT live path |
| **Scripts (ops)** | `scripts/`, `start/` | Launch, verify, backtest |
| **Dashboard (UI)** | `scripts/dashboard_server.py`, `RUN_DASHBOARD.bat` | Local Web Dashboard |

## Core Objects (Live)

| Object | File | Responsibility |
|--------|------|----------------|
| `TradingKernel` | `tradingbot/kernel/trading_kernel.py` | Global + per-market cycles |
| `LiveRunner` | `tradingbot/application/live_runner.py` | Lifecycle, background services |
| `MLKernelRegistry` | `tradingbot/ml/integration/ml_kernel_registry.py` | ML signals + legacy fallback |
| `KernelAdapter` | `tradingbot/ml/integration/kernel_adapter.py` | ML stack → TradingSignal |
| `RiskGate` | `tradingbot/adapters/risk_gate.py` | Live gates + meta + sizing |
| `Mt5ExecutionAdapter` | `tradingbot/adapters/mt5_execution.py` | order_send |
| `Mt5MarketDataAdapter` | `tradingbot/adapters/mt5_market_data.py` | OHLCV fetch |
| `Mt5PositionManager` | `tradingbot/adapters/mt5_position_manager.py` | Trailing/partial/close |

## Entry Points

| Entry | Production? |
|-------|-------------|
| `python -m tradingbot --loop --execute` | **YES** (via watchdog) |
| `RUN_DASHBOARD.bat` | **YES** (dashboard LIVE) |
| `scripts/run_live_watchdog.py` | **YES** |
| `run_system_manager.py` | **NO** — removed/replaced |
| `scripts/run_phase*.py` (70+) | **NO** — research/validation only |
| `engine/*` direct | **NO** — only via LegacyStrategyRegistry fallback |

## Repository Map (Top-Level)

```
TradingBot new/
├── tradingbot/          # Production kernel + ML integration (~1073 .py)
├── engine/              # Legacy StrategyManager + priceaction
├── scripts/             # 102 operational + research runners
├── start/               # 14 dashboard .bat launchers
├── tests/               # 102 test files
├── data/                # Runtime: journal, ML artifacts, flags
├── logs/                # watchdog, execution logs
├── reports/             # Backtest JSON outputs
├── scripts/dashboard_server.py   # Primary UI
├── .env                 # MT5 + USE_ML_KERNEL + Phase 19D filters
└── docs/                # Onboarding, phase docs (FA)
```

## Design Invariants (from code)

1. **TradingKernel never imports ML factory directly** — wired via `build_strategy_registry()` in bootstrap/LiveRunner.
2. **KernelAdapter never calls order_send** — signal only (`kernel_adapter.py` docstring).
3. **Research phases forbidden from execution imports** — enforced by 50+ test files.
4. **Single order_send production path** — `Mt5ExecutionAdapter._place_market_order` (+ position manager modifications).

## Async Model

- Main loop: `asyncio` in `TradingKernel.run_forever()` and `LiveRunner._run()`
- Background: `threading.Thread` for KillSwitch, PositionRecovery, optional PositionProtector
- No multiprocessing in production live path
