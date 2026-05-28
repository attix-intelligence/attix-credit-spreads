"""Tests for the shared on-disk SQLite bar cache (shared/shared_bar_cache.py)."""
import sqlite3
import threading

import numpy as np
import pandas as pd
import pytest

from shared.shared_bar_cache import (
    Freshness,
    SharedBarCache,
    SharedCacheError,
    default_db_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(periods=30, seed=1):
    np.random.seed(seed)
    idx = pd.date_range("2024-01-02", periods=periods, freq="B")
    idx.name = "Date"
    close = 450.0 + np.cumsum(np.random.randn(periods))
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.random.randint(1_000_000, 5_000_000, periods).astype(float),
        },
        index=idx,
        columns=["Open", "High", "Low", "Close", "Volume"],
    )


@pytest.fixture
def cache(tmp_path):
    return SharedBarCache(db_path=str(tmp_path / "bars.db"), fresh_ttl=900, max_stale=3 * 86_400)


# ---------------------------------------------------------------------------
# read / write round-trip
# ---------------------------------------------------------------------------

def test_put_then_get_roundtrip(cache):
    df = _make_df()
    cache.put_bars("SPY", df)
    res = cache.get_bars("SPY")
    assert res.status == Freshness.FRESH
    assert len(res.df) == len(df)
    # OHLCV values survive the round-trip
    pd.testing.assert_series_equal(
        res.df["Close"].reset_index(drop=True),
        df["Close"].reset_index(drop=True),
        check_names=False,
    )
    assert list(res.df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert res.df.index.name == "Date"


def test_ticker_is_case_insensitive(cache):
    cache.put_bars("spy", _make_df())
    assert cache.get_bars("SPY").status == Freshness.FRESH


def test_put_is_idempotent_upsert(cache):
    df = _make_df(periods=20)
    cache.put_bars("TLT", df)
    cache.put_bars("TLT", df)  # second write must not duplicate rows
    res = cache.get_bars("TLT")
    assert len(res.df) == 20


def test_put_updates_existing_and_appends(cache):
    cache.put_bars("SPY", _make_df(periods=10))
    bigger = _make_df(periods=15)
    cache.put_bars("SPY", bigger)
    assert len(cache.get_bars("SPY").df) == 15


def test_empty_frame_is_noop(cache):
    cache.put_bars("SPY", pd.DataFrame())
    assert cache.get_bars("SPY").status == Freshness.MISS


# ---------------------------------------------------------------------------
# freshness / TTL
# ---------------------------------------------------------------------------

def test_miss_when_absent(cache):
    res = cache.get_bars("NOPE")
    assert res.status == Freshness.MISS
    assert res.df is None


def test_fresh_within_ttl(cache):
    cache.put_bars("SPY", _make_df())  # fetch_ts = now
    assert cache.get_bars("SPY").status == Freshness.FRESH


def test_stale_past_ttl(cache):
    import time
    # Write with a fetch timestamp older than fresh_ttl but within max_stale.
    cache.put_bars("SPY", _make_df(), fetch_ts=time.time() - 1000)  # fresh_ttl=900
    res = cache.get_bars("SPY")
    assert res.status == Freshness.STALE
    assert res.df is not None and not res.df.empty  # stale data is still served
    assert res.age > 900


def test_miss_when_older_than_max_stale(cache):
    import time
    cache.put_bars("SPY", _make_df(), fetch_ts=time.time() - (4 * 86_400))  # > max_stale
    res = cache.get_bars("SPY")
    assert res.status == Freshness.MISS
    assert res.df is None
    assert res.age is not None  # we still know how old it was


# ---------------------------------------------------------------------------
# schema / migration
# ---------------------------------------------------------------------------

def test_schema_initialised(tmp_path):
    p = str(tmp_path / "s.db")
    SharedBarCache(db_path=p)
    conn = sqlite3.connect(p)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"daily_bars", "bar_meta", "cache_schema"} <= names
    assert conn.execute("SELECT version FROM cache_schema").fetchone()[0] == 1
    conn.close()


def test_reopen_preserves_data(tmp_path):
    p = str(tmp_path / "s.db")
    c1 = SharedBarCache(db_path=p)
    c1.put_bars("SPY", _make_df(periods=12))
    c1.close()
    c2 = SharedBarCache(db_path=p)  # re-open = migration check path, no data loss
    assert len(c2.get_bars("SPY").df) == 12


def test_migration_from_empty_schema_table(tmp_path):
    """A db with cache_schema but no version row (current==0) gets fully built."""
    p = str(tmp_path / "s.db")
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE cache_schema (version INTEGER NOT NULL)")  # no row
    conn.commit()
    conn.close()
    c = SharedBarCache(db_path=p)  # must create daily_bars/bar_meta + version
    c.put_bars("SPY", _make_df(periods=5))
    assert len(c.get_bars("SPY").df) == 5


# ---------------------------------------------------------------------------
# corruption / fallback
# ---------------------------------------------------------------------------

def test_corrupt_db_raises_shared_cache_error(tmp_path):
    p = str(tmp_path / "corrupt.db")
    with open(p, "wb") as f:
        f.write(b"this is definitely not a sqlite database file " * 50)
    with pytest.raises(SharedCacheError):
        SharedBarCache(db_path=p)


def test_get_bars_raises_on_broken_table(tmp_path):
    """If the table is dropped underneath us, get_bars surfaces SharedCacheError."""
    p = str(tmp_path / "s.db")
    c = SharedBarCache(db_path=p)
    c.put_bars("SPY", _make_df())
    # Corrupt the schema out-of-band.
    conn = sqlite3.connect(p)
    conn.execute("DROP TABLE bar_meta")
    conn.commit()
    conn.close()
    c.close()  # drop cached connection so the next call reopens
    with pytest.raises(SharedCacheError):
        c.get_bars("SPY")


def test_healthy(tmp_path):
    c = SharedBarCache(db_path=str(tmp_path / "s.db"))
    assert c.healthy() is True


# ---------------------------------------------------------------------------
# concurrency (WAL)
# ---------------------------------------------------------------------------

def test_concurrent_readers_while_writing(tmp_path):
    p = str(tmp_path / "concurrent.db")
    writer = SharedBarCache(db_path=p)
    writer.put_bars("SPY", _make_df(periods=40))

    errors = []
    read_ok = []

    def reader():
        try:
            c = SharedBarCache(db_path=p)  # own connection (mimics a subprocess)
            for _ in range(15):
                res = c.get_bars("SPY")
                if res.status in (Freshness.FRESH, Freshness.STALE):
                    read_ok.append(len(res.df))
            c.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def writer_loop():
        try:
            c = SharedBarCache(db_path=p)
            for i in range(15):
                c.put_bars("SPY", _make_df(periods=40, seed=i))
            c.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(6)] + [
        threading.Thread(target=writer_loop)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent access raised: {errors}"
    assert read_ok and all(n == 40 for n in read_ok)


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------

def test_default_db_path_env_override(monkeypatch):
    monkeypatch.setenv("SHARED_CACHE_DB", "/tmp/custom_bars.db")
    assert default_db_path() == "/tmp/custom_bars.db"


def test_default_db_path_uses_data_dir(monkeypatch):
    monkeypatch.delenv("SHARED_CACHE_DB", raising=False)
    assert default_db_path().endswith("shared_bars.db")
