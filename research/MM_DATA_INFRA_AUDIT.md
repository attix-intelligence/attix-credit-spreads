# EXP-MM-1 — Market-Making Data & Infra Audit + Backtest Feasibility

**Date:** 2026-06-21
**Author:** Research sprint (data/infra audit)
**Question:** With our current data and code, can we realistically backtest, profit from, and run market making (MM) on $1,000,000 capital?
**Method:** Direct inspection of files on disk. Every number below was produced by reading the actual files, not from memory. Commands and outputs are reproduced.

**Bottom line up front:** We have **no equity quote data at all**, and our only options *quote* (bid/ask) data is **hourly** — roughly 3–4 orders of magnitude too coarse for genuine market making. The existing "MM sim" is a 100% synthetic Monte-Carlo toy that has never touched a real price. Equity MM backtesting is **impossible** with what we have; options MM backtesting is possible only as a crude, optimistic approximation, not a credible simulation of a real quoting business.

---

## 1. CBOE options data — `data/cboe_complete/{spx,spy,qqq}`

### 1.1 Layout

```
data/cboe_complete/
├── spx/   512M   408 files
├── spy/   248M   396 files
└── qqq/   216M   379 files          (total ~976M, 1183 .gz files)
```

Each symbol is split into **8 DTE (days-to-expiry) buckets**, identical across symbols:

```
{symbol}/{0dte,1dte,2dte,3dte,5dte,7dte,14dte,30dte}/YYYY-MM.csv.csv.gz
```

So the data is **not** a full continuous option chain. It is pre-filtered snapshots grouped by how many days each contract had left until expiry, with one gzipped CSV per calendar month per bucket. (`.csv.csv.gz` double-extension is a naming artifact from the download pipeline, not two files.)

### 1.2 File type & schema

All 1183 files are gzipped CSV (`.gz`). Schema is **identical** across spx / spy / qqq (verified by reading headers from all three):

```
ticker, expiration, strike, option_type, timestamp,
open, high, low, close,                          ← TRADE price OHLC
bid_open, bid_high, bid_low, bid_close,          ← BID quote OHLC  ✅
ask_open, ask_high, ask_low, ask_close,          ← ASK quote OHLC  ✅
delta, gamma, theta, vega, rho, iv,              ← greeks
volume, open_interest, underlying_price
```

**We DO have quotes** — explicit `bid_*` and `ask_*` columns (OHLC of the quote within each bar), plus greeks and IV. This is genuinely better than trade-only data. The catch is the bar frequency (next section).

Sample rows (SPY, 0dte, 2024-01, head):

```
SPY,2024-01-02,402.0,C,2024-01-02 10:00:00, ... bid_close=69.62 ask_close=71.55 ... delta=0.9847
SPY,2024-01-02,402.0,P,2024-01-02 10:00:00, ... bid_close=0.0  ask_close=0.01  ... delta=-0.0008
```

Greeks are populated on liquid contracts (SPY/QQQ rows above; SPX 30dte rows show delta≈1.0, iv≈2.05, etc.). Deep ITM/OTM rows often carry zeros for greeks and one-sided quotes (e.g. `bid=0`), which is realistic — no resting bid on a worthless option.

### 1.3 GRANULARITY — the decisive finding

The `timestamp` column is **hourly**. For a single contract across one day, the *complete* set of bars is:

```
10:00:00  11:00:00  12:00:00  13:00:00  14:00:00  15:00:00  16:00:00  16:15:00
```

That is **7 hourly bars + one 16:15 settlement bar = ~8 snapshots per trading day**. Confirmed by listing every distinct time-of-day value in a full monthly file — there are only those eight.

Two important consequences:
- The session **starts at 10:00, not 09:30** — we are missing the opening 30 minutes entirely (often the most active MM window).
- Within each hour we get OHLC of the bid and ask, so we know the *range* the quote traversed, but not the *path* or *when* inside the hour.

