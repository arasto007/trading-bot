# گام C — مدیریت کامل پوزیشن از هسته (Trailing / Partial TP)

## هدف
انتقال مدیریت پوزیشن‌های باز از یک Thread مستقل (`PositionProtector` قدیم) به
**مسیر قطعی و قابل‌لاگ هسته**. حالا در هر چرخه‌ی `TradingKernel.run_global_cycle`
یک مدیر پوزیشن واحد، همه‌ی پوزیشن‌ها را مدیریت می‌کند.

## اجزای جدید

| فایل | نقش |
|------|-----|
| `tradingbot/ports/position_manager.py` | پورت `IPositionManager` با متد `manage_all()` |
| `tradingbot/adapters/mt5_position_manager.py` | آداپتر `Mt5PositionManager` — پیاده‌سازی کامل |

## مکانیزم‌ها (به ترتیب اجرا برای هر پوزیشن)

1. **Emergency Stop** — اگر ضرر از حد مجاز (پیش‌فرض ۵۰ pips) بگذرد، پوزیشن فوراً بسته می‌شود.
2. **Partial TP (مبتنی بر R)** — ریسک اولیه `R = |entry − SL|` محاسبه و در سطوح زیر برداشت سود پله‌ای انجام می‌شود:
   - `1R` → بستن ۵۰٪
   - `2R` → بستن ۳۰٪
   - `3R` → بستن ۲۰٪ (باقیمانده)
3. **Trailing Stop پلکانی ATR-Based** — بازسازی دقیق `_calculate_aggressive_sl` قدیم:
   - `0–8 pips`: SL = ورود − ۵ pip
   - `8–15 pips`: SL = نقطه سربه‌سر (breakeven)
   - `15–30 pips`: فاصله = `2.0×ATR` (حداقل ۱۲ pip)
   - `30–50 pips`: فاصله = `1.5×ATR` (حداقل ۱۰ pip)
   - `50–100 pips`: فاصله = `1.2×ATR` (حداقل ۸ pip)
   - `100+ pips`: فاصله = `1.0×ATR` (حداقل ۸ pip)
   - **هرگز شل نمی‌شود** (یک‌طرفه به نفع سود).

## اتصال به هسته
- `TradingKernel` آرگومان اختیاری `position_manager` گرفت.
- در پایان هر `run_global_cycle`، متد `_manage_positions()` یک‌بار `manage_all()` را صدا می‌زند.
- `build_kernel_live` و `LiveRunner` به‌صورت پیش‌فرض `Mt5PositionManager` را وصل می‌کنند.

## حذف تداخل
- `PositionProtector` قدیم به‌صورت **پیش‌فرض خاموش** است (`enable_protector=False`) تا با مدیریت هسته
  تداخل (مثل partial-close دوباره) ایجاد نشود. برای فعال‌سازی دستی: فلگ `--protector`.
- `PositionRecoveryService` همچنان روشن است (بازیابی پس از ری‌استارت).

## حالت امن (Dry-Run)
با `TRADINGBOT_DRY_RUN=1` (پیش‌فرض در حالت‌های تست و `--loop` بدون `--execute`)، مدیر پوزیشن
فقط **لاگ** می‌کند و هیچ سفارش اصلاح/بستن واقعی ارسال نمی‌کند.

## تست
```bash
# تست منطق (بدون MT5)
python scripts/test_position_mgr_stepC.py

# تست + یک چرخه dry-run روی MT5 واقعی
python scripts/test_position_mgr_stepC.py --live
```
نتیجه‌ی مورد انتظار: `ALL OK` و جدول مراحل trailing.

## محدودیت‌های فعلی (برای فازهای بعد)
- رجیستری Partial TP درون‌حافظه‌ای است؛ پس از ری‌استارت ریسک اولیه از روی SL فعلی
  بازمحاسبه می‌شود (که ممکن است با trail جابه‌جا شده باشد). تثبیت دائمی در ادغام با
  `PositionRecoveryService` انجام خواهد شد.
- اندازه‌ی pip برای طلا/JPY heuristic است (`XAU`=0.1، `JPY`=0.01، بقیه=0.0001).
