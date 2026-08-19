"""Port: مدیریت پوزیشن‌های باز — trailing stop, partial TP, emergency stop."""

from typing import Protocol


class IPositionManager(Protocol):
    """قرارداد مدیریت پوزیشن — معادل manage_trailing_stop + PartialTPManager + PositionProtector."""

    def manage_all(self) -> None:
        """مدیریت همه پوزیشن‌های باز در یک چرخه (trailing/partial/emergency)."""
        ...