**Hourly is fundamentally incompatible with market making.** A real options MM re-quotes on the order of milliseconds-to-seconds and turns inventory many times per minute. Hourly snapshots cannot represent quote updates, queue dynamics, or fills between snapshots.

### 1.4 Date range & gaps

Range per symbol (from monthly filenames, 0dte bucket):

| Symbol | First | Last | Months present (0dte) |
|--------|-------|------|----------------------|
| SPX | 2021-02 | 2025-12 | 48 |
| SPY | 2021-02 | 2025-12 | 48 |
| QQQ | 2021-04 | 2025-12 | 46 |

The series is **not gap-free**. SPX 0dte months actually present:

```
2021: 02 03 04 06 07 08 09 10 11 12        (missing 05)
2022: 02 03 04 05 06 07 08 09 11 12        (missing 01, 10)
2023: 02 03 05 06 08 09 10 11 12           (missing 01, 04, 07)
2024: 01 02 03 04 05 07 08 10 11 12        (missing 06, 09)
2025: 01 04 05 06 07 08 09 10 12           (missing 02, 03, 11)
```

~10 calendar months are missing across the window. Any backtest must treat the dataset as discontinuous and not assume a clean daily index.

### 1.5 Row volume

Files are small (monthly CSVs ~90KB–250KB gzipped; e.g. SPX 0dte 2024-01 = 2,657 rows). This is consistent with hourly granularity × a filtered strike set, not a full tick chain. The whole 976MB corpus is "wide but shallow in time": many strikes/expiries, very few timestamps per day.

---

## 2. `data/options_cache.db` — 993 MB SQLite

No `sqlite3` CLI is installed in this environment; inspected via Python `sqlite3`. Four tables:

| Table | Rows | Quotes? | What it is |
|-------|------|---------|------------|
| `option_daily` | 6,278,985 | ❌ no bid/ask | Daily trade OHLC + volume + OI |
| `option_intraday` | 1,591,036 | ❌ no bid/ask | 5-minute trade OHLC + volume |
| `option_contracts` | 276,221 | n/a | Contract reference (ticker/expiry/strike/type) |
| `lost_and_found` | 347,900 | n/a | **SQLite corruption-recovery artifact** |

### 2.1 `option_intraday` — 5-minute TRADE bars, no quotes

```
contract_symbol, date, bar_time, open, high, low, close, volume
```

Sample:
```
O:SPY221104C00369000  2022-10-03  09:40  8.20 8.20 8.20 8.20  vol=5
O:SPY221104C00369000  2022-10-03  09:45  8.54 8.54 8.54 8.54  vol=1
```

- `bar_time` is on a **5-minute grid** (09:30, 09:35, 09:40, … through the session). Higher resolution than the CBOE hourly data, **but**:
- **There is no bid or ask.** These are *trade prints* only. The `O:SPY…` symbology is Polygon-format, i.e. this is Polygon aggregate trade data.
- Bars are **sparse / event-driven** — a bar exists only where a trade occurred. Bar counts taper off through the day (09:30 → 34,701 rows; 11:55 → 16,325 rows), confirming these are realized trades, not a continuous quote feed.
- Range: **2020-01-02 → 2026-02-24**.

### 2.2 `option_daily` — daily trade OHLC, no quotes

```
contract_symbol, date, open, high, low, close, volume, open_interest
```

- No bid/ask. Daily resolution.
- `open_interest` is frequently `NULL` in samples.
- Date range reported as `0000-00-00 → 2026-04-02` — the `MIN` is a **garbage/sentinel date**, so date hygiene is imperfect and must be filtered.

### 2.3 `option_contracts` — reference, broad underlying coverage

Top underlyings by contract count: SPY (193,272), QQQ (23,022), XLI (17,287), GLD (14,738), TLT (10,749), XLF (9,256), SOXX, XLK, XLE, … Useful as a contract dictionary; carries no prices.

