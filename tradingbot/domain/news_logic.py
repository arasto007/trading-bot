"""
فیلتر اخبار با اثر بالا — blackout قبل/بعد رویدادهای USD (برای XAUUSD).

بدون API خارجی: تقویم ثابت + الگوهای تکرارشونده (NFP اولین جمعه ماه).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable


def _to_naive_utc(ts: datetime) -> datetime:
    """Normalize tz-aware/naive timestamps for calendar comparisons."""
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()  # type: ignore[union-attr]
    if not isinstance(ts, datetime):
        return datetime.utcnow()
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts

# رویدادهای با اثر بالا — (سال، ماه، روز، ساعت UTC، دقیقه)
_KNOWN_EVENTS: tuple[tuple[int, int, int, int, int], ...] = (
    # ۲۰۲۶ — NFP (اولین جمعه)
    (2026, 2, 6, 13, 30),
    (2026, 3, 6, 13, 30),
    (2026, 4, 3, 13, 30),
    (2026, 5, 1, 13, 30),
    (2026, 6, 5, 13, 30),
    # CPI تقریبی
    (2026, 2, 12, 13, 30),
    (2026, 3, 12, 13, 30),
    (2026, 4, 10, 13, 30),
    (2026, 5, 13, 13, 30),
    (2026, 6, 11, 13, 30),
    # FOMC
    (2026, 3, 19, 19, 0),
    (2026, 5, 7, 19, 0),
    (2026, 6, 18, 19, 0),
)


def _first_friday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d.replace(hour=13, minute=30, second=0, microsecond=0)


def _recurring_events(ts: datetime) -> list[datetime]:
    """NFP اولین جمعه هر ماه — ±blackout."""
    out: list[datetime] = []
    for month in (ts.month - 1, ts.month, ts.month + 1):
        y = ts.year
        if month < 1:
            month += 12
            y -= 1
        elif month > 12:
            month -= 12
            y += 1
        try:
            out.append(_first_friday(y, month))
        except ValueError:
            pass
    return out


def _iter_event_times(ts: datetime) -> Iterable[datetime]:
    ts = _to_naive_utc(ts)
    day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    for ev in _KNOWN_EVENTS:
        y, m, d, h, mi = ev
        if abs((datetime(y, m, d) - day_start).days) <= 2:
            yield datetime(y, m, d, h, mi)
    for ev in _recurring_events(ts):
        if abs((ev.date() - ts.date()).days) <= 2:
            yield ev


def is_news_blackout(
    ts: datetime,
    *,
    minutes_before: int = 30,
    minutes_after: int = 30,
) -> bool:
    """True اگر در بازه blackout اخبار با اثر بالا باشیم."""
    if ts is None:
        return False
    ts = _to_naive_utc(ts)
    window_before = timedelta(minutes=minutes_before)
    window_after = timedelta(minutes=minutes_after)
    for event_time in _iter_event_times(ts):
        if event_time - window_before <= ts <= event_time + window_after:
            return True
    return False
