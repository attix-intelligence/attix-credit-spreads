"""
EXP-3311 — Event-Calendar Entry Gate.

Implements a blackout calendar covering FOMC, CPI, Non-Farm Payrolls (NFP),
and monthly options expiration (OpEx) Fridays. Credit-spread *entries* whose
trade date falls inside any blackout window are skipped; the signal stays
armed and may re-fire on the next non-blackout day. Once a trade is opened
its existing exit logic is untouched.

Why
---
Adverse-selection literature (Hu 2014; Kacperczyk & Pagnotta 2024) shows
that effective option spreads widen 20-40% in the 60-90 minutes before
known macro events. Our edge is statistical VRP, not informational — we
pay the widening without compensating return. The hypothesis is that a
modest blackout window around scheduled events reduces transaction-cost
drag by 50-150 bps/yr while removing few trades.

Sources
-------
- FOMC dates: ``shared.constants.FOMC_DATES`` (hand-maintained, real).
- CPI release: 2nd Tuesday-Wednesday each month (BLS schedule). We use
  2nd Wednesday as a deterministic proxy — matches the existing
  ``shared.economic_calendar.EconomicCalendar`` convention.
- NFP release: 1st Friday each month (BLS schedule). Deterministic.
- OpEx: 3rd Friday each month (US listed options convention).
  Deterministic.

No CPI/NFP/OpEx data is fetched from a network source — the conventions
above are publicly documented schedules and are reproducible from a
calendar alone. Rule Zero compliant.

Default window
--------------
``(-1, 0)`` — blackout = (T-1 trading day) and (event day T). This matches
the EXP-3310 specification: avoid entries on the trading day immediately
before a scheduled event and on the event day itself.

Public API
----------
- :class:`EventCalendar` — built once per backtest run.
- :meth:`EventCalendar.is_blackout(date, window=(-1, 0))` — True if *date*
  falls within ``window[0]``..``window[1]`` trading days of any tracked
  event.
- :meth:`EventCalendar.active_events(date, window=(-1, 0))` — list of
  ``(event_type, event_date, day_offset)`` tuples for diagnostics.
- :meth:`EventCalendar.coverage_stats(start, end)` — fraction of trading
  days in a window that are blacked out, by event type.

Notes
-----
- All comparisons are date-level (not timestamps). Event timezones are
  irrelevant since we operate on US trading-day calendars.
- The blackout offset is measured in *calendar* days for simplicity. For
  events that fall on weekends (rare for FOMC/CPI/NFP; never for OpEx),
  the gate still blackouts the surrounding ±N days. The downstream entry
  logic only fires on trading days, so non-trading-day blackouts have no
  effect except via the T-1 rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.constants import FOMC_DATES


# ---------------------------------------------------------------------------
# Public defaults
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: Tuple[int, int] = (-1, 0)
EVENT_TYPES: Tuple[str, ...] = ("fomc", "cpi", "nfp", "opex")


# ---------------------------------------------------------------------------
# Deterministic date generators
# ---------------------------------------------------------------------------


def cpi_dates(year: int) -> List[date]:
    """CPI release dates: BLS schedules CPI on the 2nd Tuesday/Wednesday.

    We use 2nd Wednesday as the deterministic proxy.
    """
    out: List[date] = []
    for month in range(1, 13):
        first = date(year, month, 1)
        first_wed = first + timedelta(days=(2 - first.weekday()) % 7)
        out.append(first_wed + timedelta(days=7))
    return out


def nfp_dates(year: int) -> List[date]:
    """Non-Farm Payrolls release dates: 1st Friday each month."""
    out: List[date] = []
    for month in range(1, 13):
        first = date(year, month, 1)
        out.append(first + timedelta(days=(4 - first.weekday()) % 7))
    return out


def opex_dates(year: int) -> List[date]:
    """Monthly options expiration: 3rd Friday each month."""
    out: List[date] = []
    for month in range(1, 13):
        first = date(year, month, 1)
        first_fri = first + timedelta(days=(4 - first.weekday()) % 7)
        out.append(first_fri + timedelta(days=14))
    return out


def _to_date(d) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, pd.Timestamp):
        return d.to_pydatetime().date()
    if isinstance(d, str):
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    raise TypeError(f"Unsupported date type: {type(d)}")


# ---------------------------------------------------------------------------
# Event calendar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventRecord:
    event_type: str
    event_date: date


class EventCalendar:
    """Unified event calendar with O(1) blackout lookup."""

    def __init__(self, years: Optional[Iterable[int]] = None) -> None:
        if years is None:
            years = range(2018, 2031)
        years = sorted(set(int(y) for y in years))

        self._events: List[EventRecord] = []

        # FOMC: real, hand-maintained list
        for dt in FOMC_DATES:
            d = dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date()
            if d.year in years:
                self._events.append(EventRecord("fomc", d))

        # Deterministic schedules for CPI/NFP/OpEx
        for y in years:
            for d in cpi_dates(y):
                self._events.append(EventRecord("cpi", d))
            for d in nfp_dates(y):
                self._events.append(EventRecord("nfp", d))
            for d in opex_dates(y):
                self._events.append(EventRecord("opex", d))

        # Sort + build an event-date -> event_types map for fast lookup
        self._events.sort(key=lambda e: (e.event_date, e.event_type))
        self._by_date: Dict[date, List[str]] = {}
        for ev in self._events:
            self._by_date.setdefault(ev.event_date, []).append(ev.event_type)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_blackout(
        self,
        d,
        window: Tuple[int, int] = DEFAULT_WINDOW,
        event_types: Optional[Sequence[str]] = None,
    ) -> bool:
        """Return True if *d* is within ``window`` (calendar) days of any event.

        ``window = (-1, 0)`` means the day before and the day of the event
        are both blackouts; the event must occur in ``[d, d - window[0]]``
        i.e. up to ``-window[0]`` days *after* d.
        """
        target = _to_date(d)
        lo, hi = window
        if lo > hi:
            raise ValueError(f"window lo > hi: {window}")
        types = set(event_types) if event_types is not None else None
        for off in range(lo, hi + 1):
            probe = target + timedelta(days=-off)
            # off=-1 means event is +1 day after target (i.e. tomorrow)
            #   probe = target - (-1) = target + 1
            # off= 0 means event is on target day
            #   probe = target
            evs = self._by_date.get(probe)
            if evs is None:
                continue
            if types is None or any(t in types for t in evs):
                return True
        return False

    def active_events(
        self,
        d,
        window: Tuple[int, int] = DEFAULT_WINDOW,
    ) -> List[Tuple[str, date, int]]:
        """Return all events triggering the blackout for *d*.

        Each tuple = ``(event_type, event_date, offset_days)`` where
        ``offset_days = event_date - d`` (positive = event is in future).
        """
        target = _to_date(d)
        lo, hi = window
        hits: List[Tuple[str, date, int]] = []
        for off in range(lo, hi + 1):
            probe = target + timedelta(days=-off)
            for t in self._by_date.get(probe, ()):
                hits.append((t, probe, (probe - target).days))
        return hits

    def all_dates(self) -> List[date]:
        return [e.event_date for e in self._events]

    def by_type(self, event_type: str) -> List[date]:
        return [e.event_date for e in self._events if e.event_type == event_type]

    def coverage_stats(
        self,
        start,
        end,
        window: Tuple[int, int] = DEFAULT_WINDOW,
    ) -> Dict[str, float]:
        """Fraction of trading days in [start, end] that are blacked out.

        Uses pandas business-day index, US holiday calendar is not
        applied (the bdate_range is close enough for diagnostic stats).
        """
        idx = pd.bdate_range(start=_to_date(start), end=_to_date(end))
        n = len(idx)
        if n == 0:
            return {"n_days": 0, "blackout_pct": 0.0}
        per_type: Dict[str, int] = {t: 0 for t in EVENT_TYPES}
        any_count = 0
        for ts in idx:
            d = ts.date()
            hit_any = False
            for t in EVENT_TYPES:
                if self.is_blackout(d, window=window, event_types=[t]):
                    per_type[t] += 1
                    hit_any = True
            if hit_any:
                any_count += 1
        return {
            "n_days": n,
            "blackout_pct": round(100 * any_count / n, 2),
            **{f"{t}_pct": round(100 * per_type[t] / n, 2) for t in EVENT_TYPES},
        }

    # ------------------------------------------------------------------
    # Convenience filters for trade tapes
    # ------------------------------------------------------------------

    def filter_trades(
        self,
        trades: Sequence,
        entry_date_attr: str = "entry_date",
        window: Tuple[int, int] = DEFAULT_WINDOW,
    ) -> Tuple[list, list]:
        """Split *trades* into (kept, dropped) by entry-date blackout.

        Works on both dataclass-like (e.g. ``SpreadTrade``) records and
        dict-style trade records, identified by ``entry_date_attr``.
        """
        kept, dropped = [], []
        for t in trades:
            if hasattr(t, entry_date_attr):
                ed = getattr(t, entry_date_attr)
            else:
                ed = t[entry_date_attr]
            if self.is_blackout(ed, window=window):
                dropped.append(t)
            else:
                kept.append(t)
        return kept, dropped


# ---------------------------------------------------------------------------
# CLI helper (diagnostics only — does not run a backtest)
# ---------------------------------------------------------------------------


def _main() -> None:  # pragma: no cover
    cal = EventCalendar()
    stats = cal.coverage_stats("2020-01-01", "2025-12-31")
    print("EXP-3311 EventCalendar coverage 2020-01-01 → 2025-12-31")
    print(f"  trading days:           {stats['n_days']}")
    print(f"  any-event blackout pct: {stats['blackout_pct']:.2f}%")
    for t in EVENT_TYPES:
        print(f"  {t:5s} blackout pct:       {stats[f'{t}_pct']:.2f}%")
    print(f"\n  total event records:    {len(cal._events)}")
    for t in EVENT_TYPES:
        print(f"  {t:5s} events 2020-2025:   "
              f"{sum(1 for d in cal.by_type(t) if 2020 <= d.year <= 2025)}")


if __name__ == "__main__":
    _main()
