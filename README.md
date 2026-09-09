# TradingBot (بازطراحی)

نسخه بازطراحی‌شده ربات ترید خودکار MT5 با **هسته مرکزی** (`TradingKernel`) که تمام پردازش‌ها را از یک مسیر واحد عبور می‌دهد.

> 👋 **شروع سریع:** [دستورات اجرایی](دستورات_اجرایی.md) · [راهنمای توسعه‌دهنده](docs/ONBOARDING_FA.md)

## وضعیت فعلی

| مرحله | وضعیت |
|-------|--------|
| هسته + pipeline + ports | ✅ |
| MT5 live (داده + سفارش) | ✅ |
| استراتژی Price Action طلا (M5/M15/H4) | ✅ |
| ریسک + فیلتر ۵ لایه + meta-labeler | ✅ |
| Watchdog + پنل HTA | ✅ |
| بک‌تست (parity با live) | ✅ |

## ساختار

```
TradingBot new/
├── scripts/dashboard_server.py # Web Dashboard
├── start/                   # batهای آماده
├── scripts/                 # watchdog، بک‌تست، meta، چک live
├── docs/                    # مستندات فارسی
├── engine/                  # استراتژی Price Action
├── models/                  # meta-labeler
├── data/                    # کش، لاگ meta، journal
└── tradingbot/
    ├── kernel/              # TradingKernel
    ├── pipeline/            # Data → Signal → Risk → Execute
    ├── adapters/            # MT5، risk_gate
    ├── backtest/            # موتور بک‌تست
    ├── domain/              # منطق خالص + فیلترها
    └── config/              # live + presets
```

نصب: `pip install -r requirements.txt`

## اجرای سریع

```powershell
cd "C:\Users\AMIR\Desktop\TradingBot new"

# پنل (پیشنهادی)
start\7_open_dashboard.bat

# یا مستقیم:
python scripts/check_live_setup.py              # چک MT5
python -m tradingbot --live                     # یک چرخه dry-run
python scripts/run_live_watchdog.py --execute   # LIVE + watchdog
powershell -File scripts\stop_live_daemon.ps1   # توقف
```

## بک‌تست

```powershell
python scripts/run_backtest.py --symbol XAUUSD --tf M15 --days 30 --risk 0.005
python scripts/backtest_custom_range.py --start "2026-06-01 08:00" --end "2026-06-07 20:00"
```

## مستندات

- [دستورات اجرایی](دستورات_اجرایی.md)
- [راهنمای توسعه‌دهنده](docs/ONBOARDING_FA.md)
- [قابلیت‌های فعلی](docs/CAPABILITIES.md)
- [معماری](docs/ARCHITECTURE_FA.md)
- [بک‌تست](docs/PHASE3_BACKTEST_FA.md)

## اصل طراحی

**همه پردازش از Kernel عبور می‌کند.** live و backtest همان pipeline را اجرا می‌کنند — فقط آداپتر داده و اجرا عوض می‌شود.
