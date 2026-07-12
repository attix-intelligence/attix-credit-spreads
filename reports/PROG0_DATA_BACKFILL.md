# PROG-0 — Zero-Spend Data Work (PROFITABILITY_PROGRAM.md §0)

**Date:** 2026-07-12 · **Author:** cc4 · **Carlos GO:** profitability program approved (this session)
**Protocol:** EXP-3570 backfill protocol — DB backup before first write, probe cross-check, integrity counts before/after, Rule Zero (every row is a real Polygon bar; nothing synthesized).

## Ledger

| Item | Status | Detail |
|---|---|---|
| DB backup | ✅ | `data/options_cache.db.bak-prog0` (1.04 GB, taken 2026-07-12 17:30 before any write) |
| Pre-run probe cross-check | ✅ 5/5 | Random cached QQQ/GLD bars (2021/2023/2024/2025 eras) re-fetched from Polygon: all OHLC fields match exactly |
| Key finding | ⚠️ | `POLYGON_OPTIONS_API_KEY` **403s on pre-2024 option aggs**; `POLYGON_API_KEY` has full-depth options entitlement — all PROG-0 fetches use the latter |
| (1) SLV backfill | ✅ | 28,016 Friday-expiry contracts (333 expiries 2020-01→2026-08), 833,522 bars 2019-12-02→2026-07-10 |
| (2) QQQ/GLD/TLT extension | ✅ | Friday expiries 2025-12-26→2026-08-21: QQQ 12,444 / GLD 10,668 / TLT 2,846 contracts; 462,670 bars 2025-12-19→2026-07-10 |
| (3a) FOMC 2020-2025 calendar | ✅ | 49 events → `compass/orchestrator/calendars/fomc_2020_2025.csv` |
| (3b) CPI 2020-2025 calendar | ✅ | 72 releases → `compass/orchestrator/calendars/cpi_2020_2025.csv` |
| (4) Multi-leg harness | ✅ | `backtest/multileg.py` + 10 passing tests (commit `f411fa9`) |
| Post-run integrity check | ✅ **PASS** | 16/16 probe matches, expiry sanity clean, growth-only asserted, backup verified |

## Before-counts (recorded pre-write, 2026-07-12)

| Ticker | Contracts | Daily bars | Bar span |
|---|---|---|---|
| SLV | 0 | 0 | — |
| QQQ | 23,022 | 779,955 | 2020-01-02 → 2025-12-19 |
| GLD | 14,738 | 190,133 | (has a pre-existing `0000-00-00` artifact row) → 2025-12-19 |
| TLT | 10,749 | 293,500 | (same artifact) → 2025-12-19 |
| **DB totals** | **280,709** | **6,397,396** | |

Pre-existing data quirks observed (NOT introduced or touched by PROG-0): a handful of `0000-00-00`-dated rows on GLD/TLT/SPY-era contracts; QQQ/GLD/TLT 2025 cache holds **monthly (3rd-Friday) expiries only** while earlier eras include weeklies. PROG-0 additions use all Friday expiries (weeklies + monthlies) — strictly more coverage, same convention family.

## After-counts (integrity check **PASS**, 2026-07-12 — `results/integrity_check.log`)

| Ticker | Contracts | Daily bars | Bar span | Probe cross-check |
|---|---|---|---|---|
| SLV | 0 → **28,016** | 0 → **833,522** | 2019-12-02 → 2026-07-10 | 4/4 MATCH |
| QQQ | 23,022 → 174,744¹ | 779,955 → 1,387,279¹ | → 2026-07-10 | 4/4 MATCH |
| GLD | 14,738 → 25,406 | 190,133 → 361,267 | → 2026-07-10 | 4/4 MATCH |
| TLT | 10,749 → 13,595 | 293,500 → 348,293 | → 2026-07-10 | 4/4 MATCH |
| **DB totals** | 280,709 → **473,961** | 6,397,396 → **8,064,169** | | **16/16 MATCH** |

¹ QQQ deltas include a **sibling session's concurrent 2023-24 backfill** (same working DB, same as-of date; its 2023-era rows show in the density histogram). PROG-0's own QQQ contribution is the 2026-era extension: 12,444 contracts / 236,743 bars staged and merged. All rows regardless of author passed the same probe/expiry checks.

