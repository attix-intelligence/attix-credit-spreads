#!/usr/bin/env python3
"""Print the top-N dark-flow tickers from the most recent TradeAlgo snapshot.

Reads ``data/tradealgo/{snapshot_date}/snapshot.json`` if available;
otherwise (with ``--fetch``) calls the live API. Designed for ad-hoc
inspection and as the verification step requested by Carlos after wiring
the integration.

Usage::

    python3 scripts/tradealgo_daily_demo.py                       # most recent cache
    python3 scripts/tradealgo_daily_demo.py --date 2026-05-27     # specific date
    python3 scripts/tradealgo_daily_demo.py --fetch               # force network fetch
    python3 scripts/tradealgo_daily_demo.py -n 20 --side down     # 20 trending_down

No flags, no live network = safe to run any time. The ``--fetch`` path
requires ``TRADEALGO_API_KEY`` in the environment.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.tradealgo_client import TradeAlgoClient
from shared.tradealgo_darkflow import (
    darkflow_zscores,
    parse_movement_darkflow,
    top_darkflow,
)


def _most_recent_cached() -> date | None:
    cache = ROOT / "data" / "tradealgo"
    if not cache.exists():
        return None
    candidates = []
    for d in cache.iterdir():
        if d.is_dir() and (d / "snapshot.json").exists():
            try:
                candidates.append(date.fromisoformat(d.name))
            except ValueError:
                continue
    return max(candidates) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="snapshot date YYYY-MM-DD")
    parser.add_argument("--fetch", action="store_true",
                        help="fetch live from API instead of cache")
    parser.add_argument("-n", type=int, default=10, help="top-N (default 10)")
    parser.add_argument("--side", choices=["up", "down", "both"], default="up")
    parser.add_argument("--sort-by", choices=["dollar_value", "multiplier", "perf"],
                        default="dollar_value")
    args = parser.parse_args()

    if args.fetch:
        client = TradeAlgoClient()
        snap = client.fetch_snapshot(force_refresh=True)
        when = "(live fetch)"
    else:
        target = (date.fromisoformat(args.date) if args.date
                  else _most_recent_cached())
        if target is None:
            print("No cached snapshots in data/tradealgo/. Use --fetch.",
                  file=sys.stderr)
            return 2
        snap = TradeAlgoClient.from_cache(target)
        when = target.isoformat()

    records = parse_movement_darkflow(snap)
    if not records:
        print(f"snapshot {when} has no movement/darkflow data", file=sys.stderr)
        return 1

    zs = darkflow_zscores(records)

    side_filter = None if args.side == "both" else args.side
    top = top_darkflow(records, n=args.n, side=side_filter, sort_by=args.sort_by)

    print(f"TradeAlgo Daily Snapshot — {when}")
    print(f"  movement/ records: {len(records)}  (parsed across 3 cap buckets)")
    print(f"  top {args.n} by {args.sort_by} — side={args.side}")
    print()
    print(f"  {'#':>2}  {'Ticker':<6}  {'Cap':<6}  {'Side':<4}  "
          f"{'Mult':>5}  {'Dollar Vol':>16}  {'Sentiment':>9}  "
          f"{'ATS % avg':>9}  {'Perf %':>7}  {'DarkflowZ':>9}")
    print("  " + "-" * 99)
    for i, r in enumerate(top, 1):
        z = zs.get(r.ticker)
        z_str = f"{z:+.3f}" if z is not None else "  —  "
        fs = f"{r.flow_sentiment:.3f}" if r.flow_sentiment is not None else "  —  "
        ats = f"{r.ats_dollar_volume_pct:.1f}" if r.ats_dollar_volume_pct is not None else "  —  "
        perf = f"{r.perf:+.2f}" if r.perf is not None else "  —  "
        print(f"  {i:>2}  {r.ticker:<6}  {r.cap_bucket:<6}  {r.side:<4}  "
              f"{r.multiplier:>5.2f}  ${r.dollar_value:>15,.0f}  {fs:>9}  "
              f"{ats:>9}  {perf:>7}  {z_str:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