### 2.4 `lost_and_found`

347,900 rows with columns `rootpgno, pgno, nfield, id, c0…c4`. This is the table name SQLite's `.recover` / corruption-recovery process creates. Its presence means **this DB has been through a corruption-recovery at some point** — a data-integrity caveat worth noting before relying on it.

### 2.5 Verdict on the DB

`options_cache.db` is a **trade-history** store (daily + 5-min prints). It contains **zero quote (bid/ask/NBBO) data**. It is useless as a primary source for MM, which is a quoting business — you cannot model where to post or whether you'd get filled from trade prints alone. Its only MM-adjacent use is as a *reference* for which contracts traded and at what realized prices (e.g. to estimate volume/toxicity).

---

## 3. Existing market-making code

`grep -riE "avellaneda|stoikov|market_mak|quoting" --include=*.py` (excluding `.venv`) returns:

```
compass/archive/market_making_sim.py        (571 lines)   ← generates reports/market_making_sim.html
compass/archive/market_maker.py             (Avellaneda-Stoikov simulator)
compass/exp2020_cross_vol_arb.py            (vol-arb, not MM)
tests/archive/test_market_making_sim.py
tests/archive/test_market_maker.py
```

Note both MM modules live under **`archive/`** — they are not part of the live strategy code, they are shelved experiments.

### 3.1 What `market_making_sim.py` actually does

It is a clean implementation of the **Avellaneda-Stoikov (2008)** optimal-quoting model, and it is **100% synthetic Monte-Carlo**. The core:

- **Reservation price:** `r = mid − q·γ·σ²·(T−t)` (`reservation_price`)
- **Optimal half-spread:** `δ* = γ·σ²·(T−t) + (2/γ)·ln(1+γ/k)` (`optimal_spread`)
- **Fill intensity:** `λ(δ) = A·exp(−k·δ)` (`fill_probability`)

The simulation loop (`run()`):
1. Walks over a `mid_prices` series, 1-minute steps (`dt = 1/390`).
2. Each step computes a bid/ask from the AS formulas.
3. Decides whether the bid/ask got hit by drawing a **uniform random number** against the Poisson fill probability (`self.rng.random() < bid_lambda`). Fills are coin-flips, not real counterparties.
4. **Adverse selection is a coin flip too:** with `adverse_fraction = 0.15`, a filled order is randomly marked "adverse" and the fill price is nudged by a fixed `adverse_move = 0.002`. There is no information event, no order-flow toxicity, no real price reaction.
5. Tracks cash/inventory, computes mark-to-market PnL, Sharpe, drawdown, and renders an HTML report with PnL/inventory/spread charts.

**Where do the prices come from?** Either `from_random_walk()` (synthetic GBM) or, in tests, `_flat_prices()` (constant price). Searching for every caller of `MarketMakingSim` / `from_random_walk` finds **only the test file**. **The simulator has never been fed a single real market price.** It is a parameter-driven illustration of the AS equations, not a backtest.

`market_maker.py` (the sibling archived module) is the same idea with extra bells (volatility-regime-adaptive spread, "toxicity scoring", PnL decomposition) and its own header explicitly states *"This is READ-ONLY simulation. No broker connections, no trade placement."* — again, synthetic.

### 3.2 Relationship to the rest of the repo

This matters culturally: `CLAUDE.md` carries an explicit **Carlos directive — "NEVER use heuristic or synthetic data."** The existing MM sim is *entirely* synthetic, which is precisely why it sits in `archive/`. It cannot be promoted to a real backtest by tuning parameters; it would have to be rebuilt around real data and a real fill model.

---

## 4. VERDICT — can we backtest / profit from MM with $1MM?

### 4.1 Equity market making — **NO. Not possible with current data.**

