# CC1 REPORT — EXP-3400 Data Validation & Rule Zero Audit

**Author:** CC1
**Date:** 2026-05-25
**Scope:** Verify that IronVault (`data/options_cache.db`) supports EXP-3401 and EXP-3402 as designed.
**Verdict:** 🔴 **BLOCK — EXP-3401 and EXP-3402 cannot proceed against this dataset.**

---

## 1. Data Audit Findings

### 1.1 Database location & size
- Path: `data/options_cache.db`
- Size: 978 MB
- Last modified: 2026-04-06
- Engine: SQLite

### 1.2 Actual schema (not the assumed `options` table)

The database has four tables:

```
option_contracts  (276,221 rows)
  ticker, expiration, strike, option_type, contract_symbol, as_of_date
  -- "as_of_date" is the metadata fetch date, NOT a trade date

option_daily      (6,278,985 rows)
  contract_symbol, date, open, high, low, close, volume, open_interest

option_intraday   (1,591,036 rows)
  contract_symbol, date, bar_time, open, high, low, close, volume

lost_and_found    (housekeeping)
```

There is **no** `options` table with `underlying_symbol`, `quote_date`, `expiration_date`, `bid`, `ask`, or `delta` columns. The task's query template referenced those; none exist.

### 1.3 Underlying ticker coverage

```
SPY     193,272 contracts
QQQ      23,022
XLI      17,287
GLD      14,738
TLT      10,749
XLF       9,256
SOXX      3,460
XLK       2,680
XLE       1,757

SPX, SPXW, ^SPX, I:SPX:   0 rows each
```

Confirmed by `SELECT COUNT(*) FROM option_contracts WHERE ticker IN ('SPX','SPXW','^SPX','I:SPX')` → **0**.

### 1.4 0DTE coverage (SPY — closest available analog)

Join: `option_daily.date = option_contracts.expiration` (the 0DTE invariant).

| Year | Bars | Distinct trading days | Date range |
|---|---|---|---|
| 2023 | 8,216 | **52** | 2023-01-06 → 2023-12-29 |
| 2024 | 10,423 | **59** | 2024-01-05 → 2024-12-31 |

A normal trading year has ~252 sessions. SPY 0DTE is present on **21–23%** of them — roughly one day per week, not daily. Coverage is sampled, not exhaustive.

### 1.5 Rule Zero quality scan (SPY 0DTE bars, ≥ 2023-01-01)

| Check | Count | % of total |
|---|---|---|
| Total bars | 33,417 | 100.00% |
| Flat OHLC (open=close AND high=low) | 12,381 | 37.05% |
| Zero volume | 0 | 0.00% |
| NULL close | 0 | — |
| Close ≤ 0 | 0 | — |
| High < Low (inverted) | 0 | — |

A 37% flat-OHLC rate is high but plausible for deep-OTM 0DTE penny strikes that genuinely don't move on the day. Not flagged as synthetic without corroborating evidence. The script's synthetic-spread heuristics (`ask-bid == 0.05`, `bid == ask`, `ask/bid == 1.01`) are **not applicable** because the bid/ask columns do not exist.

### 1.6 Spot check — 5 random SPY 0DTE bars

```
date         strike  type   open    high    low     close    vol      oi
2026-01-23   700.0   C      0.01    0.01    0.01    0.01    1006    NULL
2025-08-29   602.0   C     43.85   43.85   41.61   42.36      17    NULL
2025-10-31   681.0   P      0.56    2.45    0.01    0.02   323439   NULL
2025-09-05   375.0   C    271.21  271.43  271.20  271.28       5    NULL
2025-01-31   596.0   C     11.46   13.94    5.21    5.87     293    NULL
```

`open_interest` is partially NULL — any OI-based filter will silently drop rows.

---

## 2. Why EXP-3401 and EXP-3402 Cannot Proceed

EXP-3401 and EXP-3402 are SPX credit-spread strategies that require, at minimum:

1. **SPX option chains** (the index, not the SPY ETF — different multiplier, no dividend exposure, cash-settled, different liquidity profile, different tax treatment).
2. **Bid/ask quotes** to model realistic fill prices and slippage (mid, mid - k·spread, limit-at-bid, etc.).
3. **Delta** for strike selection (e.g., "short the 10Δ put, long the 5Δ put").

The IronVault database supplies **none of those three**:

