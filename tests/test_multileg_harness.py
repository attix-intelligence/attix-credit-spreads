"""Tests for backtest/multileg.py — the shared direct-marks multi-leg harness.

Fixture data is a throwaway SQLite with the option_contracts/option_daily
schema. Synthetic numbers are fine HERE (unit tests of arithmetic/semantics);
Rule Zero governs experiment results, which always run over the real cache.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backtest.multileg import (  # noqa: E402
    EntryResult, Leg, MarksDB, Position, close_position, net_mark,
    profit_target, roll_at_dte, run_portfolio, stop_loss, time_stop, try_enter,
)


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "marks.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE option_contracts (ticker TEXT, expiration TEXT, "
                 "strike REAL, option_type TEXT, contract_symbol TEXT PRIMARY KEY, "
                 "as_of_date TEXT)")
    conn.execute("CREATE TABLE option_daily (contract_symbol TEXT, date TEXT, "
                 "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                 "open_interest REAL, PRIMARY KEY(contract_symbol, date))")
    contracts = [
        ("GLD", "2024-03-15", 190.0, "P", "O:GLD240315P00190000"),
        ("GLD", "2024-03-15", 185.0, "P", "O:GLD240315P00185000"),
        ("GLD", "2024-04-19", 190.0, "P", "O:GLD240419P00190000"),
    ]
    conn.executemany(
        "INSERT INTO option_contracts VALUES (?,?,?,?,?,'2024-01-01')", contracts)
    bars = [
        # short 190P / long 185P vertical: day1 open credit 1.00, close credit 0.97
        ("O:GLD240315P00190000", "2024-02-01", 3.00, 3.2, 2.8, 2.97, 100),
        ("O:GLD240315P00185000", "2024-02-01", 2.00, 2.1, 1.9, 2.00, 100),
        # day2: credit decays to 0.40 (profit for a 1.00-credit seller)
        ("O:GLD240315P00190000", "2024-02-02", 2.40, 2.5, 2.3, 2.40, 100),
        ("O:GLD240315P00185000", "2024-02-02", 2.00, 2.1, 1.9, 2.00, 100),
        # day3: short leg has NO bar (stale-mark path); long leg present
        ("O:GLD240315P00185000", "2024-02-05", 2.00, 2.1, 1.9, 2.00, 100),
        # calendar back leg (for debit tests)
        ("O:GLD240419P00190000", "2024-02-01", 5.00, 5.2, 4.9, 5.10, 50),
        # bar with NULL open (legacy row -> naive fallback path)
        ("O:GLD240315P00190000", "2024-02-06", None, None, None, 2.00, 0),
        ("O:GLD240315P00185000", "2024-02-06", None, None, None, 1.50, 0),
    ]
    conn.executemany(
        "INSERT INTO option_daily VALUES (?,?,?,?,?,?,?,NULL)", bars)
    conn.commit()
    conn.close()
    m = MarksDB(p)
    yield m
    m.close()


VERT = [Leg("O:GLD240315P00190000", side=-1, expiration="2024-03-15"),
        Leg("O:GLD240315P00185000", side=+1, expiration="2024-03-15")]

CAL = [Leg("O:GLD240315P00190000", side=-1, expiration="2024-03-15"),
       Leg("O:GLD240419P00190000", side=+1, expiration="2024-04-19")]


def test_net_mark_sign_convention(db):
    # short 2.97 / long 2.00 at close -> credit 0.97 received
    v, complete, had = net_mark(db, VERT, "2024-02-01", "close")
    assert v == pytest.approx(0.97)
    assert complete and had
    # calendar: short 2.97 - long 5.10 -> net debit -2.13
    v, _, _ = net_mark(db, CAL, "2024-02-01", "close")
    assert v == pytest.approx(2.97 - 5.10)


def test_net_mark_stale_carry(db):
    carry = {}
    net_mark(db, VERT, "2024-02-02", "close", carry=carry)   # seeds carry
    v, complete, _ = net_mark(db, VERT, "2024-02-05", "close", carry=carry)
    assert not complete                       # short leg had no bar
    assert v == pytest.approx(2.40 - 2.00)    # short carried at 2.40


def test_marketable_fill_at_limit(db):
    # open credit 1.00, slip 0.05 -> limit 0.95; close credit 0.97 >= 0.95: fill AT 0.95
    er = try_enter(db, VERT, "2024-02-01", "marketable")
    assert er.filled and not er.naive_fallback
    assert er.net == pytest.approx(0.95)


def test_marketable_no_fill_when_credit_collapses(db):
    # day2 open credit 0.40 -> limit 0.35; but shift entry to a leg set where
    # close < limit: short opens 2.40 (credit 0.40), closes 2.40 -> close credit
    # 0.40 >= 0.35 fills; so instead test via a synthetic wide slip using CAL:
    # open net -2.00 -> limit -2.075 (pay <= 2.075); close net -2.13 < limit -> no fill
    er = try_enter(db, CAL, "2024-02-01", "marketable")
    assert not er.filled and er.reason == "never_marketable"


def test_naive_fallback_counted_on_missing_open(db):
    er = try_enter(db, VERT, "2024-02-06", "marketable")
    assert er.filled and er.naive_fallback
    assert er.net == pytest.approx(0.50 - 0.05)


def test_naive_model_books_at_close_minus_slip(db):
    er = try_enter(db, VERT, "2024-02-01", "naive")
    assert er.filled and er.net == pytest.approx(0.97 - 0.05)


def test_exit_rules():
    pos = Position(legs=VERT, entry_date="2024-02-01", entry_net=1.0)
    assert profit_target(0.5)(pos, "2024-02-02", 0.49) == "profit_target_50"
    assert profit_target(0.5)(pos, "2024-02-02", 0.51) is None
    assert stop_loss(2.0)(pos, "2024-02-02", 3.0) == "stop_2.0x"
    assert stop_loss(2.0)(pos, "2024-02-02", 2.9) is None
    assert time_stop(10)(pos, "2024-02-11", 1.0) == "time_10d"
    assert time_stop(10)(pos, "2024-02-10", 1.0) is None
    assert roll_at_dte(7)(pos, "2024-03-08", 1.0) == "roll_dte_7"
    assert roll_at_dte(7)(pos, "2024-03-07", 1.0) is None


def test_debit_structure_pnl_sign():
    # calendar entered at net -2.10 (paid 2.10); closed at cost -2.60
    # (received 2.60 back): profit = entry - cost = 0.50 per 1x
    pos = Position(legs=CAL, entry_date="2024-02-01", entry_net=-2.10)
    assert profit_target(0.2)(pos, "2024-02-02", -2.60) == "profit_target_20"


def test_run_portfolio_end_to_end(db):
    def signal(day, mdb, open_positions):
        if day == "2024-02-01" and not open_positions:
            return [(VERT, 2, {"tag": "test"})]
        return []

    res = run_portfolio(
        db, ["2024-02-01", "2024-02-02"], signal,
        exit_rules=[profit_target(0.5), stop_loss(2.0)],
        starting_capital=10_000.0, fill_model="marketable", max_positions=1)

    assert res.entry_attempts == 1 and res.entered == 1
    assert res.unfillable_entries == 0 and res.naive_fallback_entries == 0
    assert len(res.trades) == 1
    tr = res.trades[0]
    # entry at limit 0.95, day2 cost 0.40 -> PT50 fires;
    # pnl_1x = (0.95 - 0.40 - 0.10) * 100 = 45; x2 contracts - commissions
    # commissions = 0.65 * 2 legs * 2 contracts * 2 sides = 5.20
    assert tr["exit_reason"] == "profit_target_50"
    assert tr["pnl"] == pytest.approx(45 * 2 - 5.20)
    s = res.summary(10_000.0)
    assert s["total_trades"] == 1 and s["win_rate_pct"] == 100.0
    assert s["naive_fallback_share_pct"] == 0.0


def test_run_portfolio_counts_unfillable(db):
    def signal(day, mdb, open_positions):
        return [(CAL, 1, {})] if day == "2024-02-01" else []

    res = run_portfolio(db, ["2024-02-01"], signal, exit_rules=[],
                        fill_model="marketable")
    assert res.entry_attempts == 1 and res.entered == 0
    assert res.unfillable_entries == 1
