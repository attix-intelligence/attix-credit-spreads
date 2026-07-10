"""shared/market_calendar.py — Minimal market-day-aware time helpers.

Exports :func:`trading_hours_between`, used by Sentinel Gate 24
(stale-halt nag) to age halts in trading hours rather than wall-clock
hours, and :func:`is_rth`, used by the Polygon provider to decide
whether prior-close fallback pricing is permissible.

Intentionally lightweight: NYSE regular session only (Mon-Fri 09:30-16:00
America/New_York). Holidays are NOT modelled here; per the Branch 8
spec for G24, "false positives during holiday weeks are acceptable" and
keeping this self-contained avoids pulling in a heavy market-calendar
dependency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")
_SESSION_OPEN_H, _SESSION_OPEN_M = 9, 30
_SESSION_CLOSE_H, _SESSION_CLOSE_M = 16, 0


def is_rth(now: datetime | None = None) -> bool:
    """Return True when *now* is inside NYSE regular trading hours.

    Regular session is Mon-Fri 09:30-16:00 America/New_York. Holidays are
    not modelled (same intentional limitation as :func:`trading_hours_between`).
    Naive datetimes are interpreted as UTC; ``None`` means "now".
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now_ny = now.astimezone(_NY)
    if now_ny.weekday() >= 5:
        return False
    session_open = now_ny.replace(
        hour=_SESSION_OPEN_H, minute=_SESSION_OPEN_M, second=0, microsecond=0
    )
    session_close = now_ny.replace(
        hour=_SESSION_CLOSE_H, minute=_SESSION_CLOSE_M, second=0, microsecond=0
    )
    return session_open <= now_ny < session_close


def trading_hours_between(start: datetime, end: datetime) -> float:
    """Return the number of NYSE regular-session hours between *start* and *end*.

    Trading session is Mon-Fri 09:30-16:00 America/New_York. Holidays are
    not modelled — this is intentionally a heuristic suitable for stale-halt
    ageing, not for accounting-grade calendars.

    Naive datetimes are interpreted as UTC. Returns 0.0 when ``end <= start``.
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    if end <= start:
        return 0.0

    start_ny = start.astimezone(_NY)
    end_ny = end.astimezone(_NY)

    total_seconds = 0.0
    cursor_date = start_ny.date()
    end_date = end_ny.date()
    while cursor_date <= end_date:
        if cursor_date.weekday() < 5:
            session_open = datetime(
                cursor_date.year, cursor_date.month, cursor_date.day,
                _SESSION_OPEN_H, _SESSION_OPEN_M, tzinfo=_NY,
            )
            session_close = datetime(
                cursor_date.year, cursor_date.month, cursor_date.day,
                _SESSION_CLOSE_H, _SESSION_CLOSE_M, tzinfo=_NY,
            )
            day_start = max(start_ny, session_open)
            day_end = min(end_ny, session_close)
            if day_end > day_start:
                total_seconds += (day_end - day_start).total_seconds()
        cursor_date += timedelta(days=1)
    return total_seconds / 3600.0
