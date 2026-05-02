#!/usr/bin/env python3
"""Idempotent migration: add `excluded_from_metrics` and `exclusion_reason` to `trades`.

Per-experiment SQLite DB architecture means this migration must be applied to every
`data/pilotai_*.db` (and `data/exp*/pilotai_*.db`). Backup files (`*backup*`) are skipped.

The migration is idempotent — running it twice is a no-op. It checks for column existence
via `PRAGMA table_info` before issuing `ALTER TABLE`.

Usage:
    # Apply to a single DB (used by cc3 for EXP-1220):
    python scripts/migrate_excluded_from_metrics.py data/pilotai_exp1220.db

    # Apply to every per-experiment DB under data/ (skipping backups):
    python scripts/migrate_excluded_from_metrics.py --all

    # Dry-run (prints planned actions, makes no changes):
    python scripts/migrate_excluded_from_metrics.py --all --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

COLUMNS = [
    ("excluded_from_metrics", "INTEGER DEFAULT 0"),
    ("exclusion_reason", "TEXT"),
]
INDEX_NAME = "idx_trades_excluded_from_metrics"
INDEX_SQL = (
    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
    "ON trades (excluded_from_metrics) WHERE excluded_from_metrics = 1"
)


def find_dbs(data_dir: Path) -> list[Path]:
    """All per-experiment trade DBs, excluding backups."""
    return sorted(
        p for p in data_dir.glob("**/pilotai_*.db")
        if "backup" not in p.name
    )


def has_trades_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
    ).fetchone()
    return row is not None


def existing_columns(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(trades)")}


def migrate_one(db_path: Path, dry_run: bool = False) -> dict:
    """Apply migration to a single DB. Returns {'added': [...], 'skipped': [...], 'reason': str|None}."""
    result = {"db": str(db_path), "added": [], "skipped": [], "index": None, "reason": None}
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:  # pragma: no cover — surfaces unusable DBs
        result["reason"] = f"open failed: {exc}"
        return result

    try:
        if not has_trades_table(conn):
            result["reason"] = "no trades table"
            return result

        cols = existing_columns(conn)
        for name, ddl in COLUMNS:
            if name in cols:
                result["skipped"].append(name)
                continue
            stmt = f"ALTER TABLE trades ADD COLUMN {name} {ddl}"
            if dry_run:
                result["added"].append(f"(dry-run) {stmt}")
            else:
                conn.execute(stmt)
                result["added"].append(name)

        # Partial index — only flagged rows. Cheap; helps `WHERE excluded_from_metrics = 1` lookups
        # in audit / cleanup scripts. Idempotent via IF NOT EXISTS.
        if dry_run:
            result["index"] = f"(dry-run) {INDEX_SQL}"
        else:
            conn.execute(INDEX_SQL)
            result["index"] = INDEX_NAME

        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return result


def fmt(result: dict) -> str:
    db = result["db"]
    if result["reason"]:
        return f"  SKIP   {db}  ({result['reason']})"
    parts = []
    if result["added"]:
        parts.append("added " + ",".join(result["added"]))
    if result["skipped"]:
        parts.append("present " + ",".join(result["skipped"]))
    return f"  OK     {db}  [{'; '.join(parts) or 'no-op'}]"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "db",
        nargs="?",
        help="Path to a single .db file (omit and pass --all for bulk migration)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Apply to every pilotai_*.db under data/ (skipping *backup*)",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Override data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions, make no changes")
    args = parser.parse_args(argv)

    if not args.all and not args.db:
        parser.error("must pass a DB path or --all")
    if args.all and args.db:
        parser.error("--all and a DB path are mutually exclusive")

    if args.all:
        data_dir = Path(args.data_dir)
        if not data_dir.is_dir():
            print(f"data dir not found: {data_dir}", file=sys.stderr)
            return 2
        targets = find_dbs(data_dir)
    else:
        targets = [Path(args.db)]

    if not targets:
        print("no target DBs found", file=sys.stderr)
        return 2

    print(f"Migrating {len(targets)} DB(s){' (dry-run)' if args.dry_run else ''}:")
    n_changed = 0
    n_skipped = 0
    for db in targets:
        result = migrate_one(db, dry_run=args.dry_run)
        print(fmt(result))
        if result["reason"]:
            n_skipped += 1
        elif result["added"]:
            n_changed += 1

    print(f"\nDone. changed={n_changed} no-op={len(targets)-n_changed-n_skipped} skipped={n_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
