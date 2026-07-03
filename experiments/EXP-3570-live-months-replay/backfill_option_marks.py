#!/usr/bin/env python3
"""EXP-3570 step 1 — backfill SPY daily option bars 2026-04-01..2026-07-02.

- Contracts: existing option_contracts rows (expiries 2026-04-03..2026-06-30)
  plus newly listed Jul/Aug 2026 expiries (<= 2026-08-21, needed for EXP-800
  15-25 DTE and V8A 25-50 DTE entries in June) fetched from Polygon
  v3/reference/options/contracts and inserted with as_of_date 2026-07-03.
- Strike band 500..950 (SPY traded 655..760 in the window; band covers 2% OTM
  EXP-800 entries, 0.20-delta V8A entries, $12 IC wings, and deep-ITM exits).
- Bars: one v2/aggs request per contract for the whole window; INSERT OR
  IGNORE into option_daily (PK contract_symbol+date — existing rows are never
  touched). open_interest NULL, matching the standard-tier convention in
  backtest/historical_data.py.
- Rate limit ~4.5 req/s token pacing, 429 respects Retry-After, 5xx retries.
- Resume-safe: done contracts journaled to results/backfill_done.txt.
- DB was backed up to data/options_cache.db.bak-exp3570 before first write.
"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
DB = ROOT / "data" / "options_cache.db"
DONE_FILE = HERE / "results" / "backfill_done.txt"
BAR_START, BAR_END = "2026-04-01", "2026-07-02"
NEW_EXP_LO, NEW_EXP_HI = "2026-07-01", "2026-08-21"
STRIKE_LO, STRIKE_HI = 500.0, 950.0
AS_OF = "2026-07-03"
RATE = 4.5  # req/s


def load_key() -> str:
    env = {}
    for line in open(ROOT / ".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"')
    key = env.get("POLYGON_OPTIONS_API_KEY") or env.get("POLYGON_API_KEY")
    if not key:
        print("FATAL: no Polygon key in .env", file=sys.stderr)
        sys.exit(2)
    return key


KEY = load_key()
_last_req = [0.0]


def get(url: str, tries: int = 6) -> dict:
    """Rate-paced GET with 429/Retry-After + 5xx handling."""
    for attempt in range(tries):
        wait = _last_req[0] + 1.0 / RATE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.monotonic()
        sep = "&" if "?" in url else "?"
        try:
            with urllib.request.urlopen(url + sep + "apiKey=" + KEY, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                delay = float(ra) if ra else 2.0 * (attempt + 1)
                print(f"[rate] 429 — sleeping {delay}s", flush=True)
                time.sleep(delay)
                continue
            if e.code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"gave up after {tries} tries: {url[:120]}")


def list_new_contracts() -> list:
    """Page through Jul/Aug 2026 SPY contracts (active — expiries are future)."""
    out = []
    url = ("https://api.polygon.io/v3/reference/options/contracts?"
           f"underlying_ticker=SPY&expiration_date.gte={NEW_EXP_LO}"
           f"&expiration_date.lte={NEW_EXP_HI}&limit=1000")
    while url:
        d = get(url)
        for r in d.get("results", []):
            out.append((r["underlying_ticker"], r["expiration_date"],
                        float(r["strike_price"]), r["contract_type"][0].upper(),
                        r["ticker"], AS_OF))
        url = d.get("next_url")
    return out


def main() -> None:
    conn = sqlite3.connect(DB, timeout=60)
    done = set()
    if DONE_FILE.exists():
        done = set(DONE_FILE.read_text().split())
    donef = open(DONE_FILE, "a")

    # ── 1. list + insert new Jul/Aug contract rows (new rows only) ──────────
    marker = "__contracts_listed__"
    if marker not in done:
        new_rows = list_new_contracts()
        in_band = [r for r in new_rows if STRIKE_LO <= r[2] <= STRIKE_HI]
        before = conn.execute("select count(*) from option_contracts").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO option_contracts "
            "(ticker, expiration, strike, option_type, contract_symbol, as_of_date) "
            "VALUES (?,?,?,?,?,?)", in_band)
        conn.commit()
        after = conn.execute("select count(*) from option_contracts").fetchone()[0]
        print(f"[contracts] listed {len(new_rows)} Jul/Aug SPY contracts, "
              f"{len(in_band)} in strike band, inserted {after - before} new rows", flush=True)
        donef.write(marker + "\n"); donef.flush()
        done.add(marker)

    # ── 2. build fetch list ──────────────────────────────────────────────────
    syms = [r[0] for r in conn.execute(
        "SELECT contract_symbol FROM option_contracts "
        "WHERE ticker='SPY' AND expiration BETWEEN '2026-04-03' AND ? "
        "AND strike BETWEEN ? AND ? ORDER BY expiration, strike",
        (NEW_EXP_HI, STRIKE_LO, STRIKE_HI))]
    todo = [s for s in syms if s not in done]
    print(f"[plan] {len(syms)} contracts in scope, {len(todo)} to fetch "
          f"(~{len(todo)/RATE/60:.0f} min)", flush=True)

    # ── 3. fetch bars ────────────────────────────────────────────────────────
    ins = bars = 0
    t0 = time.monotonic()
    for i, sym in enumerate(todo):
        d = get(f"https://api.polygon.io/v2/aggs/ticker/{urllib.parse.quote(sym)}"
                f"/range/1/day/{BAR_START}/{BAR_END}?adjusted=true&limit=120")
        rows = []
        for b in d.get("results") or []:
            day = time.strftime("%Y-%m-%d", time.gmtime(b["t"] / 1000))
            rows.append((sym, day, b.get("o"), b.get("h"), b.get("l"),
                         b.get("c"), b.get("v"), None))
        if rows:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO option_daily "
                "(contract_symbol, date, open, high, low, close, volume, open_interest) "
                "VALUES (?,?,?,?,?,?,?,?)", rows)
            ins += cur.rowcount
            bars += len(rows)
        donef.write(sym + "\n")
        if (i + 1) % 100 == 0:
            conn.commit(); donef.flush()
        if (i + 1) % 500 == 0:
            el = time.monotonic() - t0
            eta = el / (i + 1) * (len(todo) - i - 1) / 60
            print(f"[progress] {i+1}/{len(todo)} contracts, {ins} new rows, "
                  f"ETA {eta:.0f} min", flush=True)
    conn.commit(); donef.flush()
    print(f"[done] fetched {len(todo)} contracts: {bars} bars seen, {ins} new rows inserted", flush=True)

    lo, hi = conn.execute("select min(date), max(date) from option_daily where date >= '2026-04-01'").fetchone()
    n = conn.execute("select count(*) from option_daily where date between '2026-04-03' and '2026-07-02'").fetchone()[0]
    print(f"[verify] window rows now: {n}, date span {lo}..{hi}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
