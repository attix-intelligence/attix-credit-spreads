#!/usr/bin/env python3
"""PROG-0 zero-spend options backfill (PROFITABILITY_PROGRAM.md §0).

Jobs (positional arg):
  slv     — SLV options full history: Friday expiries 2020-01-03..2026-08-21,
            per-expiry strike band from spot, daily aggs 2019-12-02..2026-07-10.
  extend  — QQQ/GLD/TLT: Friday expiries 2025-12-26..2026-08-21 (the cache ends
            at the 2025-12-19 monthly), same per-expiry banding, daily aggs
            2025-12-19..2026-07-10 for the NEW contracts only.

Follows the EXP-3570 backfill protocol exactly:
  - DB backed up first (data/options_cache.db.bak-prog0, 2026-07-12) before
    any write; probe cross-check done pre-run (5/5 cached-vs-API bar matches,
    see reports/PROG0_DATA_BACKFILL.md).
  - Contracts from v3/reference/options/contracts (expired=true + active pass);
    bars one v2/aggs request per contract; INSERT OR IGNORE only (PK
    contract_symbol+date / contract_symbol — existing rows never touched).
  - open_interest NULL per the standard-tier convention (backtest/historical_data.py).
  - Rate ~4.5 req/s, 429 Retry-After honored, 5xx retried; resume journal in
    results/<job>_done.txt.
  - Integrity counts printed before/after; post-run probe cross-check in the
    report. Rule Zero: every row is a real Polygon bar; nothing synthesized.

Key: POLYGON_API_KEY (NOT the OPTIONS key — probe showed the OPTIONS key 403s
on pre-2024 option aggs; the stocks key has full-depth options entitlement).

Strike banding: per-expiry [0.70 x min spot close, 1.30 x max spot close] over
the 180 calendar days ending at expiry (spot from Polygon stock aggs) — covers
deep-ITM exits and far-OTM wings without dragging the full penny-strike tail.

Usage:  .venv/bin/python experiments/PROG0-data-backfill/backfill_options.py slv
        .venv/bin/python experiments/PROG0-data-backfill/backfill_options.py extend
"""
from __future__ import annotations

import datetime as dt
import json
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
RES = HERE / "results"
RES.mkdir(exist_ok=True)
RATE = 4.5
AS_OF = "2026-07-12"

JOBS = {
    # job: (tickers, expiry_lo, expiry_hi, bar_start, bar_end)
    "slv":    (["SLV"], "2020-01-03", "2026-08-21", "2019-12-02", "2026-07-10"),
    "extend": (["QQQ", "GLD", "TLT"], "2025-12-26", "2026-08-21", "2025-12-19", "2026-07-10"),
}


def load_key() -> str:
    env = {}
    for line in open(ROOT / ".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"')
    key = env.get("POLYGON_API_KEY")  # full-depth options entitlement (probe-verified)
    if not key:
        print("FATAL: POLYGON_API_KEY missing from .env", file=sys.stderr)
        sys.exit(2)
    return key


KEY = load_key()
_last_req = [0.0]


def get(url: str, tries: int = 6) -> dict:
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


def spot_closes(ticker: str, start: str, end: str) -> dict:
    """date -> close for the underlying, from Polygon stock aggs (paginated)."""
    out = {}
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
           f"{start}/{end}?adjusted=true&limit=5000")
    while url:
        d = get(url)
        for b in d.get("results") or []:
            day = time.strftime("%Y-%m-%d", time.gmtime(b["t"] / 1000))
            out[day] = b["c"]
        url = d.get("next_url")
    return out


def list_contracts(ticker: str, lo: str, hi: str) -> list:
    """All contracts (expired + active) with Friday expiries in [lo, hi]."""
    rows = []
    for expired in ("true", "false"):
        url = ("https://api.polygon.io/v3/reference/options/contracts?"
               f"underlying_ticker={ticker}&expired={expired}"
               f"&expiration_date.gte={lo}&expiration_date.lte={hi}&limit=1000")
        while url:
            d = get(url)
            for r in d.get("results", []):
                exp = r["expiration_date"]
                if dt.date.fromisoformat(exp).weekday() != 4:  # Fridays only (cache convention)
                    continue
                rows.append((r["underlying_ticker"], exp, float(r["strike_price"]),
                             r["contract_type"][0].upper(), r["ticker"], AS_OF))
            url = d.get("next_url")
    # dedupe on contract_symbol (expired/active passes can overlap)
    seen, out = set(), []
    for r in rows:
        if r[4] not in seen:
            seen.add(r[4])
            out.append(r)
    return out


