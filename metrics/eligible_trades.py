"""Single source of truth for what counts as a metric-eligible trade.

Why this module exists
----------------------
Gate calculations (Sharpe, win-rate, trade count, drawdown) historically queried
the raw ``trades`` table directly. Filtering was ad-hoc per call site. Twice now
(EXP-1220 backfill placeholders; the systemic ``closed_pre_reset`` leak surfaced
by the 2026-05-02 audit) non-real rows have leaked into Gate metrics. See
``docs/metrics_data_pipeline.md``.

This module owns the deny-list. Gate code goes through these helpers; raw
``FROM trades`` references are blocked by ``scripts/lint_no_raw_trades.py``.

Two distinct concepts
---------------------
``metrics_eligible_cte()``  — for trade-count / Sharpe / win-rate / PnL aggregates.
                              Excludes placeholders, recovery rows, ``closed_pre_reset``,
                              ``unmanaged``, ``failed_open``, ``needs_investigation``,
                              and the manual ``excluded_from_metrics`` flag.

``open_eligible_cte()``     — for concentration / OCC reconciliation gates.
                              Includes ``open`` and ``pending_*`` (real positions)
                              but still excludes orphan / synthetic / manually-excluded
                              rows.

Architecture: per-experiment SQLite DBs (``data/pilotai_expNNN.db``) make a single
SQL view useless. CTE-based helpers give one source of truth in code with no
per-DB DDL maintenance.
"""
from __future__ import annotations

# CTE names — kept stable so call sites read naturally. Treat as public API.
ELIGIBLE_CTE_NAME = "metrics_eligible_trades"
OPEN_CTE_NAME = "open_eligible_trades"

# Status values that should NEVER count as realized/closed trade metrics.
# Derived from the 2026-05-02 audit (see reports/metrics-leakage-audit-2026-05-02.html).
_DENY_STATUSES_FOR_METRICS: tuple[str, ...] = (
    "unmanaged",                 # orphan reconciler entries
    "failed_open",               # order rejected — no fill
    "closed_pre_reset",          # pre-reset placeholder, not a real close
    "superseded_by_recovery",    # replaced by an alpaca-recovered row
    "needs_investigation",       # manual review queue
    "pending_open",              # bookkeeping only
    "pending_close",             # bookkeeping only
)

# `source` substrings that mark non-real-fill rows.
_DENY_SOURCE_PATTERNS: tuple[str, ...] = ("%backfill%", "%placeholder%", "%recovery%")

# Exact `source` values that mark non-real-fill rows.
_DENY_SOURCES_EXACT: tuple[str, ...] = ("register_orphan_v3",)

# Status values that count as live positions (open-position gates).
_OPEN_STATUSES: tuple[str, ...] = ("open", "pending_open", "pending_close")


def _quote_sql_string(s: str) -> str:
    """Defensive single-quote escaping for SQL string literals.

    Inputs to this function are constants in this module — never user data — but
    we still escape to keep the generated SQL safe to inline if the constants
    are ever extended.
    """
    return "'" + s.replace("'", "''") + "'"


def _eligible_predicate() -> str:
    """The shared row-level predicate, returned as a SQL boolean expression.

    Used by both CTEs as the orphan/synthetic/explicit-exclusion floor.
    """
    return (
        "COALESCE(excluded_from_metrics, 0) = 0\n"
        "    AND id NOT LIKE 'orphan-%'\n"
        "    AND id NOT LIKE 'synthetic-%'"
    )


def _source_clauses() -> str:
    src_pat = " AND ".join(
        f"COALESCE(source, '') NOT LIKE {_quote_sql_string(p)}"
        for p in _DENY_SOURCE_PATTERNS
    )
    src_exact = " AND ".join(
        f"COALESCE(source, '') != {_quote_sql_string(s)}"
        for s in _DENY_SOURCES_EXACT
    )
    return f"{src_pat}\n    AND {src_exact}"


def metrics_eligible_cte() -> str:
    """SQL CTE definition that filters ``trades`` to metric-eligible rows.

    Prefix this to any SELECT, then ``FROM metrics_eligible_trades`` (or whatever
    ``ELIGIBLE_CTE_NAME`` is). Example::

        from metrics import metrics_eligible_cte, ELIGIBLE_CTE_NAME

        sql = metrics_eligible_cte() + f'''
            SELECT COUNT(*), SUM(pnl)
            FROM {ELIGIBLE_CTE_NAME}
            WHERE status LIKE 'closed%'
        '''
        cur = conn.execute(sql)

    Returns the CTE definition with a trailing newline; the caller appends the
    main SELECT.
    """
    statuses = ", ".join(_quote_sql_string(s) for s in _DENY_STATUSES_FOR_METRICS)
    return (
        f"WITH {ELIGIBLE_CTE_NAME} AS (\n"
        f"  SELECT * FROM trades\n"
        f"  WHERE {_eligible_predicate()}\n"
        f"    AND {_source_clauses()}\n"
        f"    AND status NOT IN ({statuses})\n"
        f")\n"
    )


def open_eligible_cte() -> str:
    """SQL CTE for live-position gates (concentration, OCC reconciliation).

    Includes ``open / pending_open / pending_close``; still excludes orphan /
    synthetic / explicitly-excluded rows. Example::

        from metrics import open_eligible_cte, OPEN_CTE_NAME

        sql = open_eligible_cte() + f'''
            SELECT id, ticker, contracts FROM {OPEN_CTE_NAME}
        '''
        cur = conn.execute(sql)
    """
    open_statuses = ", ".join(_quote_sql_string(s) for s in _OPEN_STATUSES)
    return (
        f"WITH {OPEN_CTE_NAME} AS (\n"
        f"  SELECT * FROM trades\n"
        f"  WHERE {_eligible_predicate()}\n"
        f"    AND status IN ({open_statuses})\n"
        f")\n"
    )
