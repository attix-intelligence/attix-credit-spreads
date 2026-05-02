"""Unit tests for the metrics eligibility helpers.

Each test inserts a small fixture into an in-memory SQLite DB and verifies that
each clause of the deny-list does what it claims.
"""
from __future__ import annotations

import sqlite3

import pytest

from metrics import (
    ELIGIBLE_CTE_NAME,
    OPEN_CTE_NAME,
    metrics_eligible_cte,
    open_eligible_cte,
)


# Match the production schema (columns the helpers reference plus a few neighbours).
SCHEMA = """
CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    source TEXT,
    status TEXT,
    pnl REAL,
    excluded_from_metrics INTEGER DEFAULT 0,
    exclusion_reason TEXT
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _insert(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO trades (id, source, status, pnl, excluded_from_metrics, exclusion_reason) "
        "VALUES (:id, :source, :status, :pnl, :excluded_from_metrics, :exclusion_reason)",
        [
            {
                "id": r["id"],
                "source": r.get("source"),
                "status": r.get("status"),
                "pnl": r.get("pnl"),
                "excluded_from_metrics": r.get("excluded_from_metrics", 0),
                "exclusion_reason": r.get("exclusion_reason"),
            }
            for r in rows
        ],
    )
    conn.commit()


def _eligible_ids(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(metrics_eligible_cte() + f"SELECT id FROM {ELIGIBLE_CTE_NAME}")
    return {r["id"] for r in cur.fetchall()}


def _open_ids(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(open_eligible_cte() + f"SELECT id FROM {OPEN_CTE_NAME}")
    return {r["id"] for r in cur.fetchall()}


# --- metrics_eligible_cte ----------------------------------------------------


def test_legitimate_closed_trade_included():
    conn = _conn()
    _insert(conn, [{"id": "t1", "source": "execution", "status": "closed_profit", "pnl": 12.0}])
    assert _eligible_ids(conn) == {"t1"}


def test_excluded_from_metrics_flag_filters_row():
    conn = _conn()
    _insert(conn, [
        {"id": "t1", "source": "execution", "status": "closed_profit",
         "excluded_from_metrics": 1, "exclusion_reason": "manual"},
        {"id": "t2", "source": "execution", "status": "closed_profit"},
    ])
    assert _eligible_ids(conn) == {"t2"}


def test_orphan_id_filtered():
    conn = _conn()
    _insert(conn, [
        {"id": "orphan-abc", "source": "reconciler", "status": "closed_profit"},
        {"id": "synthetic-xyz", "source": "reconciler", "status": "closed_profit"},
        {"id": "real-1", "source": "execution", "status": "closed_profit"},
    ])
    assert _eligible_ids(conn) == {"real-1"}


@pytest.mark.parametrize("source", [
    "alpaca_backfill_2026-05-01",  # the EXP-1220 incident value
    "manual_backfill",
    "recovery_2025",
    "alpaca_recovered",  # contains 'recovery' substring? — actually 'recovered' lacks 'recovery'
])
def test_source_pattern_excludes_backfill_and_recovery(source):
    conn = _conn()
    _insert(conn, [{"id": source, "source": source, "status": "closed_profit"}])
    if "backfill" in source or "placeholder" in source or "recovery" in source:
        assert _eligible_ids(conn) == set(), f"expected {source} excluded"
    else:
        assert _eligible_ids(conn) == {source}, f"expected {source} included"


def test_source_pattern_includes_legitimate_recovered_when_no_recovery_substring():
    """`alpaca_recovered` should be evaluated by the substring rule. The current
    deny-list uses '%recovery%' — `recovered` does NOT match `recovery%`. This
    test pins that behaviour: if intent ever changes to also match `recovered`,
    update the deny-list explicitly."""
    conn = _conn()
    _insert(conn, [{"id": "r1", "source": "alpaca_recovered", "status": "open"}])
    # 'recovered' does not match LIKE '%recovery%', so the row is eligible.
    assert _eligible_ids(conn) == {"r1"}


def test_register_orphan_v3_source_excluded():
    conn = _conn()
    _insert(conn, [{"id": "t1", "source": "register_orphan_v3", "status": "closed_pre_reset"}])
    assert _eligible_ids(conn) == set()


@pytest.mark.parametrize("status", [
    "unmanaged",
    "failed_open",
    "closed_pre_reset",
    "superseded_by_recovery",
    "needs_investigation",
    "pending_open",
    "pending_close",
])
def test_deny_status_filtered(status):
    conn = _conn()
    _insert(conn, [{"id": "t1", "source": "execution", "status": status}])
    assert _eligible_ids(conn) == set()


@pytest.mark.parametrize("status", [
    "open",
    "closed",
    "closed_profit",
    "closed_loss",
    "closed_manual",
    "closed_external",
    "closed_expired",
    "expired",
])
def test_realized_status_kept(status):
    conn = _conn()
    _insert(conn, [{"id": "t1", "source": "execution", "status": status}])
    assert _eligible_ids(conn) == {"t1"}


def test_null_source_does_not_crash_and_is_included():
    """COALESCE wraps source so NULL doesn't false-trigger LIKE checks."""
    conn = _conn()
    _insert(conn, [{"id": "t1", "source": None, "status": "closed_profit"}])
    assert _eligible_ids(conn) == {"t1"}


