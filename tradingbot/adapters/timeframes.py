"""تبدیل timeframe بین فرمت هسته جدید (M5) و legacy (5m)."""

from __future__ import annotations

# هسته جدید → legacy (DataPipeline / Storage)
KERNEL_TO_LEGACY: dict[str, str] = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "W1": "1w",
    "MN1": "mn1",
}

LEGACY_TO_KERNEL: dict[str, str] = {v: k for k, v in KERNEL_TO_LEGACY.items()}


def to_legacy(timeframe: str) -> str:
    tf = timeframe.strip()
    if tf in KERNEL_TO_LEGACY:
        return KERNEL_TO_LEGACY[tf]
    if tf.lower() in LEGACY_TO_KERNEL:
        return tf.lower()
    return tf.lower()


def to_kernel(timeframe: str) -> str:
    tf = timeframe.strip().lower()
    if tf in LEGACY_TO_KERNEL:
        return LEGACY_TO_KERNEL[tf]
    upper = timeframe.strip().upper()
    if upper in KERNEL_TO_LEGACY:
        return upper
    return upper
