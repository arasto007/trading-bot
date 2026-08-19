# Phase 22A — Thread Analysis

## Production Live Threads

| Thread | Owner | Daemon | Frequency | Purpose |
|--------|-------|--------|-----------|---------|
| **Main** | Python process | No | — | asyncio event loop |
| **Asyncio loop** | TradingKernel.run_forever | No | ~30s cycle | Market cycles |
| **KillSwitch** | KillSwitchService | Yes | Config interval | Drawdown monitor, emergency close |
| **PositionRecovery** | PositionRecoveryService | Yes | position_check_interval (~10s) | Reconcile MT5 vs DB state |
| **PositionProtector** | BackgroundServices | Yes | Optional, **default OFF** | Legacy trailing (conflicts with kernel PM) |

## Watchdog Process

Separate `python scripts/run_live_watchdog.py` — **not a thread**, subprocess spawns `tradingbot --loop`.

## Thread Interactions

```
Main asyncio
  ├─ run_global_cycle (async)
  │    ├─ MT5 data fetch (sync in adapter)
  │    ├─ ML prediction (sync, PipelineCache lock)
  │    └─ order_send (sync, blocks event loop)
  ├─ KillSwitch thread → may call mt5.order_send (emergency)
  └─ Recovery thread → reads MT5 positions, updates SQLite

PositionProtector (if enabled) → may modify SL via order_send
Mt5PositionManager.manage_all() → order_send on main cycle
```

## Shared Resources

| Resource | Accessors | Protection |
|----------|-----------|------------|
| PipelineCache | ML adapter, health gate | `threading.Lock` |
| MetaLabeler singleton | RiskGate | Module-level `_instance` |
| LiveRiskTracker | RiskGate | Module singleton |
| MT5 API | All threads | **No explicit lock** — race risk |
| trade_journal.db | Kernel, scripts | SQLite default |
| position_state.db | Recovery service | Single writer thread |

## Possible Race Conditions

1. **MT5 concurrent access** — KillSwitch + main cycle + recovery thread without mutex
2. **PipelineCache** — mitigated by lock
3. **manual_stop.flag** — read by watchdog and stop script; file IO race low risk
4. **PositionProtector + Mt5PositionManager** — if both enabled, duplicate trailing (why protector default off)

## Async Tasks

- No `asyncio.create_task` background tasks in production kernel
- All pipeline stages are `async def run()` but mostly call sync MT5/ML code

## Blocking Calls on Event Loop

| Call | Impact |
|------|--------|
| ML stack (10k+ features in backtest) | High — minutes per TF |
| mt5.copy_rates | Medium |
| order_send + retry sleep(0.5) | Low-Medium |
| MetaLabeler joblib predict | Low |

## Non-Production Threads

- Phase 20A `deployment_runner` flush thread
- Phase 18B live_safety test workers
- Research scripts — not live