Additional checks passed: zero bars dated past expiration+1 day on all new rows; per-year density continuous (no year gaps) on SLV 2020→2026; totals grew only (INSERT OR IGNORE can't mutate); pre-write backup `options_cache.db.bak-prog0` verified present. Fetch totals per run logs: SLV 488,787 bars staged (run 2) + ~326k direct (run 1); QQQ 236,743; GLD 171,134; TLT 54,793; merge moved 25,958 contracts + ~951k bars in 91.9 s.

## Method notes

- **Strike banding:** per-expiry `[0.70 × min spot close, 1.30 × max spot close]` over the 180 calendar days ending at expiry; spot from Polygon stock aggs. Covers 2%-OTM entries, 0.20-delta wings, and deep-ITM exits without the penny-strike tail.
- **Inserts:** `INSERT OR IGNORE` only (PKs `contract_symbol` / `contract_symbol+date`) — existing rows can never be mutated or deleted; the checker asserts totals only grew.
- **Resume safety:** per-contract journal in `experiments/PROG0-data-backfill/results/<job>_done.txt`; the SLV run survived one `database is locked` crash at contract 10,500 and resumed cleanly.
- **Staging redesign (operational finding):** a sibling-session backfill (honest-fills-fleet QQQ 2023-24) held the main DB's write lock for long stretches — direct writes ran ~7× slow (ETA 465 min vs 64) and died once on `database is locked` despite a 300 s busy_timeout. The runner was switched mid-job to fetch into `data/prog0_staging.db` (zero contention, full fetch speed) with a single bounded `merge` step (`INSERT OR IGNORE ... SELECT` under lock retry) at the end. The ~11.1k SLV contracts / 326k bars inserted directly into the main DB before the switch are valid and are deduped by the merge.
- **`open_interest` stays NULL** by standard-tier convention (`backtest/historical_data.py`); dealer-GEX work (P2A) still requires the CBOE DataShop purchase.

## Calendars (3) — provenance and validation

**FOMC 2020-2025** (`fomc_2020_2025.csv`, 49 rows) — built by `experiments/PROG0-data-backfill/build_fomc_calendar.py` fetching **federalreserve.gov directly** (reachable from this box):
- 2021-2025 from the FOMC calendars page; 2020 from the historical page, including the **Mar-2 and Mar-15-2020 unscheduled emergency meetings** (Mar-15 was a Sunday — flagged in-row; market window = next session). The cancelled Mar-17-18-2020 meeting is excluded; notation votes (2020 Mar-19/23/31, Aug-27; 2025 Aug-22) excluded, with the Mar-23-2020 facilities announcement noted in the header for researchers.
- Convention: each row = second day of the meeting (statement day), matching `fomc_2026.csv`.
- **Cross-check:** the same page's 2026 panel reproduces the committed `fomc_2026.csv` **8/8 exactly**; scheduled-meeting count validated 8/yr (7 in 2020 + 2 unscheduled).

**CPI 2020-2025** (`cpi_2020_2025.csv`, 72 rows) — built by `build_cpi_calendar.py`. bls.gov **403s this host** (direct and browser-UA), so the builder pulls **Wayback Machine captures of the official BLS schedule page** (9 snapshots 2020-2026; each carries ~14 months of official rows):
- **Cross-checks:** overlapping snapshots must agree on every reference month (build aborts on any conflict — none found); exactly 72 releases, one per month 2020-01→2025-12; every date a weekday inside the BLS 8th–16th release band; all releases 08:30 ET.

**Repo convention flag for Carlos:** the calendar CSVs are *untracked* — the repo-wide `.gitignore` `*.csv` rule catches them, and the existing 2026 calendar files are untracked too. The committed builders reproduce them deterministically, but if the on-disk files are ever lost, event-gated experiments (P2B) silently lose their calendars. Consider force-adding `compass/orchestrator/calendars/*.csv` or moving them to JSON.

## Harness (4) — what was built

`backtest/multileg.py` (commit `f411fa9`), shared by P1B/P1C/P1E/P2B:
- Positions = leg lists (`side`, `qty`, OCC symbol, expiration) over `option_daily` real marks. Credit/debit symmetric (net premium received; debits negative).
- **Entry = FIX #3 marketable semantics generalized to N legs on daily bars:** limit = net OPEN mark − per-pair slippage concession (qty-weighted pairs: vertical 1×, IC 2×, 1×2 ratio 1.5×); fills AT the limit iff the CLOSE-mark net traded at/through it. Bars missing opens book naively and are **counted** (`naive_fallback_entries`) per the program's non-SPY fill caveat; the ≤20 % prereg gate consumes this number.
- Daily MTM from closes with stale-mark carry and a per-position stale-day share (P1B's ">20 % missing back-leg marks" kill criterion reads this).
- Composable exits: `profit_target`, `stop_loss` (on net premium), `time_stop`, `roll_at_dte` (front leg). Exit fills at close − per-pair exit slippage; $0.65/contract/side commissions.
- `run_portfolio` minimal shared loop (flat sizing; sizing policy and signal generation deliberately stay with callers) + summary with the program-gate counters.
- Tests: 10, covering sign conventions, fill-at-limit, never-marketable, naive-fallback counting, stale carry, every exit rule, end-to-end P&L with commissions.

Follow-ups deliberately left for the first consuming prereg (P1B): strike/expiry selection helpers per structure family, and the P1D calibrated-inside-NBBO uplift column (blocked on P0B probes anyway).

## Commits

1. `fc1f8e2` — calendar builders + backfill runner
2. `f411fa9` — multi-leg harness + tests
3. integrity checker + staging/merge runner rev + run logs + this report (final)
