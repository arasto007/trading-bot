# Startup and Shutdown

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of startup/shutdown procedure (supporting LIVE_PATH).  
**Operator-effective state:** UNKNOWN  

Supersedes `STARTUP.md` as the ChatGPT startup file. `STARTUP.md` kept with pointer.

## Startup

1. `START_BOT.bat` may `call start/_load_env.bat` (loads `.env` into cmd — **do not document secret values**).
2. `start_bot.py`: `load_dotenv()`; wait for MT5 **process**; remove `data/manual_stop.flag`; launch daemon.
3. Daemon: kill prior watchdog/loop; `release_mt5_ipc_lock.py`; set env if unset; hidden `run_live_watchdog.py --execute`.
4. Watchdog supervises `python -m tradingbot --loop --execute`.
5. `LiveRunner`: `validate_startup`, connect MT5, optional timezone calibrate, position reconciliation, start services + kill switch, `kernel.run_forever()`.

Evidence: `start/START_BOT.bat`, `scripts/start_bot.py`, `start_live_daemon.ps1`, `live_runner.py`.

This audit **does not start** those programs.

## Shutdown

`LiveRunner._shutdown`: `kernel.stop()`, kill_switch stop, live_ops stop, background stop, `market_data.shutdown()`. Ctrl+C → `set_manual_stop("ctrl_c")`. Operator: `scripts/stop_live_daemon.ps1` / `start/5_stop_bot.bat`.

Emergency: `KernelState.EMERGENCY_STOP` or emergency-stop file → exit **2**.

## Other CLI (not default daemon)

| Flag | Path |
|------|------|
| `--live` | one cycle `run_live_cycle` |
| `--paper` | paper fills |
| `--backtest` | `BacktestEngine` (default TF **M5**; Phase 25B) |
| `--strategies` | stubs, no MT5 |
| `--healthcheck` | heartbeat only |
