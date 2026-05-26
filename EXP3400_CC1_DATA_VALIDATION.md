# EXP-3400 CC1 — Data Validation & Rule Zero Enforcement

**Date:** 2026-05-25
**DB:** `data/options_cache.db` (978 MB, mtime 2026-04-06)
**Scope:** IronVault SPX 0DTE data quality, 2023-2024
**Verdict:** 🔴 **BLOCK — data does not match EXP-3400 assumptions**

---

## TL;DR

EXP-3400 assumes IronVault contains **SPX 0DTE chains with bid/ask spreads and delta**. The actual database contains **none of those three things**:

| Assumption | Reality |
|---|---|
| SPX 0DTE chains 2023-2024 | ❌ **Zero SPX rows** — only SPY/QQQ/XLI/GLD/TLT/XLF/SOXX/XLK/XLE |
| Bid/ask spreads | ❌ Schema is OHLCV-only — no `bid`/`ask` columns in `option_daily` or `option_intraday` |
| Delta / Greeks | ❌ No `delta`, `gamma`, `theta`, `vega`, or `iv` columns anywhere |
| Continuous 0DTE coverage | ⚠️ SPY 0DTE only on **52 days in 2023** and **59 in 2024** (~21-23% of trading days) |

Any backtest of an SPX 0DTE credit-spread strategy using this database would be impossible without:
1. Substituting SPY (different multiplier, different liquidity, dividend exposure), AND
2. **Synthesizing bid/ask from close ± a fudge factor** — explicit Rule Zero violation, AND
3. **Synthesizing delta from Black-Scholes inversion** — model-derived, not market-observed

---

## Actual schema

`options_cache.db` has 4 tables (not the single `options` table assumed by the CC1 script):

```
option_contracts (276,221 rows)
  ticker, expiration, strike, option_type, contract_symbol, as_of_date
  ^^ "as_of_date" is the metadata fetch date — NOT a trade date

option_daily     (6,278,985 rows)
  contract_symbol, date, open, high, low, close, volume, open_interest

option_intraday  (1,591,036 rows)
  contract_symbol, date, bar_time, open, high, low, close, volume

lost_and_found
```

**No bid. No ask. No delta. No IV.**

---

## Underlying coverage (option_contracts.ticker)

```
SPY     193,272
QQQ      23,022
XLI      17,287
GLD      14,738
TLT      10,749
XLF       9,256
SOXX      3,460
XLK       2,680
XLE       1,757
SPX           0   ← absent
SPXW          0   ← absent
```

Confirmed via `SELECT COUNT(*) FROM option_contracts WHERE ticker IN ('SPX','SPXW','^SPX','I:SPX')` → **0**.

---

## SPY 0DTE coverage (closest available analog)

Join semantics: `option_daily.date = option_contracts.expiration` (NOT `as_of_date`).

| Year | Bars | Distinct trading days | Range |
|---|---|---|---|
| 2023 | 8,216 | **52** | 2023-01-06 → 2023-12-29 |
| 2024 | 10,423 | **59** | 2024-01-05 → 2024-12-31 |

~252 trading days per year — coverage is roughly **one day per week**, not daily. Likely sampled, not exhaustive.

---

## Rule Zero quality scan (SPY 0DTE bars ≥ 2023-01-01)

| Check | Count | % |
|---|---|---|
| Total bars | 33,417 | 100.00% |
| Flat OHLC (open=close, high=low) | 12,381 | **37.05%** |
| Zero volume | 0 | 0.00% |
| NULL close | 0 | — |
| Close ≤ 0 | 0 | — |
| High < Low (inverted) | 0 | — |

**Flat-OHLC rate of 37%** is high but plausible for deep-OTM 0DTE penny strikes — those genuinely don't move on the day. Not a synthetic-data smoking gun on its own, but worth pairing with a volume/OI inspection before trusting it for fills.

The synthetic-spread heuristics in the original CC1 script (`ask-bid == 0.05`, `bid == ask`, `ask/bid == 1.01`) are **not applicable** — bid/ask columns do not exist.

---

## Sample 5 random SPY 0DTE bars (post-2024)

```
date         strike  type   open    high    low     close   vol      oi
2026-01-23   700.0   C      0.01    0.01    0.01    0.01    1006     —
2025-08-29   602.0   C     43.85   43.85   41.61   42.36     17     —
2025-10-31   681.0   P      0.56    2.45    0.01    0.02   323439   —
2025-09-05   375.0   C    271.21  271.43  271.20  271.28      5     —
2025-01-31   596.0   C     11.46   13.94    5.21    5.87    293     —
```

`open_interest` returns NULL on these rows — the column is populated for some bars but not others. Spot check before relying on OI filters.

---

## Findings (severity)

### 🔴 CRITICAL — blocks EXP-3400 as written
- **C1:** No SPX data. EXP-3400 cannot run against IronVault for SPX. Either re-scope to SPY (and re-validate strategy edge on the ETF) or source SPX chains elsewhere (CBOE DataShop, OPRA via Polygon options endpoints, Theta Data).
- **C2:** No bid/ask. Any backtest fill model that quotes "mid - slippage" or "limit at bid + 0.05" is unimplementable from this dataset without synthesis. Rule Zero prohibits synthesis.
- **C3:** No delta. Delta-targeted strike selection (e.g., "10-delta short, 5-delta long") is unimplementable without Black-Scholes inversion of close prices, which is model-derived and silently injects an IV assumption.

### 🟡 HIGH
- **H1:** SPY 0DTE coverage is sparse (~21-23% of trading days). A daily-cadence strategy backtest will skip 80% of the period, biasing results.
- **H2:** `open_interest` is partially NULL — filters using it will silently drop rows.

### 🟢 PASS
- No NULL/negative closes, no inverted high/low bars, no zero-volume contamination.
- 37% flat-OHLC bars are consistent with legitimate deep-OTM 0DTE penny-strike behavior; not flagged as synthetic without further evidence.

---

## Recommendation

**Do not proceed with EXP-3400 against this database for SPX 0DTE.**

Three viable paths:

1. **Re-scope to SPY 0DTE** — accepting that the strategy edge must be re-validated on SPY's different liquidity/dividend profile, and accepting the sparse 0DTE coverage. Still need an external bid/ask + delta source.
2. **Add an SPX chain source** — Polygon options aggregates do publish SPX/SPXW chains on entitled plans; verify the existing `PolygonClient` plan tier before assuming it works.
3. **Suspend EXP-3400 pending data acquisition** — the cleanest Rule Zero outcome.

What this audit explicitly will NOT do: substitute synthetic bid/ask or Black-Scholes-inverted delta. That is the Rule Zero line.
