# فاز ۳ — بک‌تست (Backtesting)

این فاز یک موتور بک‌تست کامل اضافه می‌کند که **همان `TradingKernel` و pipeline** را روی
داده‌ی تاریخی، کندل‌به‌کندل اجرا می‌کند. هیچ منطق استراتژی/ریسک/مدیریت‌پوزیشنی دوباره
نوشته نشده — فقط آداپترهای «منبع داده» و «اجرای سفارش» با نسخه‌ی شبیه‌سازی‌شده جایگزین شده‌اند.

این دقیقاً قدرت معماری Ports & Adapters است: با تعویض دو پورت، کل سیستم به حالت بک‌تست می‌رود.

```
            ┌────────────────── همان هسته و pipeline ──────────────────┐
            │ Data → Indicators → Signals → Risk → Execution → Manage   │
            └───────────────────────────────────────────────────────────┘
  live:     Mt5MarketDataAdapter   LegacyIndicators  Legacy   Legacy   Mt5Executor   Mt5PositionManager
  backtest: BacktestMarketData     Passthrough       Legacy   Backtest SimulatedBroker BacktestPositionManager
```

## اجزای جدید (`tradingbot/backtest/`)

| فایل | نقش | پورت |
|------|------|------|
| `config.py` | پیکربندی بک‌تست (نماد، تایم‌فریم، بالانس، ریسک، هزینه‌ها) | — |
| `data_source.py` | `BacktestMarketData` — دریافت/کش داده‌ی MT5 + cursor برای replay | `IMarketDataProvider` |
| `broker.py` | `SimulatedBroker` — اجرای سفارش مجازی، چک SL/TP درون‌کندلی، balance/equity | `IOrderExecutor` |
| `risk.py` | `BacktestRiskGate` — parity با live (`domain/live_gates`) | `IRiskGate` |
| `htf_provider.py` | `BacktestHtfBiasProvider` — bias از H4/D1 بدون look-ahead | — |
| `position_manager.py` | `BacktestPositionManager` — trailing/partial/emergency روی پوزیشن مجازی | `IPositionManager` |
| `indicators.py` | `PassthroughIndicatorEngine` (اندیکاتورها یک‌بار در data_source) | `IIndicatorEngine` |
| `metrics.py` | محاسبه‌ی متریک‌ها + گزارش متنی | — |
| `engine.py` | `BacktestEngine` — هماهنگ‌کننده‌ی حلقه‌ی کندل‌به‌کندل | — |
| `models.py` | `VirtualPosition`, `ClosedTrade`, `BacktestResult` | — |

### منطق مشترک با Live
توابع خالص trailing/partial/pip در `tradingbot/domain/position_logic.py` قرار گرفتند تا
`Mt5PositionManager` (live) و `BacktestPositionManager` (backtest) **دقیقاً یک رفتار** داشته باشند
(Single Source of Truth).

### Parity ریسک (ژوئن ۲۰۲۶)
`BacktestRiskGate` و `RiskGate` (live) هر دو از **`domain/live_gates.py`** استفاده می‌کنند:

| فیلتر | Live | Backtest |
|-------|------|----------|
| max positions (کل + per-symbol) | ✅ | ✅ |
| HTF alignment (M15→H4، H4→D1) | ✅ | ✅ (`htf_provider.py` + preset per-TF) |
| spread / news / friday | ✅ | ✅ |
| regime → ضریب لات | ✅ | ✅ |

برای M15/H4 موتور بک‌تست دادهٔ HTF (H4 یا D1) را جداگانه لود می‌کند و `htf_bias` را
فقط از کندل‌های **بسته‌شده** محاسبه می‌کند (بدون look-ahead). پرچم‌های HTF و max positions
از `pa_symbol_tf_presets.py` per-TF خوانده می‌شوند (parity با live).

اعتبارسنجی: `python scripts/check_live_setup.py` و `python scripts/run_backtest.py --days 30`