| Required input | Available in `options_cache.db`? | Rule Zero blocker? |
|---|---|---|
| SPX chains 2023–2024 | ❌ No — only SPY/QQQ/sector ETFs | Cannot substitute without changing the strategy |
| Bid/ask spreads | ❌ No — schema is OHLCV-only | Synthesizing `bid/ask = close ± k` violates Rule Zero |
| Delta / Greeks | ❌ No — no delta/IV/gamma/theta/vega anywhere | Black-Scholes-inverting delta from close injects a model and a synthetic IV assumption — Rule Zero violation |
| Daily 0DTE bars | ⚠️ Sparse for SPY (~22% of days); SPX absent entirely | Backfilling missing days = synthetic |

Even if EXP-3401/3402 were re-scoped to SPY, the missing bid/ask and delta are still hard blockers. Reconstructing them from close prices requires assumptions (mid-spread heuristic, BS-inversion with assumed IV) that fall on the wrong side of Rule Zero ("NO SYNTHETIC DATA EVER").

**Conclusion:** Running EXP-3401 or EXP-3402 against this database produces a backtest whose entry prices, exit prices, and strike selection are all model-derived. The Sharpe ratio of such a backtest measures the model, not the strategy.

---

## 3. Three Options Forward

### Option A — Re-scope to SPY 0DTE, source bid/ask + delta externally
- **Action:** Change EXP-3401/3402 underlier from SPX to SPY. Acquire bid/ask and delta from a quote-level source (Polygon options snapshots, CBOE DataShop EOD greeks, Theta Data).
- **Cost:** Strategy edge must be re-validated on SPY — ETF dynamics are not equivalent (dividends, multiplier 100 vs 100, but tax treatment, settlement, and pin-risk all differ). Sparse 0DTE day coverage (~22%) remains a problem unless backfilled from the new source.
- **Risk:** Two new dependencies (data source + re-validation) before any backtest result is meaningful.
- **Rule Zero:** Compatible if and only if the new source supplies real quotes — no interpolation.

### Option B — Acquire SPX chains from a primary source
- **Action:** Subscribe to / pull from a source that publishes SPX/SPXW with bid/ask and greeks. Candidates: Polygon options (verify the current plan's SPX entitlement first), CBOE DataShop, Theta Data, ORATS. Backfill 2023–2024 then run EXP-3401/3402 as originally designed.
- **Cost:** Data subscription (likely $-thousands/year for full greeks history), ingest pipeline work (new loader, schema additions to `options_cache.db` or a separate DB), QA pass against a known reference.
- **Risk:** Longest path. Data-quality issues from the new source need their own audit before strategy results are trusted.
- **Rule Zero:** Cleanest fit. Real SPX, real quotes, real greeks.

### Option C — Suspend EXP-3401/3402 pending data acquisition
- **Action:** Park both experiments. Redirect EXP-3400's CC2–CC5 sessions to strategies whose data needs IronVault already meets (SPY/QQQ/sector ETFs with OHLCV-only models, e.g., directional underlying strategies or vol-of-vol overlays that don't require option quotes).
- **Cost:** Delay. No SPX credit-spread research advances until Option A or B unblocks.
- **Risk:** Low. No false-confidence backtest published.
- **Rule Zero:** Trivially compatible. Nothing is run on missing data.

---

## 4. Recommendation

**Option C in the short term, transitioning to Option B.**

Rationale:
1. **Option A** trades one set of data problems (no bid/ask, no delta on SPX) for two new ones (a different underlier and a still-required external quote source). The re-validation work is large and the result is no longer the SPX strategy that was scoped.
2. **Option B** is the only path that produces a backtest of EXP-3401/3402 as designed. It's the most expensive, but it's also the only one whose output is interpretable. The data subscription cost is small relative to the cost of trading a strategy whose backtest used synthetic inputs.
3. **Option C** prevents Rule Zero violations during the gap and keeps the rest of the audit moving on data the DB actually supports.

Concrete next steps:
1. **Today:** Mark EXP-3401 and EXP-3402 as `data_blocked` in the experiment registry. Do not start any backtest runs against `options_cache.db` for these IDs.
2. **This week:** Inventory primary SPX-chain sources (Polygon plan check first — it's the cheapest test). Capture the bid/ask + greeks fields each source provides and the historical depth.
3. **Before unblocking:** Define an ingestion schema upgrade (`options_cache.db` gets `bid`, `ask`, `delta`, `gamma`, `theta`, `vega`, `iv` columns, or a parallel `option_quotes` table) and a Rule Zero-compatible loader that fails closed on missing fields rather than interpolating.
4. **Watchdog:** Add a CI assertion that any code path referencing SPX 0DTE in IronVault raises rather than silently returning empty — so this gap cannot be re-introduced as a silent zero-row backtest.

Sign-off: 🔴 **DO NOT RUN** EXP-3401 or EXP-3402 against `data/options_cache.db` in its current shape.
