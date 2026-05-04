"""Tests for reconcile_positions.apply_plan superseding Gate-7 orphan placeholders.

When Gate 7 first detects an untracked broker leg, it inserts a placeholder
row (`status='unmanaged'`, `id='orphan_<OCC>'` or legacy `'orphan-<OCC>'`)
into the experiment's `trades` table. Until that row is closed or superseded,
Gate 23 re-alerts on it every cycle. Reconcile must transition those
placeholders out of `unmanaged` once a real `open` spread has been inserted
covering the same OCC symbols.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile_positions  # noqa: E402  (after sys.path insertion)


SCHEMA_TRADES = """
CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    source TEXT,
    ticker TEXT,
    strategy_type TEXT,
    status TEXT,
    short_strike REAL,
    long_strike REAL,
    expiration TEXT,
    credit REAL,
    contracts INTEGER,
    entry_date TEXT,
    exit_date TEXT,
    exit_reason TEXT,
    pnl REAL,
    metadata TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

SCHEMA_TRADE_LEGS = """
CREATE TABLE trade_legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT,
    leg_type TEXT,
    strike REAL,
    occ_symbol TEXT,
    status TEXT
);
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_TRADES + SCHEMA_TRADE_LEGS)
    return conn


def _seed_orphan_placeholder(conn: sqlite3.Connection, pid: str, occ: str) -> None:
    """Insert a Gate-7-style placeholder row mirroring sentinel/runtime.py."""
    conn.execute(
        "INSERT INTO trades (id, source, ticker, strategy_type, status, "
        "metadata, created_at, updated_at) VALUES "
        "(?, 'sentinel', 'SPY', 'unknown', 'unmanaged', ?, "
        " datetime('now', '-2 days'), datetime('now', '-2 days'))",
        (
            pid,
            json.dumps({"occ_symbol": occ, "detected_by": "sentinel_gate7"}),
        ),
    )
    conn.commit()


def _make_plan_with_one_spread() -> dict:
    """Construct a plan with a single inferred bull-put spread, no other ops."""
    return {
        "in_sync": [],
        "qty_mismatches": [],
        "broker_only": [],
        "db_only": [],
        "spreads_inferred": [
            {
                "ticker": "SPY",
                "expiration": "2026-05-08",
                "type": "P",
                "short_strike": 689.0,
                "long_strike": 684.0,
                "contracts": 10,
                "short_alpaca_sym": "SPY260508P00689000",
                "long_alpaca_sym": "SPY260508P00684000",
            }
        ],
    }


def test_apply_plan_supersedes_underscore_placeholder():
    conn = _make_conn()
    _seed_orphan_placeholder(conn, "orphan_SPY260508P00689000", "SPY260508P00689000")
    _seed_orphan_placeholder(conn, "orphan_SPY260508P00684000", "SPY260508P00684000")

    stats = reconcile_positions.apply_plan(conn, _make_plan_with_one_spread())

    assert stats["inserted_spreads"] == 1
    assert stats["orphans_superseded"] == 2
    rows = conn.execute(
        "SELECT id, status, metadata FROM trades WHERE id LIKE 'orphan%'"
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["status"] == "superseded"
        meta = json.loads(r["metadata"])
        assert meta["superseded_by_reconcile"].startswith("alpaca_backfill_")

    legs = conn.execute(
        "SELECT occ_symbol FROM trade_legs ORDER BY occ_symbol"
    ).fetchall()
    assert [r["occ_symbol"] for r in legs] == [
        "SPY260508P00684000",
        "SPY260508P00689000",
    ]


def test_apply_plan_supersedes_legacy_hyphen_placeholder():
    conn = _make_conn()
    _seed_orphan_placeholder(conn, "orphan-SPY260508P00689000", "SPY260508P00689000")

    stats = reconcile_positions.apply_plan(conn, _make_plan_with_one_spread())

    assert stats["orphans_superseded"] == 1
    row = conn.execute(
        "SELECT status FROM trades WHERE id = 'orphan-SPY260508P00689000'"
    ).fetchone()
    assert row["status"] == "superseded"


def test_apply_plan_leaves_unrelated_placeholders_alone():
    """Placeholders for OCCs not in this reconcile run must NOT be touched."""
    conn = _make_conn()
    _seed_orphan_placeholder(conn, "orphan_SPY260508P00689000", "SPY260508P00689000")
    _seed_orphan_placeholder(conn, "orphan_SPY260508P00684000", "SPY260508P00684000")
    # Unrelated placeholder — different expiry, not in plan.
    _seed_orphan_placeholder(conn, "orphan_SPY260515P00701000", "SPY260515P00701000")

    stats = reconcile_positions.apply_plan(conn, _make_plan_with_one_spread())

    assert stats["orphans_superseded"] == 2
    untouched = conn.execute(
        "SELECT status FROM trades WHERE id = 'orphan_SPY260515P00701000'"
    ).fetchone()
    assert untouched["status"] == "unmanaged"


def test_apply_plan_idempotent_on_second_run():
    """Re-running on a clean DB (placeholders already superseded) must be a no-op
    for the supersede pass — no rows revert, no extra updates."""
    conn = _make_conn()
    _seed_orphan_placeholder(conn, "orphan_SPY260508P00689000", "SPY260508P00689000")
    _seed_orphan_placeholder(conn, "orphan_SPY260508P00684000", "SPY260508P00684000")

    first = reconcile_positions.apply_plan(conn, _make_plan_with_one_spread())
    assert first["orphans_superseded"] == 2

    # Empty plan to simulate "nothing new to backfill" — idempotent path.
    empty_plan = {
        "in_sync": [],
        "qty_mismatches": [],
        "broker_only": [],
        "db_only": [],
        "spreads_inferred": [],
    }
    second = reconcile_positions.apply_plan(conn, empty_plan)
    assert second["orphans_superseded"] == 0
    assert second["inserted_spreads"] == 0

    # Statuses unchanged.
    rows = conn.execute(
        "SELECT status FROM trades WHERE id LIKE 'orphan%'"
    ).fetchall()
    assert all(r["status"] == "superseded" for r in rows)


def test_apply_plan_no_placeholders_no_supersede():
    """If there are no placeholder rows at all, supersede counter stays 0."""
    conn = _make_conn()
    stats = reconcile_positions.apply_plan(conn, _make_plan_with_one_spread())
    assert stats["inserted_spreads"] == 1
    assert stats["orphans_superseded"] == 0


def test_apply_plan_handles_null_metadata_on_placeholder():
    """Some legacy placeholder rows have NULL metadata — must not crash."""
    conn = _make_conn()
    conn.execute(
        "INSERT INTO trades (id, source, ticker, strategy_type, status, "
        "metadata, created_at, updated_at) VALUES "
        "('orphan_SPY260508P00689000', 'sentinel', 'SPY', 'unknown', "
        " 'unmanaged', NULL, datetime('now','-2 days'), "
        " datetime('now','-2 days'))"
    )
    conn.commit()

    stats = reconcile_positions.apply_plan(conn, _make_plan_with_one_spread())

    assert stats["orphans_superseded"] == 1
    row = conn.execute(
        "SELECT status, metadata FROM trades WHERE id = 'orphan_SPY260508P00689000'"
    ).fetchone()
    assert row["status"] == "superseded"
    meta = json.loads(row["metadata"])
    assert meta["superseded_by_reconcile"].startswith("alpaca_backfill_")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