We hold **no equity quote or trade data whatsoever.** Everything on disk is *options*. The CBOE files carry a single `underlying_price` scalar per row (a reference mark), not an equity bid/ask, not a depth book, not a trade tape. There is literally nothing to quote against for SPY/QQQ/SPX shares. Equity MM backtesting is off the table until we acquire equity NBBO / L2 data.

### 4.2 Options market making — **technically possible, but only as a crude, optimistic toy.**

We *can* build something that consumes the CBOE `bid_*`/`ask_*` columns and simulates posting inside the spread. But it would be a weak approximation, severely limited by the data:

- **Hourly quotes** (CBOE) — the only quote source — are ~3–4 orders of magnitude too coarse. Real options MM re-quotes sub-second; modeling it on 8 snapshots/day is like backtesting an HFT strategy on monthly closes. Intra-hour quote movement, the thing MM lives and dies on, is invisible.
- **5-minute bars** (`option_intraday`) are finer but have **no bid/ask**, so they can't tell you where to post or whether a passive order would fill — only that *someone* traded.
- We would be forced to **assume fills** rather than simulate them, which structurally biases PnL upward (you "capture the spread" without ever losing the queue race or being adversely picked off by faster quoters).

So a deliverable is feasible, but it must be labeled what it is: an *order-of-magnitude profitability sketch*, not evidence the strategy works.

### 4.3 The single biggest data gap

**We have no order-book / event-level quote data, and therefore no way to build a credible fill or queue model.** Concretely, all of the following are absent:

1. **No L2 / depth-of-book** — we never see resting size at each price level, so queue position (who gets filled first) is unknowable. This alone makes passive-fill modeling guesswork.
2. **No tick / sub-second quote stream** — the finest *quote* data we have is **hourly**. Fill timing, quote flicker, and adverse-selection windows all happen far below this resolution.
3. **No trade-to-quote linkage / NBBO timeline** — we can't tell whether a print at 09:42 hit a bid or lifted an ask, nor reconstruct the NBBO the instant before each trade.

If forced to name *one*: **the absence of event-level (tick) NBBO + order-book depth, which makes a realistic fill/queue model impossible.** Spread capture in MM *is* the fill model; without it every PnL number is assumption-driven.

### 4.4 Honest framing for the $1MM question

- **Can we backtest equity MM?** No — zero equity data.
- **Can we backtest options MM?** Only crudely, on hourly quotes, with assumed fills. The result would not be trustworthy enough to commit $1MM against.
- **Would the existing sim tell us anything?** No — it's synthetic and has never seen a real price; its PnL is a function of its own random seed and parameters.
- **What would it take to do this for real?** A tick-level options quote/NBBO feed (and an equity NBBO/L2 feed if equity MM is in scope), plus a fill/queue model built on that. That is a **data-acquisition problem first**, a coding problem second.

---

## Appendix — commands used (reproducible)

```bash
# Layout & sizes
du -sh data/cboe_complete/*                      # spx 512M, spy 248M, qqq 216M
find data/cboe_complete/spx -type f | wc -l      # 408 (.gz)

# Schema & granularity
zcat data/cboe_complete/spx/0dte/2024-01.csv.csv.gz | head -1
zcat data/cboe_complete/spx/0dte/2024-01.csv.csv.gz \
  | awk -F',' 'NR>1{split($5,a," ");print a[2]}' | sort -u   # only 8 hourly times

# SQLite (via python3 sqlite3 — no sqlite3 CLI present)
#   option_daily 6,278,985 rows  (daily trade OHLC, no bid/ask)
#   option_intraday 1,591,036 rows (5-min trade OHLC, no bid/ask), 2020-01-02..2026-02-24
#   option_contracts 276,221 rows  (reference)
#   lost_and_found 347,900 rows    (corruption-recovery artifact)

# MM code
grep -riE "avellaneda|stoikov|market_mak|quoting" --include=*.py -l .   # all under archive/
```

*All figures above were read from the live files on 2026-06-21. No values were estimated or fabricated.*