## ترتیب پردازش هر کندل (بدون look-ahead)

1. **خروج پوزیشن‌های قبلی** روی range کندل جدید (SL/TP درون‌کندلی با high/low). برخورد همزمان SL مقدم است.
2. **mark-to-market + مدیریت هسته‌محور**: trailing پلکانی ATR، partial TP (۱R→۵۰٪، ۲R→۳۰٪، ۳R→۲۰٪)، حد ضرر اضطراری.
3. **ورود جدید**: اجرای کامل pipeline هسته (Data → Indicators → Signals → Risk → Execution). سفارش روی close کندل با spread/slippage پر می‌شود.
4. **ثبت نقطه‌ی equity**.

نکته‌ی مهم: اندیکاتورها **یک‌بار** روی کل سری محاسبه می‌شوند (causal — هر کندل فقط به گذشته وابسته است)،
سپس در هر گام فقط برشِ تا کندل جاری به استراتژی داده می‌شود. این هم سرعت را بالا می‌برد و هم
دقت اندیکاتورها را در پنجره‌های کوچک حفظ می‌کند.

## متریک‌ها

- **Profit Factor واقعی** = مجموع سود ناخالص ÷ مجموع زیان ناخالص (نه فرمول ساده‌شده‌ی پروژه‌ی قدیم).
- Win rate، Net profit، Return %، میانگین برد/باخت، Expectancy.
- **Max Drawdown** از روی equity curve (peak-to-trough).
- **Sharpe** سالانه‌شده بر اساس بازده‌ی هر کندل و ضریب تایم‌فریم.
- تفکیک دلیل خروج: `sl | tp | trailing | emergency | partial | end`.

## نحوه‌ی اجرا

```powershell
cd "c:\Users\AMIR\Desktop\TradingBot new"

python scripts/run_backtest.py --symbol XAUUSD --tf M15 --days 30 --balance 1000 --risk 0.005
python scripts/run_backtest.py --symbol XAUUSD --tf M5 --days 30 --min-confidence 0.54 --save reports/bt.json
python scripts/backtest_custom_range.py --start "2026-06-01 08:00" --end "2026-06-07 20:00" --balance 200
python -m tradingbot --backtest --symbol XAUUSD --tf M15 --bars 1500
```

داده در `data/backtest/{symbol}_{tf}.parquet` کش می‌شود؛ اجرای بعدی بدون دریافت مجدد از MT5 انجام می‌شود
(برای نادیده‌گرفتن کش: `--no-cache`).

## اعتبارسنجی

استراتژی Price Action **گزینشی** است؛ روی بازه کوتاه ممکن است معامله کم باشد. برای تأیید:

```powershell
python scripts/check_live_setup.py
python scripts/run_backtest.py --symbol XAUUSD --tf M15 --days 30
python -m tradingbot --strategies
```

گزارش‌های بک‌تست در `reports/` ذخیره می‌شوند (`--save`).

## نکات و محدودیت‌ها

- پرکردن سفارش روی **close** کندل انجام می‌شود (نه tick‌به‌tick)؛ برای تایم‌فریم‌های پایین واقع‌گرایانه است.
- مدل هزینه تقریبی است: spread + slippage (pip) + کمیسیون به‌ازای لات (قابل تنظیم در `BacktestConfig`).
- اندازه‌ی قرارداد (PnL) برای طلا/JPY/فارکس تقریبی است (`domain/position_logic.contract_size`).
- استراتژی‌های legacy live-محورند و فقط برای آخرین کندل سیگنال می‌دهند؛ بنابراین بک‌تست هم به‌صورت per-bar اجرا می‌شود (نه precompute).
- سرعت: حدوداً چند صد کندل در دقیقه (محاسبه‌ی استراتژی روی هر کندل گلوگاه است)؛ برای دوره‌های بلند، تایم‌فریم بالاتر یا بازه‌ی کوتاه‌تر استفاده شود.