def expiry_band(spot: dict, expiry: str) -> tuple:
    """[0.70 x min close, 1.30 x max close] over 180 cal days ending at expiry."""
    e = dt.date.fromisoformat(expiry)
    lo_d = (e - dt.timedelta(days=180)).isoformat()
    vals = [c for d, c in spot.items() if lo_d <= d <= expiry]
    if not vals:  # future expiry beyond spot history: use trailing 180d of what we have
        tail = sorted(spot.items())[-120:]
        vals = [c for _, c in tail]
    return 0.70 * min(vals), 1.30 * max(vals)


def main() -> None:
    job = sys.argv[1] if len(sys.argv) > 1 else None
    if job not in JOBS:
        print(f"usage: backfill_options.py {{{'|'.join(JOBS)}}}", file=sys.stderr)
        sys.exit(2)
    tickers, exp_lo, exp_hi, bar_start, bar_end = JOBS[job]

    done_file = RES / f"{job}_done.txt"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    donef = open(done_file, "a")

    conn = sqlite3.connect(DB, timeout=60)

    for ticker in tickers:
        print(f"=== {ticker} ===", flush=True)
        before_c = conn.execute("select count(*) from option_contracts where ticker=?", (ticker,)).fetchone()[0]
        before_b = conn.execute(
            "select count(*) from option_daily od join option_contracts oc using(contract_symbol) "
            "where oc.ticker=?", (ticker,)).fetchone()[0]
        print(f"[before] {ticker}: contracts={before_c} bars={before_b}", flush=True)

        spot = spot_closes(ticker, "2019-06-03", bar_end)
        print(f"[spot] {ticker}: {len(spot)} days, "
              f"range {min(spot.values()):.2f}..{max(spot.values()):.2f}", flush=True)

        marker = f"__{ticker}_contracts_listed__"
        if marker not in done:
            listed = list_contracts(ticker, exp_lo, exp_hi)
            bands = {}
            in_band = []
            for r in listed:
                exp = r[1]
                if exp not in bands:
                    bands[exp] = expiry_band(spot, exp)
                lo, hi = bands[exp]
                if lo <= r[2] <= hi:
                    in_band.append(r)
            conn.executemany(
                "INSERT OR IGNORE INTO option_contracts "
                "(ticker, expiration, strike, option_type, contract_symbol, as_of_date) "
                "VALUES (?,?,?,?,?,?)", in_band)
            conn.commit()
            after_c = conn.execute("select count(*) from option_contracts where ticker=?", (ticker,)).fetchone()[0]
            print(f"[contracts] {ticker}: listed {len(listed)} Friday-expiry contracts, "
                  f"{len(in_band)} in band, inserted {after_c - before_c} new rows "
                  f"({len(bands)} expiries)", flush=True)
            donef.write(marker + "\n"); donef.flush()
            done.add(marker)

        # fetch bars for contracts new to this job (as_of_date = AS_OF) — never
        # re-fetch pre-existing cache contracts (their bars are already spanned)
        syms = [r[0] for r in conn.execute(
            "SELECT contract_symbol FROM option_contracts "
            "WHERE ticker=? AND as_of_date=? ORDER BY expiration, strike",
            (ticker, AS_OF))]
        todo = [s for s in syms if s not in done]
        print(f"[plan] {ticker}: {len(syms)} job contracts, {len(todo)} to fetch "
              f"(~{len(todo)/RATE/60:.0f} min)", flush=True)

        ins = bars = 0
        t0 = time.monotonic()
        for i, sym in enumerate(todo):
            d = get(f"https://api.polygon.io/v2/aggs/ticker/{urllib.parse.quote(sym)}"
                    f"/range/1/day/{bar_start}/{bar_end}?adjusted=true&limit=5000")
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
                print(f"[progress] {ticker} {i+1}/{len(todo)}, {ins} new rows, "
                      f"ETA {eta:.0f} min", flush=True)
        conn.commit(); donef.flush()

        after_c = conn.execute("select count(*) from option_contracts where ticker=?", (ticker,)).fetchone()[0]
        after_b, lo_d, hi_d = conn.execute(
            "select count(*), min(od.date), max(od.date) from option_daily od "
            "join option_contracts oc using(contract_symbol) where oc.ticker=?",
            (ticker,)).fetchone()
        print(f"[after] {ticker}: contracts {before_c}->{after_c} "
              f"bars {before_b}->{after_b} span {lo_d}..{hi_d} "
              f"(fetched {len(todo)} contracts, {bars} bars seen, {ins} inserted)", flush=True)

    conn.close()
    print("[done]", flush=True)


if __name__ == "__main__":
    main()
