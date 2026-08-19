# Autonomous Mode — TradingBot LIVE Delivery

Hands-off operation: paper monitor, weekly snapshots, and L6 auto-review run without manual prompts.

## What runs automatically

| Component | Role |
|-----------|------|
| `logs/live_autonomous_orchestrator.ps1` | Master watchdog (5 min cycle) |
| `logs/live_l5_paper_monitor.ps1` | Shadow paper trading (15 min poll) |
| `tradingbot/ml/research/live_l5/refresh_live_candles.py` | Appends latest XAUUSD M5 bars before each shadow cycle |
| `tradingbot/ml/research/live_l6/auto_l6_on_paper_complete.ps1` | L6 review when paper ends or early gate (50 trades + PF≥1.1) |
| `tradingbot/ml/research/live_l5/paper_weekly_status.py` | Daily status snapshot |

**Rules enforced:** no live real-money orders; production deploy BLOCKED until L6 passes.

## Live candle feed (required for meaningful paper)

Shadow paper scans **new M5 bars** from the fullest candle parquet. Before each paper cycle, `refresh_live_candles.py` tries to append bars from **MT5** (or ParquetCache fallback).

- **Keep MetaTrader 5 open and logged in** while autonomous mode runs; otherwise candles stay static and `new_signals` stays 0 after bootstrap.
- Check `AUTONOMOUS_STATUS.json`: `live_feed_connected`, `candle_end`, `static_only_warning`.
- Refresh log: `logs/live_l5_candle_refresh.log`

## Hidden processes (normal)

Orchestrator and paper monitor start with `-WindowStyle Hidden` — **no terminal window appears**. This is intentional for unattended operation. Processes are alive if:

- `AUTONOMOUS_STATUS.json` → `paper_running: true`, recent `updated_utc`
- `logs/live_autonomous_orchestrator.log` and `logs/live_l5_paper_monitor_run.log` show recent cycle lines

## Check status anytime

Open **`AUTONOMOUS_STATUS.json`** at the repo root. Key fields:

- `paper_running`, `trades`, `pf`, `days_left`
- `orchestrator_pid`, `last_action`, `next_l6_check_utc`
- `candle_end`, `candle_source`, `live_feed_connected`, `static_only_warning`
- `production_blocked` (always true until L6)

## Start / resume

- **Double-click:** `logs/start_autonomous.bat`
- **After power outage:** Task Scheduler (if registered) restarts on logon; otherwise run `start_autonomous.bat` once.

## One-time Task Scheduler setup (optional but recommended)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\AMIR\Desktop\TradingBot new\logs\register_autonomous_tasks.ps1"
```

If that fails (policy/permissions), add `logs/start_autonomous.bat` to Windows Startup:

1. Press `Win+R` → `shell:startup`
2. Create shortcut to `C:\Users\AMIR\Desktop\TradingBot new\logs\start_autonomous.bat`

## Logs

- `logs/live_autonomous_orchestrator.log`
- `logs/live_autonomous_heartbeat.json`
- `logs/live_l5_paper_monitor_run.log`
- `logs/live_l5_candle_refresh.log`
- `logs/auto_l6_on_paper_complete.log`
