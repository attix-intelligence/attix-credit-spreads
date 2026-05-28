"""Backfill historical tilt signals for the MSR universe (MSR-200d).

Iterates trading dates in ``[--start, --end]``, runs the historical
tilt-signal orchestrator (``compass.signals._historical.build_tilt_for_date``)
against :class:`AthenaSignalDataProvider`, and writes one CSV per
date::

    data/signals/{YYYY-MM-DD}/tilt.csv

CSV (not Parquet) so the artefacts are human-inspectable with ``head``/
spreadsheets and we don't take a hard dep on pyarrow/fastparquet (which
aren't installed in this repo).

A JSONL run log at ``data/signals/run_log.jsonl`` captures per-date
stats (n_success, n_failed, athena_bytes_scanned, queries, elapsed_s)
so a partial run can be inspected without re-querying.

Resume semantics
----------------
By default the runner SKIPS dates whose ``tilt.parquet`` already exists.
Pass ``--overwrite`` to force recomputation.

Trading-day enumeration
-----------------------
We use SPY daily bars (via ``backtest.market_history.load_market_history``)
as the trading calendar — same convention as ``backtest.equity_backtester``.
Weekends / NYSE holidays drop out automatically.

Cost discipline
---------------
Athena bills per byte scanned. The 60-min option-candles partition is
keyed on year/month/day so a per-date query scans ~tens of MB per ticker.
The runner accumulates a running total and prints it after every date so
the operator can abort if costs balloon.

Dry-run
-------
``--dry-run`` walks the calendar, prints the date list and the per-date
skip decisions, and exits without issuing any Athena queries.

Rule Zero
---------
* No fabricated rows — every output row originates from a real Athena
  per-ticker computation (or a captured failure with error string).
* No look-ahead — each per-date query is partition-pruned to that day.
* The runner never silently catches Athena schema errors; only per-ticker
  signal exceptions are caught (and recorded as failed=True rows).
  Provider-level errors (boto3 / IAM / SQL syntax) bubble up and abort.

Usage::

    python3 scripts/msr200_build_signals.py \
        --start 2024-06-14 --end 2024-06-14 \
        --dry-run                                       # preview

    python3 scripts/msr200_build_signals.py \
        --start 2024-06-14 --end 2024-06-14             # 1-day pilot

    python3 scripts/msr200_build_signals.py \
        --start 2022-01-03 --end 2025-12-31             # full backfill
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

# ── .env bootstrap (mirrors scripts/athena_inventory.py) ─────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import pandas as pd  # noqa: E402

from compass.signals._historical import build_tilt_for_date  # noqa: E402
from compass.signals.athena_provider import AthenaSignalDataProvider  # noqa: E402
from strategies.msr_universe import load_universe  # noqa: E402

DEFAULT_OUT_DIR = ROOT / "data" / "signals"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("msr200_build_signals")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--start", required=True, help="Inclusive start date (YYYY-MM-DD).")
    p.add_argument("--end",   required=True, help="Inclusive end date (YYYY-MM-DD).")
    p.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR),
        help=f"Output root (default: {DEFAULT_OUT_DIR}).",
    )
    p.add_argument(
        "--universe", default=None,
        help="Path to msr_universe.yaml (default: strategies/msr_universe.yaml).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Enumerate trading dates and print skip decisions; issue no queries.",
    )
    p.add_argument(
        "--overwrite", action="store_true",
        help="Recompute even if data/signals/{date}/tilt.parquet exists.",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N trading dates (useful for cost pilots).",
    )
    p.add_argument(
        "--max-failures-per-day", type=int, default=None,
        help=(
            "Abort if a single date produces more than this many ticker "
            "failures. None = no cap (default)."
        ),
    )
    p.add_argument(
        "--benchmark", default="SPY",
        help="Ticker used to enumerate trading days (default: SPY).",
    )
    return p.parse_args(argv)


# ── Date enumeration ─────────────────────────────────────────────────────────

def _enumerate_trading_dates(
    start: date, end: date, benchmark: str = "SPY",
) -> List[date]:
    """Return the trading-day list in ``[start, end]`` per the benchmark's bars."""
    from backtest.market_history import load_market_history

    df = load_market_history(benchmark, start.isoformat(), end.isoformat())
    if df.empty:
        raise RuntimeError(
            f"No {benchmark} bars in [{start}, {end}] — cannot enumerate trading dates."
        )
    dates = [
        d.date() if hasattr(d, "date") else d
        for d in df.index
    ]
    return [d for d in dates if start <= d <= end]


def _parse_iso(s: str) -> date:
    return datetime.fromisoformat(s).date()


# ── Run-log JSONL ────────────────────────────────────────────────────────────

