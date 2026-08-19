# نقشه پردازش — پروژه قدیم → هسته جدید

هر ردیف: **کجا پردازش بود** → **کجا در TradingBot new می‌رود**.

## لایه ۱ — Orchestration

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `run_system_manager.py` | launcher | `application/` + `python -m tradingbot` |
| `live/system_manager.py` | حلقه async، init bots، MT5، emergency | `TradingKernel.run_forever` + `run_global_cycle` |
| `core/live_trading_bot.py` | `run_live_cycle` | `TradingKernel.run_market_cycle` |

## لایه ۲ — داده

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `core/data_pipeline.py` | fetch, cache, update | `ports/IMarketDataProvider` → `adapters/mt5_market_data` |
| `core/data_utils.py` | clean, validate | داخل adapter market data |
| `core/storage.py` | parquet/sqlite | `ports/IMarketDataStore` |
| `utils/download_historical_data.py` | bulk download | CLI در `application/` |

## لایه ۳ — اندیکاتور

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `core/features.py` | `calculate_indicators` | `pipeline/IndicatorStage` + `ports/IIndicatorEngine` |

## لایه ۴ — سیگنال

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `core/strategy_manager.py` | load, merge signals | `ports/IStrategyRegistry` |
| `core/strategies/*.py` | `generate_signals` | plugins (بدون تغییر منطق داخلی در فاز ۲) |
| `meta/meta_controller.py` | select_best | policy داخل `IStrategyRegistry` |
| `meta/performance_tracker.py` | history | service جدا زیر kernel |

## لایه ۵ — تصمیم و اجرا

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `core/trading_bot.py` | `generate_signal`, confidence, SL/TP | `SignalStage` + helpers |
| `core/risk_manager.py` | `can_trade` | `pipeline/RiskStage` |
| `core/order_manager.py` | execute, slippage | `pipeline/ExecutionStage` |
| `core/trading_bot.py` | `place_order`, trailing | `IOrderExecutor` |
| `core/position_protector.py` | thread SL/trail | background worker + executor |
| `core/position_recovery_service.py` | restart recovery | `application` startup hook |

## لایه ۶ — بک‌تست

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `backtest/backtest.py` | simulation loop | **همان** `TradingKernel` + `SimulatedExecutor` adapter |
| `backtest/run_*.py` | runners | `application/backtest_cli.py` |

## لایه ۷ — پس‌زمینه

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `core/optimizer.py` | nightly optimize | scheduled task (خارج pipeline) |
| `core/event_bus.py` | events | `ports/IEventPublisher` |
| `core/monitoring.py` | health | kernel lifecycle hooks |
| `core/reporting.py` | email reports | post-cycle hook |
| `dashboard_server.py` | metrics API | reads kernel state / cache |

## لایه ۸ — Enterprise (اختیاری)

| فایل قدیم | پردازش | مقصد جدید |
|-----------|--------|-----------|
| `core/execution/smart_execution.py` | TWAP/VWAP | `IOrderExecutor` implementation |
| `core/hedging/dynamic_hedging.py` | hedge logic | strategy plugin یا pre-risk hook |
| `core/tca_analysis.py` | TCA | post-execution analytics |
| `core/market_microstructure.py` | microstructure | optional `IndicatorStage` input |

---

## Pipeline ثابت در کد جدید

```python
# tradingbot/kernel/trading_kernel.py
DataStage → IndicatorStage → SignalStage → RiskStage → ExecutionStage
```

هیچ مرحله‌ای نباید **از دور kernel** برای open/close position در live صدا زده شود — استثنا: `PositionProtector` به‌عنوان safety net موازی.
