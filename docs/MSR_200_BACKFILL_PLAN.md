# MSR-200 Historical Signal Backfill — Plan & Cost Pilot

**Owner:** MSR / signals
**Status:** plumbing complete (200a→200d); awaiting cost pilot decision
**Last updated:** 2026-05-28

## Why this exists

Phase 1 of MSR-001 (theme-rotation) requires historical `momentum_z`,
`flow_z`, and `sentiment_z` for the universe over 2022-01-03 → 2025-12-31
so the equity backtester has the same signal shape the live path uses.

The Polygon snapshot endpoints that drive the live signal pipeline are
**live-only** — no per-date history. CBOE Athena 60-min option candles
**are historical** (14.5 years, 5,957 underliers, partitioned by
year/month/day) and so MSR-200 routes the historical reconstruction
through Athena via :class:`compass.signals.athena_provider.AthenaSignalDataProvider`.

`dark_flow_z` is **not reconstructable historically** — TradeAlgo
publishes a daily bundle but does not expose a history endpoint. The
backfill emits `dark_flow_z = None` for every row; the equity backtester
must gate dark-flow filtering off for dates without a bundle.

## What's already built

| Component | File | Status |
|---|---|---|
| MSR-200a — universe (65 tickers) | `strategies/msr_universe.{yaml,py}` | ✅ done |
| MSR-200b — Athena provider | `compass/signals/athena_provider.py` | ✅ done |
| MSR-200c — per-date orchestrator | `compass/signals/_historical.py` | ✅ done |
| MSR-200d — backfill runner CLI | `scripts/msr200_build_signals.py` | ✅ done |
| MSR-200e — cost pilot + this doc | — | 🟡 in progress |

## Cost framework — what we're trying to bound

Athena pricing: **$5.00 per TB scanned** (ap-southeast-1, same as us-east-1).
There are no other Athena charges in our path (no Workgroup CU,
no SCT). The cost equation is simply::

    total_cost  = (sum of all bytes_scanned across the run) / 1 TB × $5

The runner persists per-date `athena_bytes_scanned` and `athena_queries`
to `data/signals/run_log.jsonl`, so the actual cost is auditable after
the run.

### Per-query scan size — the load-bearing variable

Athena uses columnar storage. **The WHERE clause on non-partition columns
(symbol, expiration, etc.) does NOT reduce scan size** — it only filters
the returned rows. The scan size is determined by:

* the **columns** we SELECT (we read 11 of 36 in `cboe_60min_option_candles`)
* the **partition** the query touches (year/month/day predicate)

The empirical baseline from `backtest/spx_athena_chain.py` is **~55 MB
scanned per single-day partition** for a 13-column SELECT. Our 11-column
SELECT will be very close — call it **50-60 MB / per-day / per-query**.

### Two regimes — same pipeline, two cost outcomes

The orchestrator (`build_tilt_for_date`) iterates the universe and calls
`provider.options_snapshot(ticker)` per ticker. Each call is one Athena
query. So the cost scales with **(queries per date) × (scan per query)**:

| Regime | Queries/date | Scan/date | 1,005 trading days | Cost @ $5/TB |
|---|---|---|---|---|
| **Un-batched** (status quo) | 65 | ~3.6 GB | ~3.6 TB | **~$18.00** |
| **Batched** (`symbol IN (…)`) | 1 | ~55 MB | ~55 GB | **~$0.28** |

The batched regime is **~65× cheaper**. The optimization is contained:

* Add `prefetch_chains(symbols, expiration_lte)` to `AthenaSignalDataProvider`
  that issues ONE query with `symbol IN (…)` and stores per-symbol
  results in an in-memory cache keyed on `(as_of, symbol)`.
* `options_snapshot(ticker)` becomes a cache-first lookup; cache miss
  falls back to the per-symbol query (current behaviour) so the
  interface is unchanged for tests.
* Orchestrator calls `prefetch_chains(universe.tickers, …)` once per
  date before iterating tickers.

This optimization (call it **MSR-200f**) is NOT yet implemented.

## Pilot SOP

The pilot is a single trading day, un-batched, to:

1. **Measure** the actual scan size per query against the SPX 55 MB baseline.
   (We're SELECTing 11 columns vs SPX's 13, with similar predicates.)
2. **Quantify variance** across the 65-ticker universe — some symbols
   may have heavier option chains (SPY, QQQ) and scan more rows after the
   columnar scan, but raw bytes-scanned should be uniform if my
   columnar-storage assumption is correct.
3. **Verify the schema** — confirm `option_type`, `delta`,
   `implied_volatility` parse cleanly into `OptionContract` for all 65
   tickers (the AthenaSignalDataProvider was smoke-tested with
   synthesized DataFrames, not real CBOE data).
4. **Establish wall-clock baseline** so we can estimate how long the full
   backfill takes (queries serialize through Athena; 65× 5-10s per query
   = ~5-10 min per date × 1005 days = days of wall clock).

### Pilot date

**2024-06-14** (Friday). Rationale:

