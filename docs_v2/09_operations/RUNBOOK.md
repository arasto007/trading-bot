# Runbook

## Status

- **Status:** VERIFIED (procedures from scripts); runtime outcomes **PARTIAL**
- **Last Verified:** 2026-08-22
- **Verification Method:** Read `start/*.bat`, daemon, watchdog, stop scripts
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Operator procedures for **starting, stopping, and supervising** the bot on Windows.

## Prerequisites

| Requirement | Evidence |
|-------------|----------|
| MetaTrader 5 installed and logged in | `start_bot.py::_wait_mt5()` |
| Python environment with dependencies | Implicit |
| `.env` with `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` | `live.py`, `legacy_loader.py` |
| Algo Trading enabled in MT5 | `GO_LIVE_FULL.bat`, startup validator |

## Start (Normal)

```text
start/START_BOT.bat
```

**Expected sequence:**

1. Load `.env` via `_load_env.bat`
2. Verify MT5 process running (wait up to 60s)
3. Clear `data/manual_stop.flag`
4. Run `scripts/start_live_daemon.ps1`
5. Watchdog spawns `python -m tradingbot --loop --execute`
6. On success, may open `RUN_DASHBOARD.bat`

**Evidence:** `start/START_BOT.bat`, `scripts/start_bot.py`

## Start (Full Go-Live Pipeline)

```text
start/GO_LIVE_FULL.bat
```

Additional steps: stop existing bot, release MT5 IPC lock, fix Experts ini, restart MT5 with algo trading, run `scripts/smoke_test_execution.py`, then daemon.

**Evidence:** `start/GO_LIVE_FULL.bat`

## Stop

```text
start/5_stop_bot.bat
```

Typically invokes stop daemon script (see `scripts/stop_live_daemon.ps1` referenced in daemon output).

**Manual stop flag:** Creating `data/manual_stop.flag` or Ctrl+C sets manual stop — watchdog exits without restart when child exits 0 with flag.

**Evidence:** `tradingbot/services/manual_stop.py`; `run_live_watchdog.py::should_stop_watchdog`

## Dry Run (Single Cycle, No Orders)

```text
start/2_dry_run_once.bat
→ python -m tradingbot --live
```

Sets dry-run env via bootstrap — **no broker orders**.

## Direct Loop (No Watchdog)

```text
python -m tradingbot --loop --execute
```

No automatic restart on crash.

## Health Check (No MT5 Loop)

```text
python -m tradingbot --healthcheck
```

Writes heartbeat file only.

## Environment Overrides (Require Restart)

Documented in `CONFIGURATION.md`. Critical:

- Engine flags (`MULTI_ENGINE_ROUTER_ENABLED`, etc.)
- `TRADINGBOT_ALLOW_REAL` for real accounts
- `TRADINGBOT_SIGNAL_FILTER` for WPSQF

## Watchdog Behavior

| Child exit | Watchdog action |
|------------|-----------------|
| 0 + manual_stop | Stop watchdog |
| 0 without manual_stop | Restart after delay |
| 2 (kill switch) | 4-hour cooldown then restart |
| Other | Exponential backoff restart |

**Evidence:** `scripts/run_live_watchdog.py`

## Stall Recovery

Watchdog may terminate and restart bot if heartbeat stale or NY stall rules fire.

**Evidence:** `run_live_watchdog.py::_supervise_child`

## Failure Points (Documented, Not Fixed)

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| START_BOT fails MT5 wait | Terminal not open | Open MT5, login |
| Daemon exits immediately | See `watchdog_stderr_*.log` | Log paths file |
| Bot running, no trades | Session window, meta gate, entries frozen | `runtime_truth.json`, rejection JSONL |
| Startup refused real account | Demo guard | Set `TRADINGBOT_ALLOW_REAL=1` or use demo |
| Silent no trades | Misconfigured engine env | Verify `USE_ML_KERNEL` and router flags |

See `KNOWN_ISSUES.md`.

## Logs to Inspect

| Path | Content |
|------|---------|
| `logs/watchdog.log` | Watchdog events |
| `logs/watchdog_latest.logpaths.txt` | Latest stdout/stderr paths |
| `logs/rejection_events.jsonl` | Risk/filter rejections |
| `logs/runtime/live_heartbeat.json` | Healthcheck / router snapshot (**observed** 2026-08-22) |
| `data/live_heartbeat.json` | Live-loop heartbeat (code path; **absent** at 2026-08-22 audit) |
| `data/startup_report.json` | Startup validation (**absent** at 2026-08-22 audit) |

## Weekend / Maintenance Scripts

| Script | Purpose |
|--------|---------|
| `start/WEEKEND_CHECKLIST.bat` | Maintenance checklist |
| `start/16_daily_report.bat` | Daily report |
| `scripts/release_mt5_ipc_lock.py` | IPC lock release |

## Unknowns

- Exact contents of `5_stop_bot.bat` (not fully read — references stop daemon)
- Scheduled Task automation outside repo

## Change Impact

`start/*.bat`, `scripts/start_bot.py`, `scripts/start_live_daemon.ps1`, `scripts/run_live_watchdog.py`

## Verification

Read batch files and trace to Python entry points.
