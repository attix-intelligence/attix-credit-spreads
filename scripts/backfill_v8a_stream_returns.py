#!/usr/bin/env python3
"""scripts/backfill_v8a_stream_returns.py — seed stream_equity_history for V8A.

The Ledoit-Wolf risk-parity allocator in :mod:`compass.live.vrp_risk_parity`
exits cold-start mode when ``usable_days >= MIN_LIVE_DAYS (60)``. Without rows
in ``stream_equity_history`` it would stay in pure-prior mode forever.

This script seeds the table from V8A's launch date (2026-05-26) through the day
BEFORE the first live VRP cycle, writing **zero-valued rows** for every (stream,
date) combination. That's the honest historical truth: the 8 VRP streams did
not trade under the legacy champion-clone path; the only activity those days
was the SPY 735/723 bull put that was flushed on 2026-05-29 (and that fill was
champion, not a VRP stream). The rows are needed so the allocator's
``usable_days`` counter advances — without them the date axis is empty and
``cold_start_covariance`` reports ``days=0 → prior mode`` indefinitely.

Real per-stream returns are written by the EOD path going forward (see
:func:`compass.live.vrp_returns_provider.record_stream_returns_for_day`).

Idempotent: re-running overwrites the same rows (``PRIMARY KEY (exp_id, stream,
as_of_date)`` + ``ON CONFLICT DO UPDATE``). Safe to schedule.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List

# Allow running from anywhere — make the repo importable.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from compass.live.vrp_contracts import STREAM_SPECS, StreamStatus  # noqa: E402
from compass.live.vrp_returns_provider import backfill_zero_rows  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")

# V8A launched 2026-05-26 (per experiments/registry.json).
V8A_LAUNCH = date(2026, 5, 26)


def _trading_days(start: date, end: date) -> List[date]:
    """Mon–Fri dates in ``[start, end]`` (NYSE holidays close enough — duplicate
    rows on holidays just write a zero and don't affect the allocator, since the
    LW math weights all rows equally regardless of holiday status)."""
    out: List[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--exp-id", default="EXP-V8A", help="experiment id (default: EXP-V8A)")
    p.add_argument("--start", default=V8A_LAUNCH.isoformat(),
                   help=f"start date YYYY-MM-DD (default: {V8A_LAUNCH.isoformat()} — V8A launch)")
    p.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat(),
                   help="end date YYYY-MM-DD (inclusive; default: yesterday)")
    p.add_argument("--db-path", default=os.environ.get("ATTIX_DB_PATH"),
                   help="explicit SQLite path (default: ATTIX_DB_PATH env)")
    p.add_argument("--streams", default="active",
                   help="'active' (TRADEABLE today) | 'all' | comma-separated list")
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        log.error("end (%s) < start (%s) — nothing to do", end, start)
        return 1

    if args.streams == "active":
        streams = [s for s, spec in STREAM_SPECS.items() if spec.status is StreamStatus.TRADEABLE]
    elif args.streams == "all":
        streams = list(STREAM_SPECS.keys())
    else:
        streams = [s.strip() for s in args.streams.split(",") if s.strip()]

    if not streams:
        log.error("no streams resolved")
        return 1

    dates = _trading_days(start, end)
    if not dates:
        log.info("no trading days in [%s, %s] — done", start, end)
        return 0

    log.info("backfilling %d stream(s) × %d date(s) = %d zero-rows for %s into %s",
             len(streams), len(dates), len(streams) * len(dates),
             args.exp_id, args.db_path or "<ATTIX_DB_PATH default>")
    n = backfill_zero_rows(args.exp_id, streams, dates, equity_base=0.0, db_path=args.db_path)
    log.info("wrote %d row(s).", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
