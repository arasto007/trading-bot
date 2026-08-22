# Startup

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Traced batch → Python → PowerShell → watchdog → CLI call chain
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

How the TradingBot **starts** on the default Windows production path.

## Primary Production Entry

```text
start/START_BOT.bat
```

**Steps:**

1. `chcp 65001`, set `TB_ROOT`
2. `call start/_load_env.bat` — loads project `.env` into cmd session if present
3. `python scripts/start_bot.py`

**Evidence:** `start/START_BOT.bat`

## `scripts/start_bot.py`

| Step | Action | Evidence |
|------|--------|----------|
| 1 | Load dotenv via `tradingbot.config.dotenv_loader` | L15–17 |
| 2 | Check if bot already running (`tradingbot.*--loop` process) | `_bot_pid()` |
| 3 | Wait up to 60s for MT5 terminal process | `_wait_mt5()` |
| 4 | Remove `data/manual_stop.flag` if present | L111–114 |
| 5 | Run `scripts/start_live_daemon.ps1` | L117–127 |
| 6 | Poll up to 120s for bot PID | L133–144 |
| 7 | On success, user may launch dashboard via `RUN_DASHBOARD.bat` (from bat) | `START_BOT.bat:10` |

**Note:** Banner text says `"VOL_REGIME LIVE"` — **contradicts** daemon env (see KNOWN_ISSUES KI-002).

## `scripts/start_live_daemon.ps1`

| Step | Action |
|------|--------|
| 1 | Remove `data/manual_stop.flag` |
| 2 | Kill existing `run_live_watchdog` or `tradingbot.*--loop` python processes |
| 3 | Run `scripts/release_mt5_ipc_lock.py` |
| 4 | Set env defaults if unset (see CONFIGURATION.md) |
| 5 | Spawn hidden: `python scripts/run_live_watchdog.py --execute` |
| 6 | Write log paths to `logs/watchdog_latest.logpaths.txt` |

**Evidence:** `scripts/start_live_daemon.ps1`

## `scripts/run_live_watchdog.py`

Spawns and supervises:

```text
python -m tradingbot --loop --execute
```

Features: restart on crash, stall detection via heartbeat, kill-switch exit code 2 cooldown, manual stop detection.

**Evidence:** `scripts/run_live_watchdog.py::_bot_cmd()`

## CLI Entry — `tradingbot/__main__.py`

| Flag | Handler |
|------|---------|
| (none) | `bootstrap.run_demo_cycle()` — stubs |
| `--strategies` | `run_strategies_cycle()` |
| `--live` | `run_live_cycle()` |
| `--loop` | `run_live_loop()` |
| `--backtest` | `BacktestEngine` |
| `--healthcheck` | heartbeat only, no MT5 |
| `--execute` | live orders (with `--loop` or `--live`) |
| `--paper` | paper mode |
| `--protector` | enable PositionProtector (non-default) |
| `--no-recovery` | disable recovery service |

**Evidence:** `tradingbot/__main__.py::main()`

## `LiveRunner` Initialization (after CLI)

**File:** `tradingbot/application/live_runner.py`

Constructs:

- `Mt5MarketDataAdapter`, `Mt5ExecutionAdapter`
- `create_risk_gate(legacy_config)`
- `build_strategy_registry(...)` 
- `_ReliabilityKernel` (TradingKernel subclass)
- `BackgroundServices` (protector/recovery per flags)
- `KillSwitchService`, `LiveOpsService`

Sets execution env: `TRADINGBOT_DRY_RUN`, `TRADINGBOT_PAPER`, or `TRADINGBOT_LIVE`.

## Startup Validation (before loop)

`startup_validator.validate_startup()` — may **refuse** to start on:

- Execution mode conflict
- Emergency stop active
- MT5 unavailable (live)
- Autotrading disabled (live)
- Real account without override (live)
- ML kernel enabled but artifacts missing (when ML on)

Writes `data/startup_report.json` (path under BASE_DIR; `data/` gitignored).

**Evidence:** `tradingbot/services/startup_validator.py`

## Post-Validation Steps

1. `write_runtime_truth()`
2. `market_data.ensure_connected()`
3. `lock_live_equity_at_startup()` (live MT5)
4. `_startup_position_reconciliation()`
5. `BackgroundServices.start_all()`
6. `KillSwitchService.start()`
7. `LiveOpsService.start()` (live execute only)
8. `kernel.run_forever()`

## Alternate Entry Points

| Entry | Purpose |
|-------|---------|
| `start/GO_LIVE_FULL.bat` | MT5 fix + smoke test + daemon |
| `start/2_dry_run_once.bat` | `python -m tradingbot --live` (dry-run) |
| `start/8_backtest_custom.bat` | Backtest |
| Direct `python -m tradingbot --loop` | Loop without watchdog (no auto-restart) |

## Active Components

Full chain through watchdog + LiveRunner + TradingKernel.

## Disabled by Default

PositionProtector, PositionRecovery (when router/adaptive/vol flags on).

## Unknowns

- Operator `.env` contents loaded before daemon
- Windows Task Scheduler jobs outside repo

## Change Impact

`start/*.bat`, `scripts/start_bot.py`, `scripts/start_live_daemon.ps1`, `scripts/run_live_watchdog.py`, `tradingbot/__main__.py`, `tradingbot/application/live_runner.py`, `tradingbot/services/startup_validator.py`
