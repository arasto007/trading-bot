# فاز ۲ — گام ۳: ریسک (RiskManager legacy)

## هدف

اتصال `core/risk_manager.py` + `core/portfolio.py` به مرحله **Risk** در pipeline هسته جدید.

---

## آداپتر

| فایل | نقش |
|------|-----|
| `legacy_risk_gate.py` | `LegacyRiskGate` → `IRiskGate` |
| `create_legacy_risk_stack()` | ساخت `Portfolio` + `RiskManager` + gate |

---

## منطق (مثل LiveTradingBot)

1. `RiskManager.can_trade(symbol, signal, lot)` — اگر `False` → معامله متوقف
2. `get_recommended_position_size(...)` — محاسبه lot از ATR و equity
3. همگام‌سازی balance/equity از MT5 (اگر ترمینال وصل باشد)

---

## جریان در Pipeline

```
SignalStage → RiskStage (LegacyRiskGate) → ExecutionStage
```

`RiskStage` داده `ohlcv` غنی‌شده را در snapshot می‌گذارد تا lot درست محاسبه شود.

---

## به‌روزرسانی (ژوئن ۲۰۲۶) — گیت‌های live استاندارد

| ماژول | نقش |
|-------|-----|
| `domain/live_gates.py` | spread، خبر، max positions، جمعه، HTF alignment (pure) |
| `adapters/risk_gate.py` | `RiskGate` — sync MT5 positions + regime از OHLCV |
| `domain/risk_logic.py` | `infer_regime_from_ohlcv` + ضریب لات per regime |

پیش‌فرض live: `MAX_OPEN_POSITIONS_TOTAL=3`، `MAX_OPEN_POSITIONS_PER_SYMBOL=2`، `RISK_PER_TRADE=0.005`، HTF: M15→H4، H4→D1. فیلتر ۵ لایه در `domain/filter_policy.py`. Meta-labeler per-TF در `services/meta_labeler.py` (فعلاً M15 فعال).

## اعتبارسنجی

```powershell
cd "c:\Users\AMIR\Desktop\TradingBot new"
python scripts/check_live_setup.py
python -m tradingbot --strategies
```

---

## Live

```powershell
python -m tradingbot --live
```

همه مراحل: MT5 + priceaction + RiskGate (domain/risk_logic)

---

## گام بعدی (۴)

`run_live.py` / حلقه دائمی + PositionProtector (اختیاری)
