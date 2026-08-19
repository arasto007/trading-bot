"""
services — سرویس‌های پس‌زمینه‌ی مستقل (محافظت/بازیابی پوزیشن) روی MT5.

این سرویس‌ها مستقل از pipeline اصلی و در thread جداگانه اجرا می‌شوند و هیچ
وابستگی‌ای به پکیج legacy `engine` ندارند.
"""

from __future__ import annotations

__all__: list[str] = []
