"""Broker-agnostic market-hours guard.

Used by ExecutionEngine when no Alpaca provider is configured (e.g. Tradier-via-executor route).
Conservative floor: blocks any submit outside NYSE RTH (09:30-16:00 ET, weekdays).

Does NOT account for NYSE holidays — that floor is intentional. Tradier and the executor
will independently reject holiday submits; this function is the engine-side defense in depth.
A NYSE calendar can be wired here later (pandas_market_calendars / exchange_calendars).
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")


def is_rth_now(now_utc: Optional[datetime] = None) -> bool:
    """True iff NYSE RTH is open at `now_utc` (defaults to now)."""
    now = now_utc or datetime.now(timezone.utc)
    et = now.astimezone(_NY)
    if et.weekday() >= 5:  # Sat / Sun
        return False
    open_t = et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= et < close_t
