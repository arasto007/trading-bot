"""تبدیل symbol به نام بروکر MT5 (مثلاً EURUSD → EURUSD_i)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_broker_symbol(symbol: str, config: dict[str, Any] | None = None) -> str:
    """
    نماد قابل معامله در MT5 را پیدا می‌کند.

    ترتیب امتحان: همان نماد → نماد + _i → نماد بدون _i
    """
    overrides = (config or {}).get("symbol_aliases", {})
    if symbol in overrides:
        return overrides[symbol]

    candidates = [symbol]
    if not symbol.endswith("_i"):
        candidates.append(f"{symbol}_i")
    else:
        candidates.append(symbol.removesuffix("_i"))

    try:
        from tradingbot.adapters.legacy_loader import ensure_legacy_path

        ensure_legacy_path()
        import MetaTrader5 as mt5  # noqa: E402

        for name in candidates:
            info = mt5.symbol_info(name)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(name, True)
                return name
    except Exception as e:
        logger.debug("MT5 symbol resolve skipped: %s", e)

    return candidates[0]
