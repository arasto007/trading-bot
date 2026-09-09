# Live Runtime Path

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of LIVE_PATH hops.  
**Operator-effective state:** UNKNOWN  
**Evidence:** executable call chain. Operator env = UNKNOWN.

For each hop: component · file · symbol · caller → callee · class · confidence.

| # | Component | File | Symbol | Caller | Callee | Class | Evidence |
|---|-----------|------|--------|--------|--------|-------|----------|
| 1 | BAT | `start/START_BOT.bat` | n/a | operator | `scripts/start_bot.py` | PRODUCTION | file |
| 2 | Start | `scripts/start_bot.py` | `load_dotenv`, `_wait_mt5` | BAT | `start_live_daemon.ps1` | PRODUCTION | file |
| 3 | Daemon | `scripts/start_live_daemon.ps1` | env setdefault | start_bot | `run_live_watchdog.py --execute` | PRODUCTION | file:24–41 |
| 4 | Watchdog | `scripts/run_live_watchdog.py` | `_bot_cmd` | daemon | `python -m tradingbot --loop --execute` | PRODUCTION | file |
| 5 | CLI | `tradingbot/__main__.py` | `main` | watchdog | `run_live_loop` | PRODUCTION | file |
| 6 | Runner | `live_runner.py` | `run_live_loop` / `LiveRunner` | `__main__` | kernel construct + `run_forever` | PRODUCTION | file |
| 7 | Bootstrap | `bootstrap.py` | `build_kernel_live` | LiveRunner equivalent wiring | adapters | PRODUCTION | file:63–78 |
| 8 | Factory | `factory.py` | `build_strategy_registry` | bootstrap | `MultiEngineRouterRegistry` | PRODUCTION | file:160–215 |
| 9 | Shadow wrap | `factory.py` | `_maybe_wrap_shadow` | factory | `ShadowStrategyRegistry` | SHADOW | if `is_ml_shadow_enabled` |
| 10 | Router | `multi_engine_router.py` | `generate_signal` | SignalStage | PA/VOL/Adaptive generate; select PA | PRODUCTION select / SHADOW probe | file:86–117 |
| 11 | PA lock | `pa_production_lock.py` | `is_pa_production_lock` | router `__init__` | bool | PRODUCTION | `lock and not adaptive and not vol` |
| 12 | Legacy | `legacy_strategy_registry.py` | `generate_signal` | router | StrategyManager | PRODUCTION | |
| 13 | PA | `engine/strategies/price_action_strategy.py` | `generate_signals` | manager | gold setup | PRODUCTION | |
| 14 | Gold router | `gold_strategies/router.py` | `evaluate_gold_setup` | PA | `evaluate_m5_london_sweep` | PRODUCTION | mode london_sweep |
| 15 | Sweep | `m5_london_sweep.py` | `evaluate_m5_london_sweep` | gold router | setup | PRODUCTION | |
| 16 | Hardening | `pa_hardening.py` | `apply_setup_hardening` | gold router | setup | PRODUCTION | |
| 17 | Closed bar | `pipeline/signal_stage.py` | `SignalStage.run` | kernel | `exclude_forming_bar` | PRODUCTION | file:24 |
| 18 | Risk | `risk_gate.py` | `RiskGate.evaluate` | RiskStage | decision | PRODUCTION | |
| 19 | Exec | `mt5_execution.py` | `Mt5ExecutionAdapter.execute` | ExecutionStage | MT5 / paper / dry | PRODUCTION | |
| 20 | Freeze | `live_runner.py` | `_ReliabilityKernel.run_global_cycle` | kernel | `entries_frozen` or stale | PRODUCTION | |
| 21 | Kill | `kill_switch.py` | `KillSwitchService` | LiveRunner | exit code 2 | PRODUCTION | |
| 22 | Shutdown | `live_runner.py` | `_shutdown` | finally | kernel.stop, MT5 shutdown | PRODUCTION | file:271 |

`PIPELINE_TIMEOUT_MS` is **not** on this chain (`kernel_adapter.py`, ML only).

Config resolution: dotenv (no overwrite) → daemon setdefault → `LIVE_TRADING_CONFIG` / `get_live_config()`. Operator values UNKNOWN.

Error handling: SignalStage returns False on missing bars / duplicate closed ts. RiskGate deny. Execution fail messages. Kill-switch `sys.exit(2)`. Manual stop flag.
