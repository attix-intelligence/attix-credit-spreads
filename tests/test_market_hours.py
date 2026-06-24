"""Tests for execution.market_hours.is_rth_now — the broker-agnostic RTH guard
used by ExecutionEngine when routing through the executor sink (V8A-TRADIER).

The function intentionally does NOT honour NYSE holidays — that's a conservative
floor; downstream brokers (Tradier / executor) reject holiday submits independently.
These tests only assert the documented behaviour: weekday RTH window in ET.
"""
from datetime import datetime, timezone

from execution.market_hours import is_rth_now


# ── inside / outside RTH on a weekday ───────────────────────────────────────

def test_inside_rth_weekday_returns_true():
    # 2026-06-23 (Tue) 14:00 UTC = 10:00 ET (DST in effect, ET = UTC-4) → inside RTH.
    now = datetime(2026, 6, 23, 14, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is True


def test_before_open_weekday_returns_false():
    # 2026-06-23 (Tue) 13:29 UTC = 09:29 ET → 1 minute before the open.
    now = datetime(2026, 6, 23, 13, 29, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is False


def test_at_open_weekday_returns_true():
    # 2026-06-23 (Tue) 13:30 UTC = 09:30 ET → boundary, inclusive.
    now = datetime(2026, 6, 23, 13, 30, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is True


def test_at_close_weekday_returns_false():
    # 2026-06-23 (Tue) 20:00 UTC = 16:00 ET → boundary, exclusive.
    now = datetime(2026, 6, 23, 20, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is False


def test_after_close_weekday_returns_false():
    # 2026-06-23 (Tue) 22:00 UTC = 18:00 ET — well after the close.
    now = datetime(2026, 6, 23, 22, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is False


# ── weekend ─────────────────────────────────────────────────────────────────

def test_saturday_returns_false():
    # 2026-06-27 (Sat) mid-day ET → False regardless of clock time.
    now = datetime(2026, 6, 27, 14, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is False


def test_sunday_returns_false():
    # 2026-06-28 (Sun) mid-day ET → False regardless of clock time.
    now = datetime(2026, 6, 28, 14, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is False


# ── DST transition sanity ───────────────────────────────────────────────────
# America/New_York switches to EDT on 2nd Sunday of March (2026: Mar 8) and
# back to EST on 1st Sunday of November (2026: Nov 1).  Pick mid-week dates
# bracketing each transition so daylight-savings handling is exercised.

def test_dst_just_after_spring_forward_weekday_inside_rth():
    # 2026-03-10 (Tue) 14:00 UTC = 10:00 EDT (UTC-4 after spring forward).
    now = datetime(2026, 3, 10, 14, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is True


def test_dst_just_before_spring_forward_weekday_inside_rth():
    # 2026-03-05 (Thu) 15:00 UTC = 10:00 EST (UTC-5 before spring forward).
    now = datetime(2026, 3, 5, 15, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is True


def test_dst_just_after_fall_back_weekday_inside_rth():
    # 2026-11-04 (Wed) 15:00 UTC = 10:00 EST (UTC-5 after fall back).
    now = datetime(2026, 11, 4, 15, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is True


def test_dst_just_before_fall_back_weekday_inside_rth():
    # 2026-10-30 (Fri) 14:00 UTC = 10:00 EDT (UTC-4 still in effect).
    now = datetime(2026, 10, 30, 14, 0, 0, tzinfo=timezone.utc)
    assert is_rth_now(now) is True


# ── default arg uses 'now' ──────────────────────────────────────────────────

def test_default_now_utc_works_without_args():
    # Smoke test: calling without args returns a bool (doesn't raise).
    assert isinstance(is_rth_now(), bool)
