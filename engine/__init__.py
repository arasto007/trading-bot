"""engine — vendored, self-contained trading logic for TradingBot.

این پکیج کد منطقی منتقل‌شده از پروژه‌ی قدیم است (استراتژی‌ها، اندیکاتورها،
ریسک، داده، اجرا و سرویس‌های پس‌زمینه) که اکنون کاملاً داخل همین پروژه زندگی
می‌کند. برخلاف نسخه‌ی قدیمی `core/`، این `__init__` هیچ عارضه‌ی جانبی موقع
import ندارد (نه فعال‌سازی خودکار کش، نه monkey-patch، نه دستکاری sys.path).
"""

from __future__ import annotations

__all__: list[str] = []
