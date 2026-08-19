"""
بارگذاری پیکربندی موتور معاملاتی — کاملاً مستقل از پروژه‌ی قدیم.

کد منطقی اکنون در پکیج محلی `engine` زندگی می‌کند (داخل همین پروژه). این ماژول
فقط مطمئن می‌شود ریشه‌ی پروژه روی `sys.path` هست (تا `import engine` همه‌جا کار
کند) و config نهایی را از `engine.config` + `engine.live_config` می‌سازد.

نام‌های تاریخی (`ensure_legacy_path`, `load_legacy_config`, `legacy_root`) برای
سازگاری با آداپترهای موجود حفظ شده‌اند؛ دیگر هیچ ارجاعی به پروژه‌ی بیرونی ندارند.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT: Path | None = None


def project_root() -> Path:
    """ریشه‌ی پروژه‌ی جدید (جایی که پکیج `engine` قرار دارد)."""
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        _PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../TradingBot new
    return _PROJECT_ROOT


def ensure_engine_path() -> Path:
    """اطمینان از اینکه پکیج محلی `engine` قابل import است (ریشه روی sys.path)."""
    root = project_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


# --- سازگاری به‌عقب (نام‌های قدیمی) -------------------------------------------
def legacy_root() -> Path:
    return project_root()


def ensure_legacy_path() -> Path:
    return ensure_engine_path()


_MT5_KEYS = frozenset({"MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"})


def _is_empty_mt5_value(key: str, value: Any) -> bool:
    if key not in _MT5_KEYS:
        return False
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def load_legacy_config() -> dict[str, Any]:
    """
    ادغام config پایه + live_config.

    اولویت با متغیرهای محیطی برای MT5:
      MT5_LOGIN, MT5_PASSWORD, MT5_SERVER

    مقادیر None/خالی live.py نباید credentials معتبر engine_settings را پاک کنند.
    """
    ensure_engine_path()
    from tradingbot.config.engine_settings import config as engine_config
    from tradingbot.config.live import get_live_config
    from tradingbot.config.price_action import PA_COOLDOWN_BARS, PRICE_ACTION_CONFIG
    from tradingbot.config.prop_presets import apply_prop_preset

    base = (
        engine_config.get_config()
        if hasattr(engine_config, "get_config")
        else dict(engine_config)
    )
    merged: dict[str, Any] = dict(base)
    for key, value in get_live_config().items():
        if _is_empty_mt5_value(key, value):
            continue
        merged[key] = value
    merged["PRICE_ACTION"] = PRICE_ACTION_CONFIG
    # PA cooldown parity — do not use VOL_REGIME_COOLDOWN_BARS here.
    merged["COOLDOWN_BARS"] = int(
        PRICE_ACTION_CONFIG.get("COOLDOWN_BARS", PA_COOLDOWN_BARS)
    )

    if os.getenv("MT5_LOGIN"):
        merged["MT5_LOGIN"] = int(os.environ["MT5_LOGIN"])
    if os.getenv("MT5_PASSWORD"):
        merged["MT5_PASSWORD"] = os.environ["MT5_PASSWORD"]
    if os.getenv("MT5_SERVER"):
        merged["MT5_SERVER"] = os.environ["MT5_SERVER"]

    merged.setdefault("BASE_DIR", str(project_root()))
    return apply_prop_preset(merged)