def test_realistic_exp1220_scenario():
    """Mirror the audit's exp1220 by-source-status breakdown — confirm the
    helper would have prevented the metric leak."""
    conn = _conn()
    rows = []
    # 26 closed_pre_reset (reconciler) — leak
    rows += [{"id": f"prer-r-{i}", "source": "reconciler", "status": "closed_pre_reset"} for i in range(26)]
    # 25 closed_pre_reset (execution) — leak
    rows += [{"id": f"prer-e-{i}", "source": "execution", "status": "closed_pre_reset"} for i in range(25)]
    # 8 unmanaged — leak
    rows += [{"id": f"unm-{i}", "source": "sentinel", "status": "unmanaged"} for i in range(8)]
    # 2 alpaca_backfill_2026-05-01 — leak (the EXP-1220 incident)
    rows += [{"id": f"bf-{i}", "source": "alpaca_backfill_2026-05-01", "status": "open"} for i in range(2)]
    # 2 legitimate open — keep
    rows += [{"id": f"open-{i}", "source": "execution", "status": "open"} for i in range(2)]
    # 1 closed_profit — keep
    rows += [{"id": "win-1", "source": "execution", "status": "closed_profit", "pnl": 50}]
    # 1 needs_investigation — leak
    rows += [{"id": "inv-1", "source": "execution", "status": "needs_investigation"}]
    _insert(conn, rows)

    eligible = _eligible_ids(conn)
    # Only the 2 legitimate opens + 1 closed_profit survive.
    assert eligible == {"open-0", "open-1", "win-1"}
    assert len(eligible) == 3, f"expected 3 eligible of 65 total, got {len(eligible)}"


def test_status_like_closed_pattern_no_longer_leaks_pre_reset():
    """Reproduce sentinel/runtime.py:229 query semantics on top of the helper.
    Confirms the dispatch's stated bug is fixed."""
    conn = _conn()
    _insert(conn, [
        {"id": "real-close", "source": "execution", "status": "closed_profit", "pnl": 10},
        {"id": "preset-1", "source": "reconciler", "status": "closed_pre_reset", "pnl": None},
        {"id": "preset-2", "source": "execution", "status": "closed_pre_reset", "pnl": None},
    ])
    sql = metrics_eligible_cte() + (
        f"SELECT COUNT(*) FROM {ELIGIBLE_CTE_NAME} WHERE status LIKE 'closed%'"
    )
    assert conn.execute(sql).fetchone()[0] == 1


# --- open_eligible_cte -------------------------------------------------------


def test_open_cte_includes_open_and_pending():
    conn = _conn()
    _insert(conn, [
        {"id": "o1", "status": "open", "source": "execution"},
        {"id": "po1", "status": "pending_open", "source": "execution"},
        {"id": "pc1", "status": "pending_close", "source": "execution"},
        {"id": "c1", "status": "closed_profit", "source": "execution"},
    ])
    assert _open_ids(conn) == {"o1", "po1", "pc1"}


def test_open_cte_excludes_orphan_synthetic_and_excluded_flag():
    conn = _conn()
    _insert(conn, [
        {"id": "orphan-1", "status": "open", "source": "execution"},
        {"id": "synthetic-1", "status": "open", "source": "execution"},
        {"id": "flagged-1", "status": "open", "source": "execution",
         "excluded_from_metrics": 1, "exclusion_reason": "manual"},
        {"id": "good-1", "status": "open", "source": "execution"},
    ])
    assert _open_ids(conn) == {"good-1"}


def test_open_cte_excludes_unmanaged_and_failed_open():
    """These statuses are *real* open in the schema but we exclude them as
    metric-irrelevant orphan/error rows even for live-position counts."""
    conn = _conn()
    _insert(conn, [
        {"id": "unm-1", "status": "unmanaged", "source": "reconciler"},
        {"id": "fail-1", "status": "failed_open", "source": "execution"},
        {"id": "good-1", "status": "open", "source": "execution"},
    ])
    # `unmanaged` and `failed_open` are NOT in the open-status whitelist, so excluded.
    assert _open_ids(conn) == {"good-1"}


def test_helper_works_when_excluded_from_metrics_column_absent():
    """Pre-migration DBs lack the column. The helper's COALESCE handles NULL by
    treating absent value as 0 (= included). But the column being missing
    entirely will still fail at the SQL parser. This test pins that the helper
    ASSUMES the migration has been applied."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE trades (id TEXT PRIMARY KEY, source TEXT, status TEXT, pnl REAL);"
    )
    conn.execute(
        "INSERT INTO trades (id, source, status) VALUES ('t1', 'execution', 'closed_profit')"
    )
    with pytest.raises(sqlite3.OperationalError, match="excluded_from_metrics"):
        conn.execute(metrics_eligible_cte() + f"SELECT * FROM {ELIGIBLE_CTE_NAME}")
