# Current State

> **SUPERSEDED AS CURRENT-RUNTIME ENTRY (2026-09-01).** Use `docs_v2/01_truth/CURRENT_RUNTIME_STATE.md`. This file is a 2026-08-22 snapshot (still useful; dates lag v41/PA audits).

## Status

- **Status:** PARTIAL (source-code VERIFIED; runtime-artifact evidence incorporated 2026-08-22)
- **Last Verified:** 2026-08-22
- **Verification Method:** Static source analysis + read-only runtime artifact inspection on operator machine
- **Source-code baseline commit:** `57bf778c23cefffe508bb49079688b177796f67e`
- **Documentation baseline commit:** `53819022951456dab228b22480052ef213019ec3`

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

**ML shadow default split:** `tradingbot/ml/integration/config.py` `is_ml_shadow_enabled()` defaults to **false** if `ENABLE_ML_SHADOW` is unset. The live daemon sets `ENABLE_ML_SHADOW=true` when unset — that daemon override is the **operational** default. Shadow is log-only and does **not** own live signals.

**Requested vs effective:** `USE_ML_KERNEL=true` is requested ML only. The factory still selects the router when the ML live gate is closed. Startup report `engine_selection` / `health_status` follow the **effective** registry (`MULTI_ENGINE_ROUTER` on the default path). That is not legacy mode and not ML-owned live.

**Active ML trend id (not live owner):** `resolve_active_trend_engine_id()` defaults to `trend_rf_v41`. `trend_rf_v40` remains the rollback / historical label. This does **not** change PA live signals while the ML gate is closed.

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
| Meta-labeler | PARTIAL | Code wired in `RiskGate`; artifacts **VERIFIED FROM FILES**; historical decisions recorded; continuous live enforcement **NOT PROVEN** |

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

## Runtime Evidence (files audit — 2026-08-22)

Evidence classes used below match `SOURCE_OF_TRUTH.md` Section 33.1.

### VERIFIED FROM FILES

| Artifact | What it proves | What it does **not** prove |
|----------|----------------|----------------------------|
| `data/trade_journal.db` (E024) | 5,427,614 cycle events (2026-06-10 → 2026-08-22); 5,428 executions (`paper` 5407, `live` 17, `dry_run` 4); all XAUUSD | Current live trading |
| `data/live_risk_state.json` (E031) | Persisted risk state; last day 2026-08-12; 1 M5 trade | Current live operation |
| `data/meta_decisions.jsonl` (E028) | 4 historical meta decisions (2026-08-07 → 2026-08-12): 3 approved, 1 rejected | Current-day meta rejection behavior |
| `models/meta_labeler_*.pkl` (E025–E027) | Artifacts exist; load test: M5/M15/H4 loadable; `is_ready=True` | Continuous live enforcement |
| `logs/runtime/live_heartbeat.json` (E029) | Healthcheck snapshot 2026-08-22: `router_alive=true`, `kernel_alive=false`, `mt5_connected=false`; current MT5 live trading **NOT PROVEN** | Does NOT prove an active live loop, MT5 connection, or current live trading. |
| `logs/rejection_events.jsonl` (E030) | 14 rejections on 2026-08-22; latest: entries frozen (MT5 equity unavailable) | Successful live execution |
| `data/live_account.json` (E032) | Snapshot keys: balance, equity, profit, updated_at (2026-08-14) | Demo vs real; broker/server identity |

### NOT PROVEN (current state)

- Current live MT5 trading is NOT PROVEN. E029 healthcheck on 2026-08-22 reported `router_alive=true`, `kernel_alive=false`, `mt5_connected=false`.
- Demo vs real account classification (`demo_vs_real = UNKNOWN`).
- Production readiness and profitability.

### Absent artifacts (code may write these; not found 2026-08-22)

- `data/runtime_truth.json`
- `data/live_heartbeat.json` (observed heartbeat: `logs/runtime/live_heartbeat.json`)
- `data/startup_report.json`

### Historical ML artifacts (do not infer current default path)

`data/ml/live/` contains large historical ML-kernel logs. Source-code baseline remains: `USE_ML_KERNEL=false`, PA router + production lock. **Historical ML logs ≠ current default production engine.**

## Unknowns

| Item | Why unknown |
|------|-------------|
| Operator `.env` overrides | Not inspected (may contain secrets) |
| Demo vs real account | `live_account.json` lacks safe discriminator fields |
| Test pass/fail rate | Tests **not executed** (231 files inventory only) |
| Production profitability | Not claimed without runtime evidence |
| Current-day meta rejection rate | Last meta decision 2026-08-12; only 4 records total |
| Continuous meta-labeler live enforcement | **NOT PROVEN** despite artifacts and historical decisions |

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
