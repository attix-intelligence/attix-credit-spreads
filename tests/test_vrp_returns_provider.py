"""Persisted per-stream returns provider — schema, writer, provider round-trips."""
from __future__ import annotations

from datetime import date

import pytest

from compass.live.vrp_returns_provider import (
    PersistedReturnsProvider,
    backfill_zero_rows,
    record_stream_returns_for_day,
)
from shared.database import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Isolated SQLite DB for each test (via ATTIX_DB_PATH)."""
    p = tmp_path / "vrp_test.db"
    monkeypatch.setenv("ATTIX_DB_PATH", str(p))
    init_db()  # creates stream_equity_history (the migration we added)
    return str(p)


def test_table_created_with_expected_columns(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(stream_equity_history)").fetchall()}
    finally:
        conn.close()
    assert {"exp_id", "stream", "as_of_date", "daily_return", "daily_pnl",
            "equity_base", "source", "updated_at"}.issubset(cols)


def test_empty_provider_returns_empty_frame_with_requested_columns(db_path):
    prov = PersistedReturnsProvider("EXP-V8A", ["exp1220", "qqq_cs"])
    df = prov.stream_returns(lookback=30)
    assert df.empty
    assert list(df.columns) == ["exp1220", "qqq_cs"]


def test_writer_round_trip_and_pivot_wide(db_path):
    record_stream_returns_for_day(
        "EXP-V8A", date(2026, 5, 30),
        {"exp1220": 100.0, "qqq_cs": -50.0}, equity_base=100_000.0, source="monitor",
    )
    record_stream_returns_for_day(
        "EXP-V8A", date(2026, 5, 31),
        {"exp1220": 0.0, "qqq_cs": 25.0}, equity_base=100_000.0, source="monitor",
    )
    df = PersistedReturnsProvider("EXP-V8A", ["exp1220", "qqq_cs"]).stream_returns(lookback=10)
    assert list(df.columns) == ["exp1220", "qqq_cs"]
    assert len(df) == 2
    assert df.index.is_monotonic_increasing
    # daily_return = pnl / equity_base
    assert df.iloc[0]["exp1220"] == pytest.approx(100.0 / 100_000.0)
    assert df.iloc[1]["qqq_cs"] == pytest.approx(25.0 / 100_000.0)


def test_writer_is_idempotent_via_upsert(db_path):
    d = date(2026, 5, 30)
    record_stream_returns_for_day("EXP-V8A", d, {"exp1220": 100.0}, 100_000.0, source="monitor")
    record_stream_returns_for_day("EXP-V8A", d, {"exp1220": 200.0}, 100_000.0, source="monitor")
    df = PersistedReturnsProvider("EXP-V8A", ["exp1220"]).stream_returns(lookback=10)
    assert len(df) == 1
    assert df.iloc[0]["exp1220"] == pytest.approx(200.0 / 100_000.0)


def test_returns_are_isolated_by_exp_id(db_path):
    record_stream_returns_for_day("EXP-V8A", date(2026, 5, 30), {"exp1220": 100.0}, 100_000.0)
    record_stream_returns_for_day("EXP-V8A-IBKR", date(2026, 5, 30), {"exp1220": -100.0}, 100_000.0)
    v8a = PersistedReturnsProvider("EXP-V8A", ["exp1220"]).stream_returns(lookback=10)
    ibkr = PersistedReturnsProvider("EXP-V8A-IBKR", ["exp1220"]).stream_returns(lookback=10)
    assert v8a.iloc[0]["exp1220"] == pytest.approx(0.001)
    assert ibkr.iloc[0]["exp1220"] == pytest.approx(-0.001)


def test_lookback_caps_row_count(db_path):
    for i in range(5):
        record_stream_returns_for_day("EXP-V8A", date(2026, 5, 26 + i),
                                      {"exp1220": float(i)}, 100_000.0)
    df = PersistedReturnsProvider("EXP-V8A", ["exp1220"]).stream_returns(lookback=3)
    assert len(df) == 3
    # most recent 3 days kept (sorted ASC)
    assert df.index[0].date() == date(2026, 5, 28)
    assert df.index[-1].date() == date(2026, 5, 30)


def test_zero_backfill_writes_one_row_per_stream_per_day(db_path):
    n = backfill_zero_rows(
        "EXP-V8A", ["exp1220", "xlf_cs", "qqq_cs"],
        [date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28)],
        equity_base=0.0,
    )
    assert n == 3 * 3
    df = PersistedReturnsProvider("EXP-V8A", ["exp1220", "xlf_cs", "qqq_cs"]).stream_returns(lookback=30)
    assert df.shape == (3, 3)
    assert (df.fillna(0.0).values == 0.0).all()


def test_provider_satisfies_returns_provider_protocol():
    from compass.live.vrp_contracts import ReturnsProvider
    prov = PersistedReturnsProvider("EXP-V8A", ["exp1220"])
    assert isinstance(prov, ReturnsProvider)


def test_bad_exp_id_or_streams_raises():
    with pytest.raises(ValueError):
        PersistedReturnsProvider("", ["exp1220"])
    with pytest.raises(ValueError):
        PersistedReturnsProvider("EXP-V8A", [])
