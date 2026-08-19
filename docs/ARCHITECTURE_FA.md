# معماری بازطراحی TradingBot

## مشکل پروژه قدیم

در `TradingBot/` پردازش در چند فایل بزرگ پخش شده بود:

| فایل قدیم | حجم تقریبی | پردازش داخل آن |
|-----------|------------|----------------|
| `live/system_manager.py` | ~850 خط | orchestration، MT5، bots، emergency |
| `core/trading_bot.py` | ~1800 خط | signal، risk، order، trailing |
| `core/live_trading_bot.py` | — | چرخه live |
| `backtest/backtest.py` | ~1560 خط | شبیه‌سازی + تکرار منطق live |
| `core/risk_manager.py` | بزرگ | Kelly، VaR، regime |
| `core/strategies/*.py` | 17 فایل | منطق سیگنال |

نتیجه: **duplication**، config تکراری، تست سخت، و مسیر live/backtest متفاوت.

---

## راه‌حل: هسته مرکزی + Ports & Adapters

```
                    ┌─────────────────────┐
                    │   TradingKernel     │  ← تنها orchestrator
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   run_global_cycle      run_market_cycle      emergency/stop
         │                     │
         │              ┌──────┴────── Pipeline (ثابت)
         │              │ Data → Indicators → Signal → Risk → Execution
         ▼              └──────────────────────────────
   update_all markets
```

### اصل‌ها

1. **Single pipeline** — هر `symbol:timeframe` همان ۵ مرحله را طی می‌کند.
2. **Ports (قرارداد)** — هسته به interface وابسته است، نه MT5 یا pandas مستقیم.
3. **Adapters** — `adapters/mt5_*`, `adapters/legacy_strategy_*` در فاز ۲ وصل می‌شوند.
4. **تنظیمات واحد** — `KernelSettings.enabled_strategies` یک منبع حقیقت.
5. **CycleContext** — state پراکنده در متغیرهای instance به یک شیء انتقال داده تبدیل شد.

---

## مراحل Pipeline (معادل پردازش قدیم)

| مرحله | کلاس جدید | معادل قدیم |
|-------|-----------|------------|
| DATA | `DataStage` | `DataPipeline` + `Storage` + `DataProcessor` |
| INDICATORS | `IndicatorStage` | `features.calculate_indicators` |
| SIGNALS | `SignalStage` | `StrategyManager.generate_combined_signals` |
| RISK | `RiskStage` | `RiskManager.can_trade` |
| EXECUTION | `ExecutionStage` | `OrderManager` + `place_order` |

سرویس‌های **پس‌زمینه** (خارج pipeline اصلی ولی زیر نظر kernel):
- `PositionProtector` → `IOrderExecutor.manage_open_positions` + worker جدا
- `PositionRecoveryService` → bootstrap در startup
- `Optimizer` nightly → scheduled task در application layer
- `EventBus` → `IEventPublisher` adapter

---

## ساختار پوشه جدید

```
tradingbot/
├── kernel/trading_kernel.py    # هسته
├── pipeline/                   # مراحل پردازش
├── ports/                      # Protocol interfaces
├── domain/                     # models, enums
├── config/settings.py          # تنظیمات یکپارچه
├── adapters/                   # MT5, legacy strategies (فاز ۲)
└── application/bootstrap.py    # Composition Root
```

---

## نقشه مهاجرت (فازها)

### فاز ۱ ✅ (فعلی)
- تحلیل کامل پروژه قدیم
- مستندات قابلیت و نقشه پردازش
- اسکلت `TradingKernel` + pipeline + ports
- stub adapters برای تست

### فاز ۲ (پیشنهادی بعدی)
- `Mt5MarketDataAdapter` ← `core/data_pipeline.py`
- `LegacyStrategyAdapter` ← `core/strategy_manager.py`
- `Mt5ExecutionAdapter` ← `core/order_manager.py`
- `LegacyRiskAdapter` ← `core/risk_manager.py`
- `run_live.py` → `asyncio.run(kernel.run_forever())`

### فاز ۳
- `BacktestKernel` با `SimulatedExecutor` (یک pipeline، دو adapter)
- حذف تکرار `backtest.py` / `trading_bot.py`
- env-based secrets (حذف password از `live_config.py`)

### فاز ۴
- مهاجرت تدریجی ۱۷ استراتژی به plugin استاندارد
- یک dashboard، یک مسیر meta/signal

---

## مقایسه چرخه Live

**قدیم:**
```
run_system_manager → SystemManager.run
  → data_pipeline.update_data
  → calculate_indicators
  → for bot in bots: bot.run_live_cycle()
      → generate_signal → can_trade → place_order
```

**جدید:**
```
bootstrap.build_kernel() → TradingKernel.run_forever()
  → run_global_cycle()
      → market_data.update_all()
      → for market: run_market_cycle()  # pipeline 5-stage
      → executor.manage_open_positions()
```

---

## به‌روزرسانی‌های اخیر (ژوئن ۲۰۲۶)

- **ربات تخصصی طلا:** فقط `XAUUSD`، TFهای `M5/M15/H4`، پریست per-TF در `config/pa_symbol_tf_presets.py`.
- **لایه میانی سیگنال:** `domain/signal_helpers.py` — مسیر واحد از خروجی `StrategyManager` تا `TradingSignal`.
- **SignalStage:** `legacy_strategy_registry` → `build_trading_signal()` → Risk → Execution.
- **KillSwitch:** `services/kill_switch.py` — توقف اضطراری در drawdown/ضرر روزانه.
- راهنمای کامل برای برنامه‌نویس: [ONBOARDING_FA.md](ONBOARDING_FA.md)
