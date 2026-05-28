# Shared bar cache (`shared/shared_bar_cache.py`)

Cross-process SQLite cache for **daily OHLCV bars**, shipped in Phase 1 of the
shared-cache architecture (proposal Option B). It exists to stop the 10
experiment subprocesses from each independently fetching the same ~760-day
SPY/TLT/^VIX daily bars from Polygon on every cold start (which caused the
startup `429` bursts).

## Why a local file is a *shared* cache

`railway_worker.py` runs all experiments as `subprocess.Popen` children of **one**
container, all sharing the mounted Railway volume. So a single SQLite file on
that volume is genuinely shared across every subprocess — no Redis, no IPC, no
network. WAL journal mode gives many concurrent readers + one writer.

## What it stores — and what it does NOT

| Stored | Not stored |
|---|---|
| Daily OHLCV bars (`Open/High/Low/Close/Volume`) keyed by `(ticker, bar_date)` | Options chains (stay on **UnusualWhales**) |
| Per-ticker freshness timestamp (`bar_meta`) | Intraday bars, quotes, Greeks |

The cache covers exactly what `PolygonProvider.get_historical()` returns today.
**Options paths are untouched.**

## Contract

- **Feature-flagged.** `DataCache` only consults the shared cache when
  `USE_SHARED_CACHE` is truthy (`1/true/yes/on`). **Default OFF** — with the
  flag off, `DataCache.get_history()` behaves exactly as before (direct Polygon
  fetch into the per-process in-memory L1). Phase 2 flips the flag per
  experiment.
- **Layering:** in-memory L1 (per process, `ttl_seconds`) → shared SQLite L2
  (cross-process) → Polygon (origin).
- **Stale-while-revalidate.** `get_bars()` returns a freshness verdict:
  - `FRESH` (age < `fresh_ttl`, default = `DataCache` TTL = 900s): served directly.
  - `STALE` (`fresh_ttl` ≤ age ≤ `max_stale`, default 3 days): the stale frame is
    served **immediately** and a background thread revalidates from Polygon
    (single-flight per ticker, with a cross-process re-check to skip if another
    subprocess already refreshed it).
  - `MISS` (no rows, or age > `max_stale`): caller fetches synchronously from
    Polygon and writes through.
- **Best-effort / never required.** Any SQLite error raises `SharedCacheError`;
  `DataCache` catches it and falls back to a direct Polygon fetch. A corrupt or
  missing cache can never take the scanner down.
- **Write-through.** Every origin fetch (sync miss or background refresh) upserts
  bars + bumps the freshness timestamp (`INSERT OR REPLACE`, idempotent).

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `USE_SHARED_CACHE` | `false` | Master switch for the shared-cache path. |
| `SHARED_CACHE_DB` | `<DATA_DIR>/shared_bars.db` | Override the DB file location. |

`DATA_DIR` resolves to the Railway volume (`/app/data`) via `ATTIX_DATA_DIR`.

## Schema (`SCHEMA_VERSION = 1`)

```
daily_bars(ticker, bar_date, open, high, low, close, volume)   PK (ticker, bar_date)
bar_meta(ticker, last_fetch_ts, row_count)                     PK (ticker)
cache_schema(version)
```

Migrations are gated on `cache_schema.version`; re-opening an existing DB never
loses data.

## Tests

- `tests/test_shared_bar_cache.py` — read/write round-trip, TTL/freshness
  (fresh/stale/miss + max-stale), schema init & migration, corrupt-DB →
  `SharedCacheError`, concurrent readers under a writer (WAL).
- `tests/test_data_cache_shared.py` — flag-off parity, fresh-serves-without-
  provider, miss-fetches-and-writes-through, stale-serves-then-background-
  refresh, shared-error-falls-back-to-provider.