* Mid-2024 → all 65 tickers have ≥ 6 months of leading history for the
  63-day z-score windows.
* Recent enough that option chains for tech leaders are dense.
* Not a known anomaly day (no FOMC, no major earnings clustering).

### Pilot command

```bash
python3 scripts/msr200_build_signals.py \
    --start 2024-06-14 --end 2024-06-14 \
    --out-dir data/signals \
    --max-failures-per-day 20
```

`--max-failures-per-day 20` aborts the pilot if more than 20 of the 65
tickers fail — a sanity guard against silent schema regressions.

### Pilot success criteria

| Metric | Pass | Investigate | Fail |
|---|---|---|---|
| Athena bytes scanned | < 5 GB | 5-10 GB | > 10 GB |
| Athena queries issued | 60-70 | — | other |
| n_success rows | ≥ 50 | 30-49 | < 30 |
| Wall-clock | < 15 min | 15-30 min | > 30 min |
| Schema parse failures | 0 | 1-3 | ≥ 4 |

A **Pass** result means the un-batched regime is cheap enough (~$18 for
the full backfill) to run as-is. An **Investigate** result means add
MSR-200f batching before the full run.

A **Fail** likely indicates schema mismatch — abort, debug, re-pilot.

### Post-pilot — Decision tree

```
Pilot bytes ≤ baseline?  ─── yes ──→ ┌─────────────────────────────────┐
                                     │ Full backfill un-batched is OK   │
                                     │ → run scripts/msr200_build_… on  │
                                     │   2022-01-03 → 2025-12-31        │
                                     │   in chunks of 1 quarter         │
                                     └─────────────────────────────────┘
                          ─── no  ──→ ┌─────────────────────────────────┐
                                     │ Implement MSR-200f (batched     │
                                     │ prefetch via symbol IN (…))     │
                                     │ → re-pilot 2024-06-14            │
                                     │ → then full backfill             │
                                     └─────────────────────────────────┘
```

### Recording the pilot result

After the pilot run completes, append a Results section to **this doc**
with the following fields (copy-pasteable template):

```yaml
pilot_2024_06_14:
  ran_at_utc:           # ISO8601
  region:               ap-southeast-1
  bytes_scanned:        # int (from run_log.jsonl)
  queries_issued:       # int
  scan_mb_per_query:    # bytes / queries / 1e6
  n_success:            # 0..65
  n_failed:             # 0..65
  elapsed_s:            # from run_log.jsonl
  est_cost_full_run:    # bytes × (1005/1) ÷ 1e12 × $5
  decision:             # PASS | INVESTIGATE | FAIL
  next_action:          # e.g. "proceed full run un-batched"
                        #      "implement MSR-200f then re-pilot"
                        #      "schema mismatch — debug per-ticker"
```

## Full backfill plan (only after pilot passes)

The 2022-01-03 → 2025-12-31 window contains ~1,005 NYSE trading days.

**Execution:** run the runner in 4 calendar-year chunks so each chunk
can be inspected before launching the next::

    --start 2022-01-03 --end 2022-12-31
    --start 2023-01-03 --end 2023-12-29
    --start 2024-01-02 --end 2024-12-31
    --start 2025-01-02 --end 2025-12-31

Each chunk:

1. Run with `--max-failures-per-day 15` (≤23% of universe).
2. Inspect `run_log.jsonl` — investigate any date with >5 failures.
3. Spot-check 3 random CSVs for sanity (no NaN tilt_scores everywhere,
   z-scores in expected -3..+3 range).
4. Then launch next chunk.

## Rule Zero checklist (audited before full run)

- [x] No fabricated z-scores — every row sourced from real Athena data
  or marked `failed=True` with a captured error string.
- [x] No look-ahead — each query is partition-pruned to a single
  year/month/day; the orchestrator never references rows from later dates.
- [x] `dark_flow_z = None` for all historical rows (TradeAlgo has no
  bundle history endpoint); backtester gates dark-flow filtering off
  pre-bundle-cutover.
- [x] `large_prints_$ = 0.0` honestly — `stock_trades` returns `[]`
  because CBOE Athena has no stock prints; the flow composite averages
  over the 4 remaining components.
- [x] `provider.as_of` defaults to `None` and raises `RuntimeError` if
  `options_snapshot` is called without it being set — no silent
  default-to-today look-ahead.

## Open items / future work

* **MSR-200f** — batched `prefetch_chains(symbols, …)` on
  AthenaSignalDataProvider; deferred unless pilot indicates the
  un-batched regime is too costly.
* **MSR-200g** — historical OI cache for `oi_delta` proxy improvement
  (flow_proxy README §3 notes this as a known limitation). Not blocking
  Phase 1 of MSR-001 — it's an enhancement.
* **dark_flow_z** — once TradeAlgo offers a history endpoint, fill in
  the column retroactively. Until then the backtester treats it as None.

## Pilot results

_Pending pilot run. Populate using the template above after running
`scripts/msr200_build_signals.py --start 2024-06-14 --end 2024-06-14`._
