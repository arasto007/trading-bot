# فهرست قابلیت‌ها — TradingBot (نسخه بازطراحی)

> بخش ۱ وضعیت **فعلی** پروژه است. بخش ۲ حافظه‌ی طراحی پروژه قدیم است.

---

## ۱. وضعیت فعلی (`TradingBot new/`)

### معاملات زنده

- اتصال MetaTrader 5 (`adapters/mt5_*`)
- **فقط XAUUSD** — تایم‌فریم‌های **M5 / M15 / H4** (همزمان در هر چرخه)
- پریست per-TF: `config/pa_symbol_tf_presets.py`
- هسته: `TradingKernel` + pipeline ۵ مرحله
- **سه حالت اجرا**: dry-run / paper / live (`services/execution_mode.py`)
- **Watchdog**: `scripts/run_live_watchdog.py` — ری‌استارت خودکار ۵ دقیقه
- مدیریت پوزیشن هسته‌محور: trailing / partial TP (فقط M15) / emergency
- `KillSwitchService` — drawdown + ضرر روزانه
- **گیت‌های live** (`domain/live_gates.py` + `adapters/risk_gate.py`):
  - max پوزیشن: **۳ کل / ۲ per symbol**
  - spread، خبر (NFP/CPI/FOMC)، جمعه
  - **HTF bias**: M15→H4، H4→D1
  - فیلتر بازار per-TF: regime + ADX + ATR (`domain/market_filters.py`)
  - **Meta-labeler** per-TF (فعلاً فقط M15 فعال)
- cooldown و max trades/day per-TF (`services/live_risk_tracker.py`)
- مانیتورینگ: `TradeJournal`، `Notifier`، `mt5_health`، `meta_decision_log`
- `PositionRecoveryService` — پیش‌فرض روشن
- `PositionProtector` — پیش‌فرض خاموش

### استراتژی

- فقط **Price Action (SMC)**: sweep، BOS+OB، structure
- پریست‌های طلا:
  - **M5** `gold_ny_sweep` — NY 12–15 UTC
  - **M15** `atr_tight_gold` — سشن 8–20 UTC
  - **H4** `gold_h4_swing` — 24h
- سیاست فیلتر ۵ لایه بدون تداخل: `domain/filter_policy.py`

### Meta-Labeler (ML)

- آموزش walk-forward با OOS gate: `scripts/train_meta_labeler.py`
- به‌روزرسانی افزایشی: `start/12_update_meta.bat`
- لاگ لایو: `data/meta_decisions.jsonl`
- گزارش: `scripts/show_meta_stats.py`

### بک‌تست

- همان هسته روی داده تاریخی (`tradingbot/backtest/`)
- parity با live: HTF، max positions، partial TP از preset per-TF
- اسکریپت‌ها:
  - `scripts/run_backtest.py` — بک‌تست عمومی + Monte Carlo
  - `scripts/backtest_custom_range.py` — بازهٔ تهران (پنل HTA)
- کش داده: `data/backtest/*.parquet`

### پنل و اجرا

- پنل: `live_dashboard.hta`
- پوشه `start/` — batهای آماده

### اجرا

```powershell
python scripts/run_live_watchdog.py --execute   # LIVE + watchdog
python -m tradingbot --loop --execute         # LIVE بدون watchdog
python -m tradingbot --loop --paper           # paper mode
python scripts/check_live_setup.py            # چک قبل از live
python scripts/show_meta_stats.py             # وضعیت meta
python scripts/run_backtest.py --symbol XAUUSD --tf M15 --days 30
```

راهنمای کامل: [ONBOARDING_FA.md](ONBOARDING_FA.md) · دستورات: [../دستورات_اجرایی.md](../دستورات_اجرایی.md)

---

## ۲. حافظه طراحی — پروژه قدیم (مرجع مهاجرت)

<details>
<summary>قابلیت‌های کشف‌شده در TradingBot/ قدیم</summary>

چند symbol، چند استراتژی (priceaction، hedging، ML، …)، DataPipeline، Dashboard قدیم.

در نسخه جدید فقط **XAUUSD + Price Action + M5/M15/H4** فعال است.

</details>
