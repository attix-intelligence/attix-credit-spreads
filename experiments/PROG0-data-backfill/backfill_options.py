#!/usr/bin/env python3
"""PROG-0 zero-spend options backfill (PROFITABILITY_PROGRAM.md §0).

Jobs (positional arg):
  slv     — SLV options full history: Friday expiries 2020-01-03..2026-08-21,
            per-expiry strike band from spot, daily aggs 2019-12-02..2026-07-10.
  extend  — QQQ/GLD/TLT: Friday expiries 2025-12-26..2026-08-21 (the cache ends
            at the 2025-12-19 monthly), same per-expiry banding, daily aggs
            2025-12-19..2026-07-10 for the NEW contracts only.
  merge   — one-shot INSERT OR IGNORE of the staging DB into options_cache.db
            (run after slv/extend complete; retries through lock contention).

STAGING DESIGN: fetch jobs write to data/prog0_staging.db, NOT the main cache.
A sibling-session backfill (honest-fills-fleet QQQ 2023-24) holds the main
DB's write lock for long stretches; direct writes ran ~7x slow (ETA 465 min
vs 64) and one run died on `database is locked` despite 300s busy_timeout.
Staging decouples the (slow, network-bound) fetch from the (fast, contended)
insert; `merge` is one bounded write window. The first SLV run inserted
~11.1k contracts / 326k bars directly into the main DB before the switch —
harmless (same INSERT OR IGNORE semantics; merge dedupes the remainder).

Follows the EXP-3570 backfill protocol:
  - Main DB backed up first (data/options_cache.db.bak-prog0, 2026-07-12);
    pre-run probe cross-check 5/5 (see reports/PROG0_DATA_BACKFILL.md).
  - Contracts from v3/reference/options/contracts (expired=true + active);
    bars one v2/aggs request per contract; INSERT OR IGNORE only —
    existing main-DB rows are never touched.
  - open_interest NULL per standard-tier convention.
  - Rate ~4.5 req/s, 429 Retry-After honored, 5xx retried; resume journal
    results/<job>_done.txt.
  - Integrity counts printed before/after; Rule Zero: every row is a real
    Polygon bar; nothing synthesized.

Key: POLYGON_API_KEY (NOT the OPTIONS key — that one 403s pre-2024 option
aggs; the stocks key has full-depth options entitlement, probe-verified).

Strike banding: per-expiry [0.70 x min spot close, 1.30 x max spot close]
over the 180 calendar days ending at expiry.

Usage:  .venv/bin/python experiments/PROG0-data-backfill/backfill_options.py slv
        .venv/bin/python experiments/PROG0-data-backfill/backfill_options.py extend
        .venv/bin/python experiments/PROG0-data-backfill/backfill_options.py merge
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
STAGING = ROOT / "data" / "prog0_staging.db"
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


def db_retry(fn, tries: int = 60):
    """Retry a main-DB write through sibling-session lock contention."""
    for attempt in range(tries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == tries - 1:
                raise
            delay = min(30.0, 5.0 * (attempt + 1))
            print(f"[lock] database locked — retry {attempt+1}/{tries} in {delay}s", flush=True)
            time.sleep(delay)


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
            print(f"[net] transient error — retry {attempt+1}/{tries}", flush=True)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"gave up after {tries} tries: {url[:120]}")


def spot_closes(ticker: str, start: str, end: str) -> dict:
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
    rows = []
    for expired in ("true", "false"):
        url = ("https://api.polygon.io/v3/reference/options/contracts?"
               f"underlying_ticker={ticker}&expired={expired}"
               f"&expiration_date.gte={lo}&expiration_date.lte={hi}&limit=1000")
        while url:
            d = get(url)
            for r in d.get("results", []):
                exp = r["expiration_date"]
                if dt.date.fromisoformat(exp).weekday() != 4:  # Fridays only
                    continue
                rows.append((r["underlying_ticker"], exp, float(r["strike_price"]),
                             r["contract_type"][0].upper(), r["ticker"], AS_OF))
            url = d.get("next_url")
    seen, out = set(), []
    for r in rows:
        if r[4] not in seen:
            seen.add(r[4])
            out.append(r)
    return out


def expiry_band(spot: dict, expiry: str) -> tuple:
    e = dt.date.fromisoformat(expiry)
    lo_d = (e - dt.timedelta(days=180)).isoformat()
    vals = [c for d, c in spot.items() if lo_d <= d <= expiry]
    if not vals:
        tail = sorted(spot.items())[-120:]
        vals = [c for _, c in tail]
    return 0.70 * min(vals), 1.30 * max(vals)


def staging_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(STAGING, timeout=60)
    conn.execute("CREATE TABLE IF NOT EXISTS option_contracts ("
                 "ticker TEXT, expiration TEXT, strike REAL, option_type TEXT, "
                 "contract_symbol TEXT PRIMARY KEY, as_of_date TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS option_daily ("
                 "contract_symbol TEXT, date TEXT, open REAL, high REAL, low REAL, "
                 "close REAL, volume REAL, open_interest REAL, "
                 "PRIMARY KEY (contract_symbol, date))")
    return conn


def run_fetch(job: str) -> None:
    tickers, exp_lo, exp_hi, bar_start, bar_end = JOBS[job]
    done_file = RES / f"{job}_done.txt"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    donef = open(done_file, "a")

    stg = staging_conn()
    main_ro = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    for ticker in tickers:
        print(f"=== {ticker} ===", flush=True)
        spot = spot_closes(ticker, "2019-06-03", bar_end)
        print(f"[spot] {ticker}: {len(spot)} days, "
              f"range {min(spot.values()):.2f}..{max(spot.values()):.2f}", flush=True)

        marker = f"__{ticker}_contracts_listed__"
        if marker not in done:
            listed = list_contracts(ticker, exp_lo, exp_hi)
            bands, in_band = {}, []
            for r in listed:
                exp = r[1]
                if exp not in bands:
                    bands[exp] = expiry_band(spot, exp)
                lo, hi = bands[exp]
                if lo <= r[2] <= hi:
                    in_band.append(r)
            stg.executemany(
                "INSERT OR IGNORE INTO option_contracts VALUES (?,?,?,?,?,?)", in_band)
            stg.commit()
            print(f"[contracts] {ticker}: listed {len(listed)} Friday-expiry, "
                  f"{len(in_band)} in band ({len(bands)} expiries) -> staging", flush=True)
            donef.write(marker + "\n"); donef.flush()
            done.add(marker)

        # fetch list = this job's contracts (staging) ∪ contracts the pre-staging
        # SLV run already put in the MAIN db under this as_of_date. Both branches
        # are pinned to the JOB'S expiry window: a sibling-session backfill writes
        # same-day QQQ 2023-24 contracts into the main DB, and without the window
        # filter the union pulled in its 139k contracts (theirs to fetch, not ours).
        syms = [r[0] for r in stg.execute(
            "SELECT contract_symbol FROM option_contracts WHERE ticker=? AND as_of_date=? "
            "AND expiration BETWEEN ? AND ? ORDER BY expiration, strike",
            (ticker, AS_OF, exp_lo, exp_hi))]
        syms += [r[0] for r in main_ro.execute(
            "SELECT contract_symbol FROM option_contracts WHERE ticker=? AND as_of_date=? "
            "AND expiration BETWEEN ? AND ?",
            (ticker, AS_OF, exp_lo, exp_hi))]
        syms = list(dict.fromkeys(syms))
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
                cur = stg.executemany(
                    "INSERT OR IGNORE INTO option_daily VALUES (?,?,?,?,?,?,?,?)", rows)
                ins += cur.rowcount
                bars += len(rows)
            donef.write(sym + "\n")
            if (i + 1) % 100 == 0:
                stg.commit(); donef.flush()
            if (i + 1) % 500 == 0:
                el = time.monotonic() - t0
                eta = el / (i + 1) * (len(todo) - i - 1) / 60
                print(f"[progress] {ticker} {i+1}/{len(todo)}, {ins} new staging rows, "
                      f"ETA {eta:.0f} min", flush=True)
        stg.commit(); donef.flush()
        nb = stg.execute("select count(*) from option_daily od join option_contracts oc "
                         "using(contract_symbol) where oc.ticker=?", (ticker,)).fetchone()[0]
        print(f"[fetched] {ticker}: {len(todo)} contracts this run, {bars} bars seen, "
              f"{ins} staged; staging bars for {ticker} now {nb}", flush=True)

    stg.close(); main_ro.close()
    print("[done fetch] run `merge` after all fetch jobs complete", flush=True)


def run_merge() -> None:
    assert STAGING.exists(), "no staging DB — run slv/extend first"
    conn = sqlite3.connect(DB, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute(f"ATTACH DATABASE 'file:{STAGING}?mode=ro' AS stg")

    bc = conn.execute("select count(*) from option_contracts").fetchone()[0]
    bd = conn.execute("select count(*) from option_daily").fetchone()[0]
    sc = conn.execute("select count(*) from stg.option_contracts").fetchone()[0]
    sd = conn.execute("select count(*) from stg.option_daily").fetchone()[0]
    print(f"[merge] main before: contracts={bc} daily={bd}; staging: {sc}/{sd}", flush=True)

    t0 = time.monotonic()
    db_retry(lambda: conn.execute(
        "INSERT OR IGNORE INTO option_contracts SELECT * FROM stg.option_contracts"))
    db_retry(lambda: conn.execute(
        "INSERT OR IGNORE INTO option_daily SELECT * FROM stg.option_daily"))
    db_retry(conn.commit)
    ac = conn.execute("select count(*) from option_contracts").fetchone()[0]
    ad = conn.execute("select count(*) from option_daily").fetchone()[0]
    print(f"[merge] done in {time.monotonic()-t0:.1f}s: contracts +{ac-bc} -> {ac}; "
          f"daily +{ad-bd} -> {ad}", flush=True)
    conn.close()


def main() -> None:
    job = sys.argv[1] if len(sys.argv) > 1 else None
    if job == "merge":
        run_merge()
    elif job in JOBS:
        run_fetch(job)
    else:
        print(f"usage: backfill_options.py {{{'|'.join(JOBS)}|merge}}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
