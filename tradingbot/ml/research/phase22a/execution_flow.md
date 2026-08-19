# Phase 22A — Execution Flow

**Note:** `run_system_manager.py` is **absent**. Equivalent chain documented from dashboard LIVE to `mt5.order_send()`.

## Startup Chain (Dashboard LIVE)

```
live_dashboard.hta
  btnLive onclick → RunBatFile("start\3_live_loop_execute.bat")
    → start/_load_env.bat          # loads .env into cmd session
    → verify_ml_live_ready.py      # ML artifacts + LIVE_REGISTRY check
    → run_live_watchdog.py --execute
        → subprocess: python -m tradingbot --loop --execute
            → tradingbot/__main__.py::main()
                → run_live_loop(execute=True)
                    → LiveRunner.__init__()
                    → LiveRunner.run() → asyncio.run(_run())
```

## LiveRunner._run() Sequence

1. `Mt5MarketDataAdapter.ensure_connected()` — MT5 init/login via `mt5_utils.ensure_mt5_connected`
2. `BackgroundServices.start_all()`
   - `PositionRecoveryService.start()` → monitor thread
   - Optional `PositionProtector` thread (default **OFF** in LiveRunner)
3. `KillSwitchService.start()` → daemon thread
4. `TradingKernel.run_forever()` — async while loop

## TradingKernel.run_global_cycle() (every ~30s)

```
1. state != EMERGENCY_STOP check
2. market_data.ensure_connected()
3. check_mt5_health() — stale tick gate (default 120s)
4. market_data.update_all(symbols, timeframes)
5. portfolio_snapshot() from RiskGate
6. _build_htf_bias_map() — H4/M15 bias per entry TF
7. FOR each MarketKey (XAUUSD × M5, M15, H4):
     run_market_cycle(market, portfolio)
     executor.manage_open_positions(market)
8. position_manager.manage_all() — trailing/partial/emergency
```

## run_market_cycle() — Pipeline Stages

| # | Stage | Class | Key Function |
|---|-------|-------|--------------|
| 1 | DATA | `DataStage` | `market_data.get_ohlcv(market, bars=fetch_bars)` |
| 2 | INDICATORS | `IndicatorStage` | `TechnicalIndicatorEngine.enrich(df)` |
| 3 | SIGNALS | `SignalStage` | `strategies.generate_signal()` — dedupe by closed bar |
| 4 | RISK | `RiskStage` | `risk.evaluate(signal, portfolio_snapshot)` |
| 5 | EXECUTION | `ExecutionStage` | `executor.execute(signal, lot)` |

Pipeline stops on first stage returning `False`.

## Signal Path (USE_ML_KERNEL=true)

```
SignalStage
  → MLKernelRegistry.generate_signal()
      → KernelAdapter.generate_signal()
          → produce_unified_signal()
              → require_health() [health_gate]
              → PipelineCache.get_unified_frame() [features]
              → DecisionOrchestrator.decide() [regime routing]
              → CalibratedDecisionAdapter + AdaptiveRisk + TradeQuality
              → apply_profitability_filters() [Phase 19C RSI/ADX]
              → UnifiedSignal
          → map_unified_to_trading_signal() → TradingSignal
      (on KernelFallbackError → LegacyStrategyRegistry fallback)
```

## Risk Path

```
RiskStage
  → RiskGate.evaluate()
      → _live_gates (spread, news, friday, htf, max positions)
      → LiveRiskTracker.check_entry_allowed()
      → risk_logic.can_trade()
      → MetaLabeler.score() if should_gate(tf, regime)
      → lot_from_stop_distance() → adjusted_lot
```

## Execution Path (LIVE)

```
ExecutionStage
  → Mt5ExecutionAdapter.execute(signal, lot)
      → if TRADINGBOT_DRY_RUN: journal only, return
      → if TRADINGBOT_PAPER: simulated fill
      → ensure_mt5_connected()
      → order_logic.validate_order()
      → order_logic.check_order_risk()
      → build TRADE_ACTION_DEAL request
      → _order_send_with_retry(mt5, request)  ← order_send HERE
      → record_live_entry(), TradeJournal.log_execution()
```

## Secondary order_send Sites (not entry)

| File | Purpose |
|------|---------|
| `mt5_position_manager.py` | Modify SL/TP, partial close, emergency close |
| `kill_switch.py` | Emergency flatten on drawdown |

## Watchdog Loop

```
while True:
  subprocess.run([python, -m, tradingbot, --loop, --execute])
  on exit:
    manual_stop.flag → stop watchdog
    exit 2 (kill switch) → 4h cooldown
    else → restart after 300s
```

## Shutdown

```
Ctrl+C / manual_stop / kernel.stop()
  → LiveRunner._shutdown()
      → kernel.stop()
      → kill_switch.stop()
      → services.stop_all()
      → market_data.shutdown()
```

## Objects Created at Startup (LiveRunner)

| Object | Type |
|--------|------|
| `market_data` | Mt5MarketDataAdapter |
| `executor` | Mt5ExecutionAdapter |
| `risk_gate` | RiskGate |
| `position_manager` | Mt5PositionManager |
| `kernel` | TradingKernel |
| `services` | BackgroundServices |
| `kill_switch` | KillSwitchService |
| `strategies` | MLKernelRegistry (if USE_ML_KERNEL) |

## Threads After Startup

| Thread | Source |
|--------|--------|
| Main asyncio loop | TradingKernel.run_forever |
| KillSwitch | kill_switch._loop |
| PositionRecovery | recovery._monitor_loop |
| PositionProtector | optional, default off |
