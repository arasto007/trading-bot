# Current State

## Status

- **Status:** VERIFIED (source-code baseline)
- **Last Verified:** 2026-08-22
- **Verification Method:** Static analysis of executable source, startup scripts, and configuration loaders. No live MT5 session observed in this pass.
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Summary of what the TradingBot repository **implements and reaches** on the default Windows production startup path, as of the verified commit.

## Repository Identity

| Field | Value | Evidence |
|-------|-------|----------|
| Repository root | `TradingBot new/` | Workspace path |
| Git branch | `master` | `git branch --show-current` |
| Git revision | `57bf778c23cefffe508bb49079688b177796f67e` | `git rev-parse HEAD` |
| Commit count | Single initial snapshot | `git log` |

## What This System Is (Verified)

A **Python MetaTrader 5 trading bot** that orchestrates live trading through:

- `TradingKernel` — async loop and pipeline orchestration
- Six fixed pipeline stages (Data → Indicators → Signal → SignalFilter → Risk → Execution)
- `RiskGate` — mandatory gate for new entries on the kernel path
- `Mt5ExecutionAdapter` — broker order submission when live execute mode is active
- `Mt5PositionManager` — open-position management each global cycle

**Evidence:** `tradingbot/kernel/trading_kernel.py`, `tradingbot/application/live_runner.py`, `tradingbot/adapters/mt5_execution.py`

## Default Production Startup Path (Verified)

```text
start/START_BOT.bat
  → scripts/start_bot.py
  → scripts/start_live_daemon.ps1
  → scripts/run_live_watchdog.py --execute
  → python -m tradingbot --loop --execute
  → LiveRunner → TradingKernel.run_forever()
```

**Evidence:** `start/START_BOT.bat`, `scripts/start_bot.py`, `scripts/start_live_daemon.ps1`, `scripts/run_live_watchdog.py`, `tradingbot/__main__.py`

## Engine Selection on Default Daemon Path (Verified)

When `start_live_daemon.ps1` sets environment defaults (only if unset):

| Variable | Daemon default | Effect |
|----------|----------------|--------|
| `USE_ML_KERNEL` | `false` | ML kernel not used for signals |
| `ENABLE_ML_SHADOW` | `true` | Shadow observer wraps registry (log-only) |
| `MULTI_ENGINE_ROUTER_ENABLED` | `true` | `MultiEngineRouterRegistry` selected |
| `ADAPTIVE_REGIME_ENABLED` | `false` | Adaptive not selected |
| `VOL_REGIME_ENABLED` | `false` | VOL not selected |

With `PA_PRODUCTION_LOCK=true` (code default in `live.py`), the router **selects Price Action only**. VOL and Adaptive signals are computed for logging but **not selected**.

**Evidence:** `scripts/start_live_daemon.ps1:24–38`, `tradingbot/config/live.py:107,110,120`, `tradingbot/adapters/multi_engine_router.py`, `tradingbot/services/pa_production_lock.py`

## Active Symbol and Timeframe (Verified)

| Setting | Default live value | Evidence |
|---------|-------------------|----------|
| Symbol | `XAUUSD_i` | `tradingbot/config/live.py::PRIMARY_SYMBOL` |
| Kernel timeframes | `["5m"]` only when router/adaptive/vol enabled | `get_live_config()` in `live.py:215–222` |
| Loop interval | 30 seconds | `LIVE_TRADING_CONFIG['LOOP_INTERVAL']` |

M15/H4 presets exist but are **not iterated** on the default live kernel loop when only M5 is configured.

## Execution Mode (Verified)

| Mode | How activated | Broker orders |
|------|---------------|---------------|
| Live execute | `--execute` + no dry-run/paper env | Yes (via `Mt5ExecutionAdapter`) |
| Dry-run | `--live` without `--execute`, or `TRADINGBOT_DRY_RUN=1` | No |
| Paper | `--paper` or `TRADINGBOT_PAPER=1` | Simulated only |

**Evidence:** `tradingbot/services/execution_mode.py`, `tradingbot/__main__.py`, `tradingbot/adapters/mt5_execution.py`

## Active Components (Default Production Path)

| Component | Status | Evidence |
|-----------|--------|----------|
| `TradingKernel` | IMPLEMENTED AND WIRED | `live_runner.py` |
| `MultiEngineRouterRegistry` | IMPLEMENTED AND WIRED | `factory.py:197–205` |
| `LegacyStrategyRegistry` / PA | IMPLEMENTED AND WIRED | Router inner + `ACTIVE_STRATEGIES` |
| `RiskGate` | IMPLEMENTED AND WIRED | `risk_stage.py`, `create_risk_gate()` |
| `Mt5ExecutionAdapter` | IMPLEMENTED AND WIRED | `execution_stage.py` |
| `Mt5PositionManager` | IMPLEMENTED AND WIRED | `TradingKernel._manage_positions()` |
| `KillSwitchService` | IMPLEMENTED AND WIRED | `live_runner.py` background thread |
| `SignalFilterStage` (WPSQF) | IMPLEMENTED; default OFF | `signal_filter_mode.py` default OFF |
| ML shadow observer | SHADOW | `shadow_strategy_registry.py` |
| Meta-labeler | PARTIALLY VERIFIED | Code wired in `RiskGate`; artifact presence UNKNOWN |

## Disabled on Default Path

| Component | Status | Evidence |
|-----------|--------|----------|
| ML kernel (`USE_ML_KERNEL=true`) | DISABLED | Daemon + `is_ml_kernel_enabled()` |
| Adaptive as selected engine | DISABLED | Daemon env + router priority |
| VOL as selected engine | DISABLED | Daemon env + PA production lock |
| `PositionProtector` | DISABLED | `live_runner.py:341–347` |
| `PositionRecoveryService` | DISABLED | Same |
| WPSQF signal filter | DISABLED (default) | `TRADINGBOT_SIGNAL_FILTER` default OFF |

## Unreachable / Misconfiguration Paths

| Condition | Result | Evidence |
|-----------|--------|----------|
| `USE_ML_KERNEL` unset + router/adaptive/vol all off | `UnconfiguredEngineRegistry` returns no signal | `factory.py:235–236` |
| Real MT5 account without `TRADINGBOT_ALLOW_REAL=1` | Startup refused in live mode | `startup_validator.py`, `demo_account_guard.py` |

## Unknowns

| Item | Why unknown |
|------|-------------|
| Operator `.env` overrides | Not inspected (may contain secrets) |
| Meta-labeler `.pkl` files on disk | `models/*.pkl` not present in workspace snapshot |
| Live trade journal contents | `data/` gitignored |
| Test pass/fail rate | Tests not executed in this documentation pass |
| Production profitability | Not claimed without runtime evidence |

## Evidence Summary

Primary files inspected:

- `tradingbot/__main__.py`
- `tradingbot/application/live_runner.py`
- `tradingbot/kernel/trading_kernel.py`
- `tradingbot/ml/integration/factory.py`
- `tradingbot/adapters/multi_engine_router.py`
- `tradingbot/config/live.py`
- `scripts/start_live_daemon.ps1`
- `scripts/run_live_watchdog.py`
- `start/START_BOT.bat`

## Change Impact

Changes to any of the above files, daemon env defaults, or `build_strategy_registry()` priority can invalidate this document.

## Verification

```text
git rev-parse HEAD
git branch --show-current
# Trace: start/START_BOT.bat → tradingbot --loop --execute
# Read: tradingbot/ml/integration/factory.py::build_strategy_registry
```
