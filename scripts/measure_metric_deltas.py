#!/usr/bin/env python3
"""Measure before/after Gate metric deltas across all per-experiment DBs.

Computes the rolling-30-trade Sharpe, win-rate, and total PnL for each
DB, both via the legacy raw `status LIKE 'closed%'` query and via the
new `metrics_eligible_cte` filter. Emits a markdown table for the PR
description.

This script reads only — no writes. Safe to run repeatedly.
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path
from statistics import mean, pstdev

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from metrics.eligible_trades import (
    _DENY_STATUSES_FOR_METRICS,
    _DENY_SOURCE_PATTERNS,
    _DENY_SOURCES_EXACT,
)


def find_dbs(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.glob("**/pilotai_*.db") if "backup" not in p.name)


def has_trades(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
    ).fetchone() is not None


def is_ineligible(row: dict) -> bool:
    """Mirror the metrics_eligible CTE deny-list, in Python."""
    tid = row.get("id") or ""
    src = (row.get("source") or "").lower()
    status = row.get("status") or ""

    if tid.startswith("orphan-") or tid.startswith("synthetic-"):
        return True
    if status in _DENY_STATUSES_FOR_METRICS:
        return True
    if src in (s.lower() for s in _DENY_SOURCES_EXACT):
        return True
    for pattern in _DENY_SOURCE_PATTERNS:
        needle = pattern.strip("%").lower()
        if needle in src:
            return True
    return False


def fetch_closed_rows(conn: sqlite3.Connection) -> list[dict]:
    """All closed rows, ordered most-recent-first by exit_date."""
    cur = conn.execute(
        "SELECT id, source, status, pnl, exit_date FROM trades "
        "WHERE status LIKE 'closed%' "
        "ORDER BY COALESCE(exit_date, created_at) DESC"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def stats(rows: list[dict], window: int = 30) -> dict:
    """Compute metric snapshot from a (chronologically newest-first) row list."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": None, "total_pnl": 0.0, "sharpe": None}

    pnls = [float(r["pnl"]) for r in rows if r.get("pnl") is not None]
    wins = sum(1 for p in pnls if p > 0)

    # Rolling-30 Sharpe — use window most recent
    head = pnls[:window]
    if len(head) >= 2 and pstdev(head) > 0:
        sharpe = mean(head) / pstdev(head) * math.sqrt(252)
    else:
        sharpe = None

    return {
        "n": n,
        "wins": wins,
        "win_rate": round(100 * wins / len(pnls), 2) if pnls else None,
        "total_pnl": round(sum(pnls), 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
    }


def main() -> int:
    data_dir = PROJECT_ROOT / "data"
    dbs = find_dbs(data_dir)
    rows_out = []

    for db in dbs:
        conn = sqlite3.connect(str(db))
        if not has_trades(conn):
            conn.close()
            continue
        all_closed = fetch_closed_rows(conn)
        conn.close()

        if not all_closed:
            continue

        eligible = [r for r in all_closed if not is_ineligible(r)]

        before = stats(all_closed)
        after = stats(eligible)
        leaked = before["n"] - after["n"]

        rows_out.append({
            "db": db.name,
            "leaked": leaked,
            "before": before,
            "after": after,
        })

    # Markdown table
    print("| Experiment | Closed (raw) | Closed (eligible) | Leaked | Win-rate before → after | Total PnL before → after | Rolling-30 Sharpe before → after |")
    print("|---|---:|---:|---:|---|---|---|")

    def fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "—"

    for r in rows_out:
        b, a = r["before"], r["after"]
        wr = f"{fmt(b['win_rate'], '%')} → {fmt(a['win_rate'], '%')}"
        pnl = f"${b['total_pnl']:.0f} → ${a['total_pnl']:.0f}"
        sh = f"{fmt(b['sharpe'])} → {fmt(a['sharpe'])}"
        print(f"| {r['db'].replace('pilotai_', '').replace('.db', '')} | {b['n']} | {a['n']} | {r['leaked']} | {wr} | {pnl} | {sh} |")

    total_raw = sum(r["before"]["n"] for r in rows_out)
    total_eligible = sum(r["after"]["n"] for r in rows_out)
    total_leaked = total_raw - total_eligible
    print(f"\n**Aggregate:** {total_leaked} of {total_raw} closed rows leaked ({100*total_leaked/total_raw:.1f}%) → {total_eligible} eligible after filter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
