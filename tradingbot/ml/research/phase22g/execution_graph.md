# Phase 22G — Verified Execution Graph (from source code)

Generated from repository inspection. **Not** from prior phase reports.

## Live entry (verified)

```
scripts/dashboard_server.py / RUN_DASHBOARD.bat
  -> scripts/run_live_watchdog.py [--execute]
       -> python -m tradingbot --loop [--execute|--paper]
            -> tradingbot/__main__.py: run_live_loop()
                 -> tradingbot/application/live_runner.py: LiveRunner
```

**Evidence:** `RUN_DASHBOARD.bat` line 27 calls `run_live_watchdog.py --execute`.
`scripts/run_live_watchdog.py` line 62 builds `[python, -m, tradingbot, --loop, --execute]`.

## LiveRunner wiring (verified)

File: `tradingbot/application/live_runner.py`

| Component | Class | Lines |
|-----------|-------|-------|
| Market data | `Mt5MarketDataAdapter` | 65 |
| Execution | `Mt5ExecutionAdapter` | 66 |
| Risk | `create_risk_gate()` -> `RiskGate` | 67 |
| Position mgmt | `Mt5PositionManager` | 70 |
| Strategies | `build_strategy_registry()` | 76-79 |
| Kernel | `TradingKernel` | 72-83 |

## TradingKernel pipeline (verified)

File: `tradingbot/kernel/trading_kernel.py` lines 81-87

```
DataStage -> IndicatorStage -> SignalStage -> RiskStage -> ExecutionStage
```

### Per-cycle flow

```
run_forever()
  -> run_global_cycle()
       -> market_data.update_all(symbols, timeframes)
       -> _portfolio_snapshot() + _build_htf_bias_map()
       -> FOR each MarketKey(symbol, timeframe):
            run_market_cycle(market, portfolio)
              -> FOR stage in pipeline: stage.run(ctx, portfolio)
       -> _manage_positions()  # trailing/partial/emergency
```

## Signal generation fork (verified)

File: `tradingbot/ml/integration/factory.py` `build_strategy_registry()` line 139

```
USE_ML_KERNEL env (tradingbot/ml/integration/config.py is_ml_kernel_enabled)
  |-- false -> LegacyStrategyRegistry -> StrategyManager / PriceAction
  '-- true  -> MLKernelRegistry -> KernelAdapter -> ML stack
                 |-- success -> TradingSignal
                 '-- KernelFallbackError / exception -> LegacyStrategyRegistry (fallback)
```

## ML stack load order (verified)

`build_ml_kernel_stack()` in factory.py:

1. `PipelineCache.get_registry()` — loads phase9_9 + trend v40 + trend v41 (if files exist)
2. `apply_phase22c_range_thresholds()` if PHASE22C_ENABLED
3. `build_range_recovery_orchestrator()` — RangeAwareConfidenceEngine wrapper
4. `build_production_calibrated_adapter()` — Platt calibration
5. `build_mapped_production_risk()` — AdaptiveRiskEngine
6. `TradeQualityAdapter` — quality gate

## KernelAdapter signal path (verified)

File: `tradingbot/ml/integration/kernel_adapter.py`

```
produce_unified_signal(market, df)
  -> require_health(registry)
  -> PipelineCache.get_unified_frame(df)  # + v41 Top5 attach when active
  -> _engine_inners()  # phase9_9 + resolve_active_trend_engine_id()
  -> build_market_context(row, range_engine, trend_engine)
  -> quality.evaluate(ctx)  # calibration -> risk -> quality chain
  -> apply_profitability_filters (phase19c RSI/ADX) if action BUY/SELL
  -> coerce HOLD if risk/quality/filter fail
  -> UnifiedSignal

generate_signal()
  -> map_unified_to_trading_signal()
  -> return None if HOLD else TradingSignal
```

## Risk + execution (verified)

File: `tradingbot/adapters/risk_gate.py` — `RiskGate.evaluate()`
- Live gates: max positions, HTF alignment, spread, news, Friday, meta-labeler
- Lot sizing from risk percent

File: `tradingbot/adapters/mt5_execution.py` — `Mt5ExecutionAdapter.execute()`
- Respects TRADINGBOT_DRY_RUN / TRADINGBOT_PAPER env
- Calls `mt5.order_send`

## Configuration sources (verified)

| Source | Loader | Notes |
|--------|--------|-------|
| `.env` | `tradingbot/config/dotenv_loader.py` | Only if key not already in os.environ |
| Legacy dict | `tradingbot/adapters/legacy_loader.py` | Merged into KernelSettings.extra |
| Kernel settings | `tradingbot/config/legacy_settings.py` | SYMBOLS, TIMEFRAMES, LOOP_INTERVAL |
| ML env | USE_ML_KERNEL, TREND_MODEL_VERSION, PHASE22C_* | Read at runtime |

## Timeframes (verified)

`kernel_settings_from_legacy()` reads `TIMEFRAMES` from legacy config, normalized via `to_kernel()`.
Live loop runs all symbol×timeframe MarketKeys from settings.

## Fallbacks (verified)

1. ML health fail -> Legacy PriceAction (`MLKernelRegistry.generate_signal`)
2. v41 env + missing v41 bundle -> registry missing engine -> legacy fallback (NOT auto v40)
3. USE_ML_KERNEL=false -> pure legacy
4. MT5 disconnect -> cycle skipped (`run_global_cycle` returns {})

## What does NOT exist in live hot path

- `run_system_manager.py` / `live/system_manager.py` — **not present** in this repo (Phase 22A confirmed)
- Research modules under `tradingbot/ml/research/` — not imported by LiveRunner unless via factory hooks