def _append_run_log(out_dir: Path, record: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run_log.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


# ── Per-date worker ──────────────────────────────────────────────────────────

def _process_date(
    as_of: date,
    universe,
    provider: AthenaSignalDataProvider,
    out_dir: Path,
    *,
    overwrite: bool,
    max_failures: Optional[int],
) -> dict:
    """Compute tilt for one date and write Parquet. Returns the run-log record."""
    date_dir = out_dir / as_of.isoformat()
    out_path = date_dir / "tilt.csv"

    if out_path.exists() and not overwrite:
        log.info("skip %s (exists; pass --overwrite to recompute)", as_of)
        return {
            "as_of": as_of.isoformat(),
            "status": "skipped_exists",
        }

    provider.reset_counters()
    t0 = time.monotonic()
    df = build_tilt_for_date(as_of, universe, provider)
    elapsed = time.monotonic() - t0

    n_success = int((~df["failed"]).sum())
    n_failed = int(df["failed"].sum())
    bytes_scanned = int(provider._bytes_scanned)
    queries = int(provider.queries_issued)

    if max_failures is not None and n_failed > max_failures:
        # Don't write a partial/bogus CSV — surface the problem.
        raise RuntimeError(
            f"{as_of}: {n_failed} ticker failures exceeds --max-failures-per-day "
            f"({max_failures}). Aborting to avoid persisting low-quality output."
        )

    date_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    try:
        display_path = out_path.relative_to(ROOT)
    except ValueError:
        display_path = out_path
    log.info(
        "wrote %s — %d success / %d failed — %d queries / %.1f MB / %.1fs",
        display_path,
        n_success, n_failed, queries, bytes_scanned / 1e6, elapsed,
    )

    return {
        "as_of": as_of.isoformat(),
        "status": "ok",
        "n_success": n_success,
        "n_failed": n_failed,
        "athena_queries": queries,
        "athena_bytes_scanned": bytes_scanned,
        "elapsed_s": round(elapsed, 2),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    start = _parse_iso(args.start)
    end = _parse_iso(args.end)
    if end < start:
        log.error("--end (%s) is before --start (%s)", end, start)
        return 2
    out_dir = Path(args.out_dir).resolve()

    log.info("loading universe …")
    universe = load_universe(args.universe) if args.universe else load_universe()
    log.info("universe: %d tickers (%d etfs / %d stocks)",
             len(universe), len(universe.etfs), len(universe.stocks))

    log.info("enumerating trading dates via %s bars …", args.benchmark)
    dates = _enumerate_trading_dates(start, end, args.benchmark)
    if args.limit is not None:
        dates = dates[: args.limit]
    log.info("trading dates in window: %d (first=%s, last=%s)",
             len(dates), dates[0] if dates else "—", dates[-1] if dates else "—")

    if not dates:
        log.warning("no trading dates — nothing to do")
        return 0

    if args.dry_run:
        print("\nDRY RUN — would process the following dates:")
        for d in dates:
            csv = out_dir / d.isoformat() / "tilt.csv"
            status = "SKIP (exists)" if csv.exists() and not args.overwrite else "RUN"
            print(f"  {d}  {status}")
        print(f"\nTotal: {len(dates)} dates, universe={len(universe)} tickers.")
        return 0

    log.info("provisioning AthenaSignalDataProvider …")
    provider = AthenaSignalDataProvider()
    log.info("  database=%s region=%s table=%s",
             provider.database, provider.region, provider.table)

    total_bytes = 0
    total_queries = 0
    total_success = 0
    total_failed = 0
    n_processed = 0

    t_start = time.monotonic()
    for d in dates:
        try:
            rec = _process_date(
                d, universe, provider, out_dir,
                overwrite=args.overwrite,
                max_failures=args.max_failures_per_day,
            )
        except KeyboardInterrupt:
            log.warning("interrupted by user at %s", d)
            return 130
        except Exception as e:  # provider-level / IO failure → log + re-raise
            log.exception("aborting at %s: %s", d, e)
            _append_run_log(out_dir, {
                "as_of": d.isoformat(),
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            })
            return 1

        _append_run_log(out_dir, rec)
        if rec.get("status") == "ok":
            total_bytes += rec["athena_bytes_scanned"]
            total_queries += rec["athena_queries"]
            total_success += rec["n_success"]
            total_failed += rec["n_failed"]
            n_processed += 1

    elapsed_total = time.monotonic() - t_start
    log.info(
        "DONE — %d dates processed (%d skipped) — totals: %d success / %d failed "
        "/ %d queries / %.1f MB scanned / %.1f min",
        n_processed, len(dates) - n_processed,
        total_success, total_failed, total_queries,
        total_bytes / 1e6, elapsed_total / 60.0,
    )
    # Athena us-east-1 price is $5/TB. ap-southeast-1 may differ — this is
    # a rough lower bound for the operator to sanity-check the run cost.
    est_cost = (total_bytes / 1e12) * 5.0
    log.info("Athena cost (rough @ $5/TB): $%.4f", est_cost)
    return 0


if __name__ == "__main__":
    sys.exit(main())
