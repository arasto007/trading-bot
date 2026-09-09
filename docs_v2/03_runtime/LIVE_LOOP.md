# Live Loop

> **Canonical runtime (2026-09-01):** `docs_v2/03_runtime/LIVE_RUNTIME_PATH.md`.

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Read `LiveRunner`, `TradingKernel`, background services
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Behavior of the **infinite live trading loop** after successful startup.

## Loop Owner

```text
TradingKernel.run_forever()
  while state == RUNNING:
      await run_global_cycle()
      await asyncio.sleep(cycle_interval_seconds)
```

Default interval: **30 seconds** from `LIVE_TRADING_CONFIG['LOOP_INTERVAL']` → `KernelSettings.cycle_interval_seconds`.

**Evidence:** `tradingbot/kernel/trading_kernel.py::run_forever`; `tradingbot/config/legacy_settings.py`

## Global Cycle (`run_global_cycle`)

| Order | Action | Can skip new entries? |
|-------|--------|----------------------|
| 1 | Abort if `EMERGENCY_STOP` | Yes — returns empty |
| 2 | `ensure_connected()` | Yes — skip cycle |
| 3 | `refresh_live_equity_from_mt5()` | May set freeze |
| 4 | MT5 health check | Yes — skip cycle |
| 5 | `update_all(symbols, timeframes)` | No |
| 6 | Build `htf_bias_map` | No |
| 7 | For each market: `run_market_cycle()` | **Skipped if `entries_frozen()`** |
| 8 | `_manage_positions()` | No — always runs |

**Evidence:** `tradingbot/kernel/trading_kernel.py::run_global_cycle`

## Per-Market Cycle

Runs six pipeline stages (see `PIPELINE.md`). Stops on first stage returning `False`.

Default markets: one `MarketKey` — `XAUUSD_i:M5` (after `get_live_config()` timeframe forcing).

## `_ReliabilityKernel` Extension

Before each global cycle, `_ReliabilityKernel`:

1. Fetches latest M5 bar from MT5
2. Updates `runtime_truth` market data stale state
3. Wraps `entries_frozen()` to also block on stale bars

**Evidence:** `tradingbot/application/live_runner.py:50–70`

## Background Threads / Services (Concurrent)

| Service | Interval / trigger | Live default |
|---------|-------------------|--------------|
| Heartbeat publisher | 60s | **ACTIVE** |
| KillSwitchService | 30s checks | **ACTIVE** |
| LiveOpsService | Daily report + drift hours | **ACTIVE** (live execute) |
| PositionProtector thread | 10s (if enabled) | **DISABLED** |
| PositionRecoveryService | periodic (if enabled) | **DISABLED** |
| Watchdog parent | supervises child process | **ACTIVE** (external) |

**Evidence:** `live_runner.py`, `kill_switch.py`, `live_ops_service.py`, `background_services.py`

## Execution Modes Inside Loop

| Mode | Env / CLI | Entry orders |
|------|-----------|--------------|
| Live | `--execute`, no dry-run/paper | Real MT5 |
| Dry-run | `TRADINGBOT_DRY_RUN=1` | Logged only |
| Paper | `TRADINGBOT_PAPER=1` | Simulated journal |

**Evidence:** `tradingbot/services/execution_mode.py`; `Mt5ExecutionAdapter.execute()`

## Shutdown Paths

| Trigger | Behavior |
|---------|----------|
| Ctrl+C | `set_manual_stop("ctrl_c")`, exit 0, watchdog stops if manual flag |
| Kill switch | `emergency_stop()`, flatten positions, exit code 2, watchdog cooldown |
| Kernel stop | `runner.stop()` in `finally` |
| MT5 disconnect | Cycles skipped; loop may continue |

**Evidence:** `live_runner.py`, `kill_switch.py`, `run_live_watchdog.py`

## State Persistence Across Restarts

- Emergency stop state restored in `TradingKernel.__init__`
- Live risk tracker: `data/live_risk_state.json` (gitignored)
- Manual stop: `data/manual_stop.flag`

## Active Components

TradingKernel loop, pipeline, position manager, kill switch, heartbeat.

## Disabled Components

Protector/recovery on default router config.

## Unknowns

- Actual cycle timing under MT5 latency
- Heartbeat file contents on operator machine

## Change Impact

`tradingbot/kernel/trading_kernel.py`, `tradingbot/application/live_runner.py`, `tradingbot/services/*`

## Verification

Trace `run_live_loop()` → `LiveRunner._run()` → `kernel.run_forever()`.
