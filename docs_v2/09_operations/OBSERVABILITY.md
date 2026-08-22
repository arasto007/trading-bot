# Observability

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Read logging, journal, telemetry, heartbeat modules
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

How runtime behavior is **observed, logged, and persisted** on the default live path.

## Logging

| Sink | Configuration | Evidence |
|------|---------------|----------|
| Console | `logging.basicConfig` in `run_live_loop` | `live_runner.py` |
| File (legacy config) | `LOG_TO_FILE` in live config | `live.py` |
| Watchdog | `logs/watchdog.log` | `run_live_watchdog.py` |
| Daemon stdout/stderr | `logs/watchdog_stdout_*.log`, `watchdog_stderr_*.log` | `start_live_daemon.ps1` |
| Component loggers | `get_logger()` per adapter/service | `infra/logging.py` |

## Trade Journal (SQLite)

| Field | Value |
|-------|-------|
| **Class** | `TradeJournal` |
| **Path** | `{BASE_DIR}/data/trade_journal.db` |
| **Tables** | `executions`, paper trades, cycle logs |
| **Written on** | Every pipeline cycle (state), executions (fills/dry-run) |
| **Git tracked** | NO (`data/` gitignored) |

**Evidence:** `tradingbot/services/trade_journal.py`

## Structured Rejection Log

| Field | Value |
|-------|-------|
| **Module** | `tradingbot/services/rejection_events.py` |
| **Default path** | `logs/rejection_events.jsonl` |
| **Override** | `TRADINGBOT_REJECTION_LOG` env |
| **Trigger** | RiskStage rejections, execution mapping errors |

## Router and Meta Logs

| Log | Module | Content |
|-----|--------|---------|
| Router decisions | `router_decision_log.py` | PA/VOL/Adaptive labels, selected engine |
| Meta decisions | `meta_decision_log.py` | Scores, thresholds, reject/approve |
| Meta observer events | same module | Observer mode counterfactuals |

## Engine Telemetry

**Module:** `tradingbot/services/engine_telemetry.py`

Records PA/VOL/ML shadow signals, rejections, trade opens — consumed for diagnostics.

## Runtime Truth Files

| File | Producer | Purpose |
|------|----------|---------|
| `data/runtime_truth.json` | `runtime_truth.write_runtime_truth()` | Engine flags, equity state snapshot |
| `data/live_heartbeat.json` | `live_loop_health.publish_runner_heartbeat()` | PID, bar age, router stats |
| `data/startup_report.json` | `startup_validator.write_startup_report()` | Startup diagnostic report |

All under `data/` — **gitignored**.

**Evidence:** `tradingbot/services/runtime_truth.py`, `live_loop_health.py`, `startup_validator.py`

## Heartbeat and Stall Detection

| Component | Interval | Consumer |
|-----------|----------|----------|
| `LiveRunner._heartbeat_loop` | 60s | Writes heartbeat |
| Watchdog stall evaluation | 30s poll | May restart child |
| NY session stall rules | conditional | `live_loop_health.evaluate_ny_stall` |

**Evidence:** `live_runner.py`; `run_live_watchdog.py`

## Notifier / Alerts

**Module:** `tradingbot/services/notifier.py`

- Startup/shutdown alerts
- Trade fill alerts from execution adapter
- Kill switch critical alerts
- Telegram optional via `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in LiveOps

## Dashboard

| Artifact | Purpose |
|----------|---------|
| `live_dashboard.hta` | Windows HTA panel |
| `RUN_DASHBOARD.bat` | Launcher after successful START_BOT |
| `scripts/dashboard_server.py` | Optional server — separate entry |

Dashboard reads snapshot/cache files — exact wiring: **PARTIALLY VERIFIED**.

## MT5 Health

**Module:** `tradingbot/adapters/mt5_health.py`

- `check_mt5_health()` — connection, tick age
- `check_autotrading_ready()` — before live orders

## Metrics / Phase Logs

`logs/phase*/` — research and certification outputs. **Historical** — not continuous live metrics unless scripts run.

## Active on Default Live

Trade journal, cycle logs, rejection JSONL, router/meta logs, heartbeat, runtime_truth, watchdog log, notifier info alerts.

## Disabled / Optional

- Telegram (env-dependent)
- Email reporting (`EMAIL_*` in config — **UNKNOWN** if wired on live path)
- WPSQF filter metadata (filter off)

## Unknowns

- Actual log volume on operator machine
- Whether dashboard displays current heartbeat vs stale cache

## Change Impact

`tradingbot/services/*log*`, `trade_journal.py`, `live_loop_health.py`, `runtime_truth.py`

## Verification

Grep `log_`, `write_`, `.jsonl`, `heartbeat` in `tradingbot/services/`.
