#!/usr/bin/env python3
"""P1A-addendum data repair — backfill QQQ option daily bars 2023-01-01..2024-12-31.

EXP-3570 protocol: DB already backed up (options_cache.db.bak-p1a); probe
cross-check passed 3/3 before first write; contracts listed from Polygon
v3/reference (expired included) in per-year strike bands; one v2/aggs request
per contract for the window; INSERT OR IGNORE only (existing rows never
modified); resume-safe via results/backfill_qqq_done.txt.

Key from env POLYGON_OPTIONS_API_KEY (never stored in-repo).
Bands: expiries 2023-01-01..2024-02-16 -> strikes 200..460;
       expiries 2024-02-17..2025-02-28 -> strikes 300..620.
Bars window: 2023-01-01..2024-12-31 (nothing past the in-sample boundary).
"""
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
DB = ROOT / "data" / "options_cache.db"
DONE = HERE / "results" / "backfill_qqq_done.txt"
BAR_START, BAR_END = "2023-01-01", "2024-12-31"
# Puts only (the addendum re-runs A3/A4 put verticals; A5 IC is void, not re-run).
# Bands cover 2%-OTM short strikes + 12-wide long side + exit marks, vs spot range.
BANDS = [("2023-01-01", "2024-02-16", 225.0, 415.0),
         ("2024-02-17", "2025-02-28", 300.0, 540.0)]
AS_OF = "2026-07-12"
RATE = 4.5  # restored: sibling SLV backfill finished, key no longer shared

KEY = os.environ.get("POLYGON_OPTIONS_API_KEY", "")
if not KEY:
    print("FATAL: POLYGON_OPTIONS_API_KEY not in env", file=sys.stderr)
    sys.exit(2)

_last = [0.0]


def get(url, tries=6):
    for attempt in range(tries):
        wait = _last[0] + 1.0 / RATE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After", 2)))
                continue
            if e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"retries exhausted: {url.split('apiKey')[0]}")


def list_contracts():
    out = {}
    for exp_lo, exp_hi, klo, khi in BANDS:
        for expired in ("true", "false"):
            url = ("https://api.polygon.io/v3/reference/options/contracts?"
                   + urllib.parse.urlencode({
                       "underlying_ticker": "QQQ", "expired": expired, "limit": 1000,
                       "contract_type": "put",
                       "expiration_date.gte": exp_lo, "expiration_date.lte": exp_hi,
                       "strike_price.gte": klo, "strike_price.lte": khi,
                       "apiKey": KEY}))
            while url:
                d = get(url)
                for c in d.get("results", []):
                    out[c["ticker"]] = (c["expiration_date"], c["strike_price"],
                                        "C" if c["contract_type"] == "call" else "P")
                nxt = d.get("next_url")
                url = (nxt + "&apiKey=" + KEY) if nxt else None
    return out


def main():
    db = sqlite3.connect(str(DB), timeout=120)
    db.execute("PRAGMA busy_timeout=120000")  # coexist with the sibling SLV backfill writer
    done = set()
    if DONE.exists():
        done = set(DONE.read_text().split())
    contracts = list_contracts()
    print(f"listed {len(contracts)} contracts; {len(done)} already done", flush=True)

    # insert missing contract rows (INSERT OR IGNORE — never touch existing)
    ins = [(sym, exp, k, t, AS_OF) for sym, (exp, k, t) in contracts.items()]
    db.executemany(
        """INSERT OR IGNORE INTO option_contracts
           (contract_symbol, ticker, expiration, strike, option_type, as_of_date)
           VALUES (?, 'QQQ', ?, ?, ?, ?)""", ins)
    db.commit()

    n_bars = 0
    todo = [s for s in sorted(contracts) if s not in done]
    with open(DONE, "a") as journal:
        for i, sym in enumerate(todo):
            url = (f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/day/"
                   f"{BAR_START}/{BAR_END}?limit=50000&apiKey={KEY}")
            try:
                d = get(url)
            except RuntimeError as e:
                print("SKIP", sym, e, flush=True)
                continue
            rows = [(sym, time.strftime("%Y-%m-%d", time.gmtime(b["t"] / 1000)),
                     b.get("o"), b.get("h"), b.get("l"), b.get("c"), b.get("v"))
                    for b in d.get("results", [])]
            if rows:
                db.executemany(
                    """INSERT OR IGNORE INTO option_daily
                       (contract_symbol, date, open, high, low, close, volume)
                       VALUES (?,?,?,?,?,?,?)""", rows)
                n_bars += len(rows)
            journal.write(sym + "\n")
            if i % 500 == 0:
                db.commit()
                journal.flush()
                print(f"{i}/{len(todo)} contracts, +{n_bars} bars", flush=True)
    db.commit()
    print(f"DONE: {len(todo)} contracts fetched, +{n_bars} bars inserted", flush=True)


if __name__ == "__main__":
    main()
