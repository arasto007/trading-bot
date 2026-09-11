# فاز ۲ — گام ۲: استراتژی Price Action (Gold Specialist)

## وضعیت فعلی

| مورد | مقدار |
|------|--------|
| استراتژی فعال | فقط `priceaction` (`tradingbot/config/strategies.py`) |
| نماد | `XAUUSD` (بروکر: `XAUUSD_i` via `adapters/symbols.py`) |
| تایم‌فریم‌ها | پریست‌ها برای `M5`, `M15`, `H4`؛ **چرخه live پیش‌فرض فقط M5** (`get_live_config()`) |
| پریست per-TF | `config/pa_symbol_tf_presets.py` |

*(به‌روزرسانی شده — 2026-09-10: جدول زیر پریست‌ها را نشان می‌دهد، نه اجرای همزمان هر سه TF در live.)*

| TF | پریست | نکته |
|----|--------|------|
| M5 | `gold_ny_sweep` | NY 12–15 UTC، بدون meta |
| M15 | `atr_tight_gold` | سشن 8–20، ADX، HTF H4، partial TP، meta فعال |
| H4 | `gold_h4_swing` | 24h، HTF D1، بدون meta |

منطق SMC در `domain/price_action.py` + `engine/strategies/price_action_strategy.py`.

---

## مسیر سیگنال (لایه میانی)

```
StrategyManager.generate_combined_signals()   ← engine/
        ↓
LegacyStrategyRegistry.generate_signal()      ← فقط wrapper
        ↓
domain/signal_helpers.build_trading_signal()  ← لایه میانی یکپارچه
   ├─ resolve_market()      symbol/TF/broker/preset
   ├─ extract_signal_direction()
   ├─ compute_confidence()
   └─ compute_sl_tp()
        ↓
TradingSignal → RiskStage → ExecutionStage
```

`adapters/legacy_signal_helpers.py` فقط re-export از `domain/signal_helpers.py` است (سازگاری importهای قدیمی).

---

## جریان در Pipeline

```
Data → IndicatorEngine → SignalStage → Risk → Execution
                              ↑
                    LegacyStrategyRegistry
```

---

## اجرا

```powershell
cd "c:\Users\AMIR\Desktop\TradingBot new"

# تست بدون MT5
python -m tradingbot --strategies

# live (dry-run)
python -m tradingbot --live

# live واقعی
python -m tradingbot --loop --execute
```

---

## فیلتر سیگنال

- `MIN_CONFIDENCE` از **پریست همان TF** (`get_price_action_config`)
- سیگنال 0 یا confidence پایین → بدون معامله
- فیلتر سشن UTC در خود استراتژی

---

## توسعه

برای تغییر مسیر سیگنال (confidence، SL/TP، فیلترها) اول `tradingbot/domain/signal_helpers.py` را ببین.
برای تغییر منطق SMC: `domain/price_action.py` و `engine/strategies/price_action_strategy.py`.
