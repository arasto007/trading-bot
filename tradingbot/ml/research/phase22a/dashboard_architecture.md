# Phase 22A — Dashboard Architecture

## Frontend

| Component | Technology | File |
|-----------|------------|------|
| Primary UI | HTA (HTML + VBScript) | `live_dashboard.hta` |
| Launcher | Batch | `RUN_DASHBOARD.bat`, `start/7_open_dashboard.bat` |
| Auto-refresh | JS setTimeout 15s | `ScheduleRefresh` → `RefreshLivePanel` |

**No web server.** No REST API. No React/Vue.

## Backend (Script Layer)

Dashboard buttons invoke `.bat` files via `WScript.Shell.Run`:

| Button | VBScript | Bat | Python Script |
|--------|----------|-----|---------------|
| بررسی آمادگی | btnCheck | `start/1_check_setup.bat` | `check_live_setup.py` |
| META | btnMeta | `start/12_update_meta.bat` | `train_meta_labeler.py --update` |
| LIVE | btnLive | `start/3_live_loop_execute.bat` | `verify_ml_live_ready.py` → `run_live_watchdog.py` |
| بک‌تست | btnRunBacktest | writes JSON + `start/8_backtest_custom.bat` | `backtest_custom_range.py` |
| توقف | btnStop | `start/5_stop_bot.bat` | `stop_live_daemon.ps1` |
| وضعیت | btnStatus | `start/6_status.bat` | `status_live.py` |
| به‌روزرسانی | btnRefresh | inline | `start/0_hta_snapshot.bat` → `status_snapshot.py` |

## Snapshot Protocol (HTA ↔ Python)

`status_snapshot.py` emits pipe-delimited lines:

```
STATE|RUNNING|STOPPED
UTC|timestamp
ML|ON_READY|trend=1|range=1|meta=1
ALERT|severity|code|message
CYCLE|ts|market|state|detail
```

HTA `ReadSnapshot()` runs bat via hidden cmd, parses stdout.

## Cache

- No server-side cache
- HTA stores dismissed alert keys in `sessionStorage` equivalent (JS vars)
- ML PipelineCache is **kernel-side**, not dashboard

## Refresh Flow

```
RefreshLivePanel (every 15s)
  → ReadSnapshot(ProjectRoot)
  → Parse STATE, ML, ALERT, CYCLE lines
  → Update DOM badges + alert banner
  → ShowAlertPopup for new critical alerts
```

## Supervisor / Control Layer

| Component | Role |
|-----------|------|
| `run_live_watchdog.py` | Process supervisor — restart on crash |
| `manual_stop.flag` | User stop signal — blocks watchdog restart |
| `stop_live_daemon.ps1` | Kills python watchdog/loop processes |
| `KillSwitchService` | In-process drawdown supervisor |

**No SystemManager.** LiveRunner replaced `run_system_manager.py`.

## Environment Loading

All `start/*.bat` call `start/_load_env.bat` → reads `.env` into cmd session.

Python scripts also call `load_dotenv()` from `tradingbot/config/dotenv_loader.py`.

## Interaction Diagram

```
User (HTA)
  ↓ click
.bat launcher
  ↓
Python script OR watchdog
  ↓
tradingbot --loop --execute
  ↓
LiveRunner / TradingKernel
  ↓
data/trade_journal.db ← status_snapshot reads cycles
data/manual_stop.flag ← stop button
logs/watchdog.log
```

## Not Connected to Dashboard

- 70+ `scripts/run_phase*.py` research runners
- `start/14_rebuild_ml_models.bat` — manual ML rebuild, no HTA button
- `start/2_dry_run_once.bat` — no HTA button
- Phase 20A deployment runner threads
