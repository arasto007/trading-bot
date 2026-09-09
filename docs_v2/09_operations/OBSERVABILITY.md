# Observability

## Status

- **Status:** PARTIAL (source-code VERIFIED; runtime paths reconciled with files audit 2026-08-22)
- **Last Verified:** 2026-08-22
- **Verification Method:** Read logging modules + read-only runtime artifact inspection
- **Source-code baseline commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

How runtime behavior is **observed, logged, and persisted** — distinguishing code-defined paths from artifacts actually present on disk.

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
| **Tables (observed 2026-08-22)** | `executions`, `cycle_events`, `paper_trades` |
| **Written on** | Every pipeline cycle (state), executions (fills/dry-run) |
| **Git tracked** | NO (`data/` gitignored) |

### Runtime evidence (E024 — VERIFIED FROM FILES)

| Table | Row count (2026-08-22) |
|-------|------------------------|
| `cycle_events` | 5,427,614 |
| `executions` | 5,428 |
| `paper_trades` | 5,352 |

Execution modes in `executions`: `paper` 5407, `live` 17, `dry_run` 4 (all XAUUSD). Historical live executions: approximately 2026-06-10 → 2026-08-12.

**Proves:** historical bot activity and execution records. **Does not prove:** current live trading.

**Evidence:** `tradingbot/services/trade_journal.py`; E024

## Structured Rejection Log

| Field | Value |
|-------|-------|
| **Module** | `tradingbot/services/rejection_events.py` |
| **Default path** | `logs/rejection_events.jsonl` |
| **Override** | `TRADINGBOT_REJECTION_LOG` env |
| **Trigger** | RiskStage rejections, execution mapping errors |

### Runtime evidence (E030 — VERIFIED FROM FILES)

- **14 lines** on 2026-08-22
- Latest observed reason category: entries frozen when MT5 equity unavailable

**Proves:** current safety/freeze behavior was logged. **Does not prove:** successful live execution.

## Router and Meta Logs

| Log | Module | Content |
|-----|--------|---------|
| Router decisions | `router_decision_log.py` | PA/VOL/Adaptive labels, selected engine |
| Meta decisions | `meta_decision_log.py` | Scores, thresholds, reject/approve |
| Meta observer events | same module | Observer mode counterfactuals |

### Runtime evidence — meta decisions file

| Path | Records | Date range |
|------|---------|------------|
| `data/meta_decisions.jsonl` (E028) | 4 | 2026-08-07 → 2026-08-12 |

3 approved, 1 rejected. **Historical only** — not proof of current-day meta behavior.

## Engine Telemetry

**Module:** `tradingbot/services/engine_telemetry.py`

Records PA/VOL/ML shadow signals, rejections, trade opens — consumed for diagnostics.

## Runtime / Heartbeat Files

### Code-defined paths vs observed presence (2026-08-22)

| Path | Producer | Present? | Notes |
|------|----------|----------|-------|
| `data/trade_journal.db` | `TradeJournal` | **Yes** | E024 |
| `data/runtime_truth.json` | `runtime_truth.write_runtime_truth()` | **No** | Absent at audit time |
| `data/live_heartbeat.json` | `live_loop_health.publish_runner_heartbeat()` | **No** | Absent at audit time |
| `data/startup_report.json` | `startup_validator.write_startup_report()` | **No** | Absent at audit time |
| `logs/runtime/live_heartbeat.json` | healthcheck / `write_healthcheck_heartbeat()` | **Yes** | E029 |
| `data/live_risk_state.json` | `LiveRiskTracker` persistence | **Yes** | E031 — last day 2026-08-12 |
| `data/live_account.json` | account snapshot writer | **Yes** | E032 — no credentials in file |

Do **not** document absent `data/` heartbeat/runtime_truth/startup paths as currently existing.

### Observed healthcheck snapshot (E029 — 2026-08-22)

| Field | Value |
|-------|-------|
| `router_alive` | true |
| `kernel_alive` | false |
| `mt5_connected` | false |
| `symbol` | XAUUSD_i |
| `active_live_timeframes` | M5 |

This is a **healthcheck snapshot**, not proof of active live trading or a running production loop with MT5 connected.

**Evidence:** `tradingbot/services/runtime_truth.py`, `live_loop_health.py`, `startup_validator.py`; E029

## Heartbeat and Stall Detection

| Component | Interval | Consumer |
|-----------|----------|----------|
| `LiveRunner._heartbeat_loop` | 60s | Writes heartbeat (live loop) |
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
| `scripts/dashboard_server.py` | Windows Local Web Dashboard |
| `RUN_DASHBOARD.bat` | Launcher after successful START_BOT |
| `scripts/dashboard_server.py` | Optional server — separate entry |

Dashboard reads snapshot/cache files — exact wiring: **PARTIALLY VERIFIED**.

## MT5 Health

**Module:** `tradingbot/adapters/mt5_health.py`

- `check_mt5_health()` — connection, tick age
- `check_autotrading_ready()` — before live orders

## ML Monitoring Artifacts (historical)

`data/ml/live/` contains large ML-kernel monitoring logs (`decisions.jsonl`, `kernel_decisions.jsonl`, etc.). **VERIFIED FROM FILES** as historical artifacts. **Not** evidence that the current default production path is ML-kernel driven.

## Metrics / Phase Logs

`logs/phase*/` — research and certification outputs. **Historical** — not continuous live metrics unless scripts run.

## Active on Default Live (source code — writers defined)

Trade journal, cycle logs, rejection JSONL, router/meta logs, heartbeat writers, watchdog log, notifier info alerts.

**Observed 2026-08-22:** journal present (E024); rejection log present (E030); heartbeat at `logs/runtime/live_heartbeat.json` (E029). `data/runtime_truth.json`, `data/live_heartbeat.json`, and `data/startup_report.json` **absent** at audit despite code paths.

## Disabled / Optional

- Telegram (env-dependent)
- Email reporting (`EMAIL_*` in config — **UNKNOWN** if wired on live path)
- WPSQF filter metadata (filter off)

## Unknowns

- Whether live loop currently writes `data/live_heartbeat.json` when running (file absent at audit)
- Whether dashboard displays current heartbeat vs stale cache
- Demo vs real account (not in safe account snapshot fields)

## Change Impact

`tradingbot/services/*log*`, `trade_journal.py`, `live_loop_health.py`, `runtime_truth.py`

## Verification

```text
Grep log_, write_, .jsonl, heartbeat in tradingbot/services/
Inspect data/trade_journal.db, logs/runtime/live_heartbeat.json (read-only)
```
