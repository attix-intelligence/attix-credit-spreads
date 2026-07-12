#!/usr/bin/env python3
"""PROG-0 post-backfill integrity check (EXP-3570 protocol closing step).

For each ticker touched by the PROG-0 jobs:
  1. after-counts (contracts, bars, date span) vs the recorded before-counts;
  2. probe cross-check: N random NEWLY-inserted bars re-fetched from Polygon
     and compared field-by-field (idempotency + transcription check);
  3. sanity: no bar dated after its contract's expiration + 1 trading day;
     per-year bar density printed for eyeballing gaps;
  4. verifies the pre-write backup still exists and the total row count only
     grew (INSERT OR IGNORE can never shrink or mutate existing rows).

Usage: .venv/bin/python experiments/PROG0-data-backfill/integrity_check.py
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "options_cache.db"
BAK = ROOT / "data" / "options_cache.db.bak-prog0"

BEFORE = {  # recorded 2026-07-12 pre-write (see reports/PROG0_DATA_BACKFILL.md)
    "SLV": {"contracts": 0, "bars": 0},
    "QQQ": {"contracts": 23022, "bars": 779955},
    "GLD": {"contracts": 14738, "bars": 190133},
    "TLT": {"contracts": 10749, "bars": 293500},
    "_total_daily": 6397396,
    "_total_contracts": 280709,
}
PROBES_PER_TICKER = 4
AS_OF = "2026-07-12"


def key() -> str:
    for line in open(ROOT / ".env"):
        line = line.strip()
        if line.startswith("POLYGON_API_KEY") and "=" in line:
            return line.partition("=")[2].strip().strip('"')
    sys.exit("no POLYGON_API_KEY")


KEY = key()


def api_bar(sym: str, day: str) -> dict | None:
    url = (f"https://api.polygon.io/v2/aggs/ticker/{urllib.parse.quote(sym)}"
           f"/range/1/day/{day}/{day}?adjusted=true&apiKey={KEY}")
    with urllib.request.urlopen(url, timeout=45) as r:
        d = json.load(r)
    rs = d.get("results") or []
    return rs[0] if rs else None


def main() -> None:
    rng = random.Random(20260712)
    assert BAK.exists(), "FATAL: pre-write backup missing"
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    total_d = conn.execute("select count(*) from option_daily").fetchone()[0]
    total_c = conn.execute("select count(*) from option_contracts").fetchone()[0]
    assert total_d >= BEFORE["_total_daily"], "option_daily shrank!"
    assert total_c >= BEFORE["_total_contracts"], "option_contracts shrank!"
    print(f"[totals] option_daily {BEFORE['_total_daily']} -> {total_d} "
          f"(+{total_d - BEFORE['_total_daily']}); option_contracts "
          f"{BEFORE['_total_contracts']} -> {total_c} (+{total_c - BEFORE['_total_contracts']})")

    failures = 0
    for t in ("SLV", "QQQ", "GLD", "TLT"):
        nc = conn.execute("select count(*) from option_contracts where ticker=?", (t,)).fetchone()[0]
        nb, lo, hi = conn.execute(
            "select count(*), min(od.date), max(od.date) from option_daily od "
            "join option_contracts oc using(contract_symbol) where oc.ticker=?",
            (t,)).fetchone()
        b = BEFORE[t]
        print(f"[{t}] contracts {b['contracts']} -> {nc} (+{nc - b['contracts']}); "
              f"bars {b['bars']} -> {nb} (+{nb - b['bars']}); span {lo}..{hi}")

        # per-year density (new-era rows only, eyeball check)
        dens = conn.execute(
            "select substr(od.date,1,4) y, count(*) from option_daily od "
            "join option_contracts oc using(contract_symbol) "
            "where oc.ticker=? and oc.as_of_date=? group by y order by y",
            (t, AS_OF)).fetchall()
        if dens:
            print(f"   new-row density by year: {dict(dens)}")

        # expiry sanity on new rows: no bar later than expiration + 1 day
        n_bad = conn.execute(
            "select count(*) from option_daily od join option_contracts oc "
            "using(contract_symbol) where oc.ticker=? and oc.as_of_date=? "
            "and od.date > date(oc.expiration, '+1 day')", (t, AS_OF)).fetchone()[0]
        if n_bad:
            print(f"   FAIL: {n_bad} bars dated after expiration+1d")
            failures += 1

        # probe cross-check on new rows
        rows = conn.execute(
            "select od.contract_symbol, od.date, od.open, od.high, od.low, od.close, od.volume "
            "from option_daily od join option_contracts oc using(contract_symbol) "
            "where oc.ticker=? and oc.as_of_date=? and od.close is not null "
            "order by od.contract_symbol, od.date", (t, AS_OF)).fetchall()
        if not rows:
            print(f"   (no new rows for {t} — nothing to probe)")
            continue
        for sym, day, o, h, l, c, v in rng.sample(rows, min(PROBES_PER_TICKER, len(rows))):
            m = api_bar(sym, day)
            time.sleep(0.25)
            if m is None:
                print(f"   PROBE FAIL {sym} {day}: API returned no bar")
                failures += 1
                continue
            ok = all(abs((m.get(k) or 0) - (x or 0)) < 1e-9
                     for k, x in (("o", o), ("h", h), ("l", l), ("c", c), ("v", v)))
            print(f"   probe {sym} {day}: {'MATCH' if ok else 'MISMATCH ' + str(m)}")
            failures += (not ok)

    conn.close()
    print(f"[result] {'PASS' if failures == 0 else f'FAIL ({failures} problems)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
