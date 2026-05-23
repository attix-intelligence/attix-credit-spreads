"""Tests for backtest.market_history.load_market_history.

Mirrors tests/test_data_cache.py's mocking pattern: PolygonClient is a
MagicMock whose ``aggregates`` returns canned Polygon-shaped result lists.
The hybrid index path uses a real SQLite file pointed at a tmp_path fixture.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backtest import market_history as mh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_polygon_results(start: str, periods: int, base: float = 450.0, seed: int = 7):
    """Synthesize a Polygon /v2/aggs response (list of bar dicts)."""
    np.random.seed(seed)
    dates = pd.date_range(start, periods=periods, freq="B")
    close = base + np.cumsum(np.random.randn(periods) * 0.5)
    results = []
    for dt, c in zip(dates, close):
        ts_ms = int(pd.Timestamp(dt).tz_localize("UTC").timestamp() * 1000)
        results.append({
            "t": ts_ms,
            "o": float(c - 0.5),
            "h": float(c + 1.0),
            "l": float(c - 1.0),
            "c": float(c),
            "v": int(np.random.randint(1_000_000, 5_000_000)),
        })
    return results


def _mock_client_with(results):
    client = MagicMock()
    client.aggregates.return_value = results
    return client


@pytest.fixture(autouse=True)
def _reset_client():
    """Each test gets a clean module-level client + a fresh LRU cache."""
    mh._set_client(None)
    yield
    mh._set_client(None)


@pytest.fixture
def fake_sqlite(tmp_path, monkeypatch):
    """Build a tmp historical_indices.sqlite with rows in the pre-2023 window."""
    db = tmp_path / "historical_indices.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE historical_indices (
            ticker TEXT NOT NULL,
            date   TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (ticker, date)
        )
        """
    )
    rows = [
        ("I:VIX", "2023-02-09", 19.0, 20.0, 18.5, 19.5, 0.0),
        ("I:VIX", "2023-02-10", 20.0, 21.0, 19.5, 20.5, 0.0),
        ("I:VIX", "2023-02-13", 20.5, 21.5, 20.0, 21.0, 0.0),
        # Pre-warmup rows for the multi-year case
        ("I:VIX", "2020-03-16", 50.0, 60.0, 48.0, 55.0, 0.0),
        ("I:VIX3M", "2023-02-13", 22.0, 23.0, 21.5, 22.5, 0.0),
    ]
    conn.executemany(
        "INSERT INTO historical_indices VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(mh, "_BOOTSTRAP_DB", db)
    return db


# ---------------------------------------------------------------------------
# Stock path
# ---------------------------------------------------------------------------

class TestStockLoad:

    def test_spy_returns_yfinance_shape(self):
        results = _make_polygon_results("2024-01-02", 20)
        mh._set_client(_mock_client_with(results))

        df = mh.load_market_history("SPY", "2024-01-02", "2024-01-31")

        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.tz is None
        assert df.index.is_monotonic_increasing
        assert len(df) == 20

    def test_stock_uses_passthrough_ticker(self):
        client = _mock_client_with(_make_polygon_results("2024-01-02", 5))
        mh._set_client(client)

        mh.load_market_history("TLT", "2024-01-02", "2024-01-10")

        call = client.aggregates.call_args
        # Either positional or kwargs — assert ticker forwarded as-is
        ticker = call.kwargs.get("ticker") or call.args[0]
        assert ticker == "TLT"

    def test_accepts_date_and_datetime_and_str(self):
        results = _make_polygon_results("2024-01-02", 5)
        mh._set_client(_mock_client_with(results))

        df1 = mh.load_market_history("SPY", "2024-01-02", "2024-01-10")
        df2 = mh.load_market_history("SPY", date(2024, 1, 2), date(2024, 1, 10))
        df3 = mh.load_market_history("SPY", datetime(2024, 1, 2), datetime(2024, 1, 10))

        assert len(df1) == len(df2) == len(df3) == 5

    def test_returns_copy_so_caller_can_mutate(self):
        results = _make_polygon_results("2024-01-02", 5)
        mh._set_client(_mock_client_with(results))

        df1 = mh.load_market_history("SPY", "2024-01-02", "2024-01-10")
        df2 = mh.load_market_history("SPY", "2024-01-02", "2024-01-10")

        df1.iloc[0, 0] = -9999
        assert df2.iloc[0, 0] != -9999

    def test_empty_polygon_response_returns_empty_df(self):
        mh._set_client(_mock_client_with([]))

        df = mh.load_market_history("SPY", "2024-01-02", "2024-01-10")

        assert df.empty
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_end_before_start_returns_empty(self):
        mh._set_client(_mock_client_with(_make_polygon_results("2024-01-02", 5)))
        df = mh.load_market_history("SPY", "2024-01-10", "2024-01-02")
        assert df.empty


# ---------------------------------------------------------------------------
# Symbol normalization
# ---------------------------------------------------------------------------

class TestSymbolMap:

    def test_caret_vix_maps_to_i_vix(self, fake_sqlite):
        # All requested data lives in SQLite (< 2023-02-14)
        mh._set_client(_mock_client_with([]))  # Polygon arm shouldn't be called

        df = mh.load_market_history("^VIX", "2023-02-09", "2023-02-13")

        assert not df.empty
        assert df["Close"].iloc[-1] == 21.0  # 2023-02-13 row from the fixture

    def test_caret_gspc_maps_to_i_spx(self):
        client = _mock_client_with(_make_polygon_results("2024-01-02", 5, base=4800))
        mh._set_client(client)

        mh.load_market_history("^GSPC", "2024-01-02", "2024-01-10")

        # The client should have been called with the canonical Polygon ticker
        call = client.aggregates.call_args
        ticker = call.kwargs.get("ticker") or call.args[0]
        assert ticker == "I:SPX"

    def test_unknown_symbol_passes_through(self):
        client = _mock_client_with(_make_polygon_results("2024-01-02", 3, base=80))
        mh._set_client(client)

        mh.load_market_history("XLE", "2024-01-02", "2024-01-05")

        call = client.aggregates.call_args
        ticker = call.kwargs.get("ticker") or call.args[0]
        assert ticker == "XLE"


# ---------------------------------------------------------------------------
# Hybrid index path — the bootstrap-SQLite ↔ Polygon seam
# ---------------------------------------------------------------------------

class TestIndexHybrid:

    def test_sqlite_only_when_window_entirely_pre_2023(self, fake_sqlite):
        client = _mock_client_with([])  # Polygon not consulted
        mh._set_client(client)

        df = mh.load_market_history("^VIX", "2023-02-09", "2023-02-13")

        assert client.aggregates.call_count == 0
        assert len(df) == 3
        assert df.index[0] == pd.Timestamp("2023-02-09")
        assert df.index[-1] == pd.Timestamp("2023-02-13")

    def test_polygon_only_when_window_entirely_2023_onward(self, fake_sqlite):
        polygon_results = _make_polygon_results("2023-03-01", 10, base=20.0)
        client = _mock_client_with(polygon_results)
        mh._set_client(client)

        df = mh.load_market_history("^VIX", "2023-03-01", "2023-03-15")

        assert client.aggregates.call_count == 1
        assert len(df) == 10
        # Polygon arm shouldn't include any SQLite rows
        assert df.index[0] >= pd.Timestamp("2023-03-01")

    def test_crosses_seam_concatenates_both_sources(self, fake_sqlite):
        polygon_results = _make_polygon_results("2023-02-14", 5, base=21.5)
        client = _mock_client_with(polygon_results)
        mh._set_client(client)

        df = mh.load_market_history("^VIX", "2023-02-09", "2023-02-21")

        # 3 SQLite rows (2023-02-09, 02-10, 02-13) + 5 Polygon rows
        assert client.aggregates.call_count == 1
        assert len(df) == 3 + 5
        assert df.index[0] == pd.Timestamp("2023-02-09")
        # Polygon was called with from_date == 2023-02-14
        call = client.aggregates.call_args
        from_d = call.kwargs.get("from_date")
        assert from_d == "2023-02-14"

    def test_seam_dedupe_polygon_wins_on_overlap(self, fake_sqlite):
        # Inject a Polygon row for 2023-02-13 (a date that ALSO exists in SQLite)
        polygon_results = [{
            "t": int(pd.Timestamp("2023-02-13").tz_localize("UTC").timestamp() * 1000),
            "o": 99.0, "h": 99.0, "l": 99.0, "c": 99.0, "v": 0,
        }]
        client = _mock_client_with(polygon_results)
        mh._set_client(client)

        # We claim a hybrid window that includes 2023-02-13 in both arms.
        # The hybrid logic restricts SQLite to < 2023-02-14, so 2023-02-13 IS
        # in SQLite. Polygon's arm starts at 2023-02-14 — but if a future code
        # change ever shifts the seam, the de-dupe guard should still favor
        # Polygon. To exercise the guard, drop the seam constant by 1 day in
        # this test.
        with patch.object(mh, "_POLYGON_INDICES_START", date(2023, 2, 13)):
            df = mh.load_market_history("^VIX", "2023-02-09", "2023-02-15")

        # 2023-02-13 row's Close should be Polygon's 99.0, not SQLite's 21.0
        assert df.loc[pd.Timestamp("2023-02-13"), "Close"] == 99.0

    def test_pre_2020_vix_returns_only_sqlite(self, fake_sqlite):
        client = _mock_client_with([])
        mh._set_client(client)

        df = mh.load_market_history("^VIX", "2020-03-01", "2020-04-01")

        assert client.aggregates.call_count == 0
        assert len(df) == 1
        assert df["Close"].iloc[0] == 55.0


# ---------------------------------------------------------------------------
# Process-local LRU
# ---------------------------------------------------------------------------

class TestCache:

    def test_repeated_call_does_not_refetch(self):
        results = _make_polygon_results("2024-01-02", 5)
        client = _mock_client_with(results)
        mh._set_client(client)

        mh.load_market_history("SPY", "2024-01-02", "2024-01-10")
        mh.load_market_history("SPY", "2024-01-02", "2024-01-10")
        mh.load_market_history("SPY", "2024-01-02", "2024-01-10")

        assert client.aggregates.call_count == 1
