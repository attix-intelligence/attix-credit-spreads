"""compass/live/vrp_returns_provider.py — persisted per-stream realized returns.

Replaces :class:`compass.live.vrp_stubs.StaticReturnsProvider` (whose TODO this
module discharges) so the Ledoit-Wolf risk-parity allocator in
:mod:`compass.live.vrp_risk_parity` actually advances out of cold-start mode and
learns the true cross-stream covariance.

DATA MODEL
----------
One row per ``(exp_id, stream, as_of_date)`` in the SQLite ``stream_equity_history``
table (see :func:`shared.database.init_db`). The schema is intentionally narrow:

  exp_id        TEXT  — e.g. ``"EXP-V8A"`` / ``"EXP-V8A-IBKR"``
  stream        TEXT  — one of :data:`compass.live.vrp_contracts.VRP_STREAMS`
  as_of_date    TEXT  — ``YYYY-MM-DD`` (UTC date the return was realized)
  daily_return  REAL  — the fraction the allocator consumes (PnL / equity_base)
  daily_pnl     REAL  — audit/backfill: the dollars realized that day
  equity_base   REAL  — the denominator used (account equity at start of day)
  source        TEXT  — ``"fills" | "monitor" | "backfill"``

PROVIDER
--------
:class:`PersistedReturnsProvider` satisfies :class:`compass.live.vrp_contracts.
ReturnsProvider` (``stream_returns(lookback) -> pd.DataFrame`` with date index +
stream columns). Missing data is returned as an *empty-rows* frame carrying the
requested stream columns — exactly the contract :mod:`vrp_risk_parity` expects
for cold-start prior mode (the same behaviour as the stub it replaces).

WRITER
------
:func:`record_stream_returns_for_day` upserts one row per stream at the end of
the trading day. The same writer powers the backfill (scripts/) — pre-VRP days
(2026-05-26 → 2026-05-29) get ``daily_return = 0.0`` because the 8 VRP streams
did not trade under the legacy champion clone; real values land from the first
VRP cycle onward.

PURE + ADDITIVE
---------------
No global state, no network. Read/write a SQLite DB through
:func:`shared.database.get_db` so the same ``ATTIX_DB_PATH`` plumbing applies.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date as date_cls
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Union

import pandas as pd

from shared.database import get_db, init_db

logger = logging.getLogger(__name__)

_DateLike = Union[str, date_cls]


def _as_date_str(d: _DateLike) -> str:
    if isinstance(d, date_cls):
        return d.isoformat()
    s = str(d).strip()
    # accept "YYYY-MM-DD" or anything pandas can parse — normalize to ISO date
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return pd.to_datetime(s, utc=True).date().isoformat()


class PersistedReturnsProvider:
    """ReturnsProvider backed by ``stream_equity_history`` (one row/stream/day).

    Parameters
    ----------
    exp_id:
        The experiment whose rows to read. Required — the table holds rows for
        every VRP experiment side-by-side (V8A + V8A-IBKR + future).
    stream_columns:
        The streams the caller wants in the returned frame. Columns missing from
        the DB are present in the frame with NaNs (which the allocator's
        ``_clean_returns`` then drops / treats as no-trade days).
    db_path:
        Optional explicit DB path; ``None`` uses :func:`shared.database.get_db_path`
        (the same path the worker writes to — respects ``ATTIX_DB_PATH``).
    """

    def __init__(
        self,
        exp_id: str,
        stream_columns: Sequence[str],
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        if not exp_id:
            raise ValueError("PersistedReturnsProvider requires a non-empty exp_id")
        if not stream_columns:
            raise ValueError("PersistedReturnsProvider requires at least one stream column")
        self._exp_id = str(exp_id)
        self._columns = list(stream_columns)
        self._db_path = str(db_path) if db_path is not None else None

    # The ReturnsProvider Protocol (vrp_contracts.py:184).
    def stream_returns(self, lookback: int = 252) -> pd.DataFrame:
        """Most recent ``lookback`` trading days as a date-indexed wide frame.

        Returns ``pd.DataFrame(columns=self._columns)`` (empty) when the table
        has no rows for this experiment — equivalent to the stub's cold-start
        behaviour. Never raises on data quality issues; logs and falls back.
        """
        lookback = max(1, int(lookback))
        try:
            conn = get_db(self._db_path) if self._db_path else get_db()
        except Exception as exc:  # noqa: BLE001 — never break the allocator
            logger.warning("[vrp_returns_provider] get_db failed: %s — empty frame", exc)
            return pd.DataFrame(columns=self._columns)

        try:
            # Ensure the table exists (a freshly-bootstrapped DB may not have it yet).
            try:
                init_db(self._db_path) if self._db_path else init_db()
            except Exception:
                # init_db is best-effort here; if it fails the query below will too,
                # caught and returned as empty.
                pass

            placeholders = ",".join("?" * len(self._columns))
            # Pull only the recent lookback dates we care about — sorted DESC then
            # pivoted. We deliberately fetch by date over LIMIT(lookback × n_streams)
            # so a stream missing some days does not displace another stream's row.
            sql = f"""
                SELECT as_of_date, stream, daily_return
                FROM stream_equity_history
                WHERE exp_id = ?
                  AND stream IN ({placeholders})
                  AND as_of_date >= (
                      SELECT MIN(as_of_date) FROM (
                          SELECT DISTINCT as_of_date FROM stream_equity_history
                          WHERE exp_id = ? AND stream IN ({placeholders})
                          ORDER BY as_of_date DESC LIMIT ?
                      )
                  )
                ORDER BY as_of_date ASC
            """
            cur = conn.execute(
                sql,
                [self._exp_id, *self._columns,
                 self._exp_id, *self._columns, lookback],
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            logger.warning("[vrp_returns_provider] query failed: %s — empty frame", exc)
            return pd.DataFrame(columns=self._columns)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not rows:
            return pd.DataFrame(columns=self._columns)

        long = pd.DataFrame(rows, columns=["as_of_date", "stream", "daily_return"])
        long["daily_return"] = pd.to_numeric(long["daily_return"], errors="coerce")
        long["as_of_date"] = pd.to_datetime(long["as_of_date"], errors="coerce", utc=True).dt.tz_localize(None)
        long = long.dropna(subset=["as_of_date"])
        if long.empty:
            return pd.DataFrame(columns=self._columns)

        wide = (
            long.pivot_table(
                index="as_of_date", columns="stream", values="daily_return", aggfunc="last"
            )
            .reindex(columns=self._columns)
            .sort_index()
        )
        wide.index.name = None
        return wide

    # ── introspection (used by the runner / tests) ────────────────────────────
    @property
    def exp_id(self) -> str:
        return self._exp_id

    @property
    def stream_columns(self) -> Sequence[str]:
        return tuple(self._columns)


# ─────────────────────────────────────────────────────────────────────────────
# Writer / backfill helpers
# ─────────────────────────────────────────────────────────────────────────────

def record_stream_returns_for_day(
    exp_id: str,
    as_of_date: _DateLike,
    per_stream_pnl: Mapping[str, float],
    equity_base: float,
    *,
    source: str = "monitor",
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Upsert one row per stream for ``as_of_date``.

    Parameters
    ----------
    exp_id:
        e.g. ``"EXP-V8A"``.
    as_of_date:
        Trading date (str ``YYYY-MM-DD`` or :class:`datetime.date`).
    per_stream_pnl:
        ``{stream_id: realized_dollars_today}``. Streams absent from this mapping
        are not written this day (they remain NaN, which the allocator treats as
        "no trade").
    equity_base:
        Denominator for the daily return (the account equity at start of day,
        or another stable basis). If ``≤ 0``, all returns are written as 0.0.
    source:
        ``"fills" | "monitor" | "backfill"`` — audit tag.
    db_path:
        Optional explicit DB; ``None`` uses ``ATTIX_DB_PATH``.

    Returns the number of rows upserted.
    """
    as_of = _as_date_str(as_of_date)
    base = float(equity_base) if equity_base is not None else 0.0
    if not per_stream_pnl:
        return 0
    rows = []
    for stream, pnl in per_stream_pnl.items():
        try:
            pnl_f = float(pnl)
        except (TypeError, ValueError):
            continue
        ret = (pnl_f / base) if base > 0 else 0.0
        rows.append((exp_id, str(stream), as_of, float(ret), pnl_f, base, source))
    if not rows:
        return 0

    # Idempotent table creation (safe on a fresh DB without the migration applied).
    init_db(db_path) if db_path else init_db()
    conn = get_db(db_path) if db_path else get_db()
    try:
        conn.executemany(
            """
            INSERT INTO stream_equity_history
                (exp_id, stream, as_of_date, daily_return, daily_pnl, equity_base, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exp_id, stream, as_of_date) DO UPDATE SET
                daily_return = excluded.daily_return,
                daily_pnl    = excluded.daily_pnl,
                equity_base  = excluded.equity_base,
                source       = excluded.source,
                updated_at   = datetime('now')
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("[vrp_returns_provider] wrote %d stream row(s) for %s @ %s (source=%s)",
                len(rows), exp_id, as_of, source)
    return len(rows)


def backfill_zero_rows(
    exp_id: str,
    streams: Iterable[str],
    dates: Iterable[_DateLike],
    *,
    equity_base: float = 0.0,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Convenience for the backfill script: write 0.0 returns for the cartesian
    product of ``streams × dates``. Used for V8A's pre-VRP days (champion clone
    era) where the 8 VRP streams did not trade — the rows must exist so the
    allocator counts those days as "no-trade" rather than missing the date entirely.

    Returns the total row count written.
    """
    streams = list(streams)
    n = 0
    for d in dates:
        per_stream = {s: 0.0 for s in streams}
        n += record_stream_returns_for_day(
            exp_id, d, per_stream, equity_base, source="backfill", db_path=db_path
        )
    return n
