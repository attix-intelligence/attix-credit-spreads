# CC4 AUDIT — Data Integrity & Rule Zero Compliance

Date: 2026-05-22
Scope: `pilotai-credit-spreads/` (compass + shared + backtest)
Focus: IronVault reader, Yahoo loaders, FOMC/futures calendars, 8-stream data availability,
       Rule Zero compliance.

---

## 0. Note on the requested file paths

The two files named in the audit brief — `compass/data_loader.py` and `compass/yahoo_downloader.py` —
**do not exist**. There is no centralised data-loader module. Data loading is scattered across
~30 experiment scripts; each experiment fetches Yahoo / loads pickles / consults IronVault
directly. The audit therefore traces the *de-facto* data paths:

| Concern                       | Actual location |
|-------------------------------|-----------------|
| IronVault options DB reader   | `shared/iron_vault.py` → `backtest/historical_data.py` |
| Yahoo ETF prices              | `compass/exp1770_commodity_calendars.py::fetch_close`, `compass/exp2690_signal_generators.py::_fetch_yahoo_close`, `compass/exp3303_regime_transition_dd.py::fetch_regime_features`, `compass/exp3311_runner.py::_ensure_exp1220_trades` (inline) |
| ^VIX                          | `compass/vix_ladder.py::fetch_vix` (top-level helper used by EXP-2850 / 3311 / 3312) |
| ^VIX3M / ^VVIX / ^SKEW        | `compass/exp3303_regime_transition_dd.py::fetch_regime_features` (cached) |
| FOMC calendar                 | `shared/constants.py::FOMC_DATES` (hand-maintained) |
| Futures roll dates GC=F, SI=F | **None — relies on Yahoo continuous splice** (see §5) |
| 8-stream cube                 | `compass/exp3311_runner.py::build_baseline_cube` → pickles + `compass/exp2080_corr_regime.py::load_streams` |

The audit findings below are organised by data path.

---

## 1. IronVault DB reader — `shared/iron_vault.py`

**Loads correctly.** Hard-fails on missing/empty DB (lines 73-98). Singleton pattern in
`IronVault.instance()` reads `POLYGON_API_KEY` from env but uses `offline_mode=True` so no
live calls.

### Findings
- ✅ **No synthetic fallback.** Per-contract cache misses return `None`; caller skips trade.
  This is enforced by `HistoricalOptionsData(offline_mode=True)`.
- ⚠️ **Validity check is shallow.** `_validate_has_data()` (line 84) only checks
  `SELECT COUNT(*) FROM option_contracts`. **It does not verify date coverage, freshness,
  or per-ticker completeness.** A DB containing only 2020 SPY data would pass; running an
  EXP-2080 / EXP-3311 backtest against it would silently produce a heavily-biased cube
  (most streams empty, no error raised). Recommend a coverage gate: assert
  `MAX(date)` is within N days of today *and* per-ticker contract counts meet a floor.
- ⚠️ **No staleness check.** No "last successful backfill" timestamp is read. If the
  options_cache.db hasn't been updated in 3 weeks, `coverage_report()` won't flag it —
  paper trading would emit signals on stale option chains.
- ⚠️ **`get_prev_daily_volume` returns None on cache miss → caller fails-open**
  (`historical_data.py:446`). The liquidity gate is therefore opt-in only; a missing-volume
  cache silently permits illiquid trades to enter.

### Failure mode if DB is stale or missing
- **Missing**: `IronVaultError` raised at process start. Clean failure. ✅
- **Empty**: `IronVaultError` raised. Clean. ✅
- **Stale (e.g. last entry 2024-12)**: **No error.** A 2025 backtest produces a sparse cube
  (most trades skip on cache miss). Reports show inflated Sharpe because fewer trade samples
  pass the filter. **This is the most dangerous silent-failure mode.**
- **Partial coverage (some tickers missing)**: No error. Stream-specific entries silently
  return zero P&L.

---

## 2. Yahoo loaders — VIX, VIX3M, ETF prices

### 2.1 `compass/vix_ladder.py::fetch_vix` (production VIX feed for EXP-2850 / 3311 / 3312)

```python
df = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False)
if df is None or df.empty:
    return pd.Series(dtype=float)        # <- silent empty return
```

**🔴 RULE-ZERO-ADJACENT BUG.** If Yahoo returns empty (rate-limit / network / outage),
`fetch_vix` returns an empty Series with **no warning, no exception**. The caller
(`VIXLadder.apply`) then takes the NaN-path:

```python
# vix_ladder.py:99-100, 144-145
nan_mask = np.isnan(arr)
raw = np.where(nan_mask, self.max_exposure, raw)   # silent fallback to 1.0
```

Behaviour when the network is down or Yahoo is throttling:
- VIX series empty → reindexed to portfolio index, all NaN → ladder returns 1.0 everywhere.
- **The flash-crash protection ladder turns OFF silently.** EXP-2820's flash-crash DD
  saving (43.1% → 0.80%) is invalidated.
- No log line, no metric, no error. Backtest run prints normally.

Recommendation: raise on empty Yahoo result; or have `apply()` fail-closed (return 0.0
exposure / refuse to run) on NaN. The docstring of `exposure_at` calls 1.0 a "permissive
fallback" — that is the wrong default for a risk-control layer.

### 2.2 `compass/exp3303_regime_transition_dd.py::fetch_regime_features` (VIX3M / VVIX / SKEW)

Cache-first; if cache covers the requested range it's returned, otherwise refetched from
Yahoo. `raw = raw.ffill().dropna()` is acceptable on these slow-moving series, but:
- **No staleness guard on the cache.** If the pickle is from 2024 and the backtest range is
  2025-2026, the `if df.index.min() <= start and df.index.max() >= end` check **does** catch
  it (lines 108-112). ✅
- However, the gate `apply_regime_gate` (line 159-163) explicitly sets `leverage=1.0` when
  composite is NaN (warm-up). Documented, but means **the first ZSCORE_WINDOW days have no
  gate** — could be hidden source of inflated SR if fold boundaries land in warm-up zones.

### 2.3 `compass/exp3311_runner.py::_ensure_exp1220_trades` (inline Yahoo for SPY + ^VIX)

Lines 162-194: imports yfinance inline, downloads SPY and ^VIX, then calls
`run_exp1220_trades(hd, spy_df, vix_s)`. No fail-fast guard if either series is empty;
the downstream `run_exp1220_trades` will `continue` past missing-data rows and just
generate fewer trades. **Silent data degradation possible.**

### 2.4 `compass/exp1770_commodity_calendars.py::fetch_close` (GLD/SLV/GC=F/SI=F)

```python
df = yf.download(symbol, ...)
if df is None or len(df) == 0:
    raise RuntimeError(f"Yahoo empty for {symbol}")
```

✅ Fail-fast. Good. Different from `fetch_vix` which silently returns empty.

**Inconsistency:** the project has two Yahoo helpers with opposite failure semantics
(`fetch_close` raises, `fetch_vix` returns empty, `_fetch_yahoo_close` returns empty). This
makes failure behaviour depend on which experiment loaded the data — a footgun.

---

## 3. Rule Zero compliance — synthetic / random / heuristic

### 3.1 `BACKTEST_CREDIT_FRACTION` — heuristic pricing constant still in tree

```python
# shared/constants.py:93
BACKTEST_CREDIT_FRACTION = 0.35

# deploy/macro-api/shared/constants.py:53   (duplicate, used by macro-api deployment)
BACKTEST_CREDIT_FRACTION = 0.35
```

CLAUDE.md classifies any use of this constant as a **"critical bug"**. The constant is
*currently* dead-ish in the main backtester production path:
- `backtest/backtester.py:431,433,1749-1751` references only `credit_jitter`, which is
  *added on top* of a real credit obtained from IronVault — not a synthetic price by itself.
- `scripts/credit_sensitivity.py` and `scripts/run_monte_carlo.py` patch the constant for
  sensitivity studies. These are research scripts, not production paths.

But:
- ⚠️ The constant **is still exported** and the comment says "heuristic mode only", implying a
  dormant heuristic-mode code path exists somewhere. A grep of imports of the constant from
  `backtest/`, `engine/`, `strategy/`, `execution/` would confirm none are live — the audit
  did not exhaustively verify this.
- ⚠️ `deploy/macro-api/shared/constants.py` is a **separate copy** of the constants module
  shipped to a deployed service. If macro-api ever computes a backtest-style metric, it has
  the heuristic constant on hand.

### 3.2 `np.random` / `random` in production strategy code

All production strategy code (signals, position selection, exit logic) uses **real data
only**. The `np.random` usages located are confined to:

| Path | Role | Rule Zero status |
|------|------|------------------|
| `compass/exp3200_monte_carlo_stress.py` | MC stress test — paths simulated from real-calibrated MVN | ✅ legitimate stress framework, **not a P&L source** |
| `compass/exp3151_stream_attribution.py`, `exp3150_post2020_retest.py` | Bootstrap CI on real returns | ✅ statistical inference, not pricing |
| `compass/stress_test.py` | Stress scenario generator | ✅ as labeled |
| `compass/exp3290_overnight_entry_test.py` | RNG seed — needs spot-check | ⚠ verify it doesn't synthesise prices |
| `backtest/backtester.py:1750` | `credit_jitter` adds noise to **real** credit | ⚠ jitter only applies when `_mc_mode == 'full'` AND user opts in; defaults to 0 |
| `compass/archive/**` | various — archived/killed | n/a |
| `compass/experiments/killed/tests/test_exp1760_crypto_vol.py:87,103,104` | **Test fixtures using `np.random.normal` for price walks** | ⚠ in test code only, but easy to mistake for a real backtest if the file path is read carelessly |

None of these inject synthetic option prices into a live backtester P&L stream. **No
critical Rule Zero violation found in main production paths.**

### 3.3 Silent "expired-worthless = 0.0" assumption in exp1220

`compass/exp1220_standalone.py:103-104`:
```python
fp = hd.get_spread_prices("SPY", exp_dt_obj, short_k, long_k, "P", exp)
return exp, "expiration", (fp["short_close"] - fp["long_close"]) if fp else 0.0, hold
```

**⚠ Soft Rule Zero violation.** If IronVault has no expiration-day quote for the spread
(cache miss on the exact expiry date), the code silently treats the spread as **expired
worthless (cv=0.0)** → maximum profit for a put credit spread. This conflates "no data"
with a favourable outcome. The same pattern is **not** present at `_walk_spread` interim
days (those `continue` past the date instead of assuming a value). At expiration the
fallback is `0.0` because there is no further day to check, but:
- If the cache simply lacks the row, the trade earns the full credit. Result: **biased upward.**
- A correct behaviour would be to return `None` here too and skip the trade entirely.

This is a real Rule Zero footgun. Verify by counting how often `fp is None` fires in
recent runs (the trade tape is regenerated and pickled in
`compass/cache/exp3311_exp1220_trades.pkl`).

### 3.4 `is_blackout` window correctness — no Rule Zero issue, but minor concerns

- CPI uses **2nd Wednesday** as a deterministic proxy. Actual BLS CPI release days vary
  (sometimes 2nd Tuesday, sometimes 2nd Wednesday or even mid-month). Acknowledged in
  docstring, but **events landing on the actual day-of will be missed** in some months.
- NFP first-Friday assumption is correct except when BLS shifts due to a federal holiday
  (rare; happened e.g. Jan 2022 → 1st Friday was Jan 7 but BLS occasionally re-schedules).
- OpEx 3rd-Friday rule: correct.
- `coverage_stats` uses `pd.bdate_range` without a US holiday calendar (acknowledged).
  Affects diagnostic stats only.

---

## 4. 8-stream data availability

The 8 streams expected by EXP-2850 / 3311 / 3312:

| Stream    | Source | Hard-fail on missing? |
|-----------|--------|------------------------|
| `exp1220` | regenerated from IronVault via `_ensure_exp1220_trades` + cached at `compass/cache/exp3311_exp1220_trades.pkl` | ❌ no — proceeds with empty trade list if Yahoo SPY/VIX empty |
| `v5_hedge` | EXP-1850 cache (`exp1850_streams.pkl`) | ✅ regenerated by `load_real_streams` if missing |
| `gld_cal` | `exp1770_commodity_calendars` (Yahoo GLD + GC=F) | ✅ `fetch_close` raises on empty |
| `slv_cal` | same (SLV + SI=F) | ✅ |
| `cross_vol` | `exp2020_cross_vol_arb` trades + IronVault | depends on inner code (not audited here) |
| `xlf_cs` | `compass/cache/exp2200_xlf_trades.pkl` | ❌ `_load_pkl` will FileNotFoundError — **no informative error** |
| `xli_cs` | `compass/cache/exp2200_xli_trades.pkl` | same |
| `qqq_cs` | `compass/cache/exp2250_qqq_trades.pkl` | same |

**🔴 Missing data sanity gate.** `build_baseline_cube` (`exp3311_runner.py:207-241`) does
NOT validate stream completeness. If `exp2200_xlf_trades.pkl` is missing the
`FileNotFoundError` propagates without context. If a pickle exists but is from a stale run
(wrong date range), the resulting series silently produces sparse zeros over the
mismatched window → **inflated Sharpe denominator, deflated DD**. There is no assertion
that each stream has ≥ N non-zero days in the test range.

The runner does print `nz=...` per column (line 324) — a human eyeballing the log would
notice, but a CI pipeline would not.

---

## 5. Futures roll dates (GLD → GC=F, SLV → SI=F)

**🔴 No explicit roll handling.** `compass/exp1770_commodity_calendars.py:73-83` simply
calls `yf.download("GC=F")` and `yf.download("SI=F")`. These are Yahoo "continuous
front-month" tickers — Yahoo splices contracts internally with an undocumented methodology.

Risks introduced:
1. **Roll-day jumps in `fut_ret`.** The instant Yahoo switches from the front contract to
   the next, the price series can jump several percent. `df["spread_ret"] = etf_ret -
   fut_ret` (line 95) will then book a spurious *spread return* on roll day equal to that
   jump.
2. **Inconsistent splice convention across vendors.** Backtests built today may not
   reproduce in 6 months because Yahoo's roll dates have shifted.
3. **No documented roll calendar.** The literature on commodity ETFs (USO, UNG, GLD, SLV)
   typically rolls on a documented schedule (e.g. USO rolls between the 5th-9th business
   day of the month). The strategy is computing roll-yield (ETF − front future) without
   knowing when the future actually rolled — a fatal conceptual issue if the roll-yield
   *signal itself* is corrupted by Yahoo splice noise.

The module's docstring claims "all real, no synthetic prices (Rule Zero)" — technically
true, but the production-quality of `GC=F`/`SI=F` continuous series is unverified.
Recommend pinning to a known roll schedule (CME contract calendars) and stitching
back-adjusted manually, OR validating that Yahoo splice dates match CME.

---

## 6. FOMC calendar loading

- `shared/constants.py:103-169` is a hand-maintained list, 2020-2026.
- Lines 177-183 emit a `logging.warning` if `FOMC_DATES[-1] < now()`. ✅
- The list extends to **2026-12-09** — current date 2026-05-22 → not yet stale.
- Risk: this is a `logging.warning`, not an exception. A backtest run on 2027-01-15 would
  print the warning and proceed using the stale list — the event gate would simply have
  zero FOMC events in 2027 → no protection, no failure. **Permissive degradation.**

Recommend converting to a hard error when `now()` is within 60 days of `FOMC_DATES[-1]`.

---

## 7. Summary — issues ranked by severity

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | 🔴 HIGH  | `fetch_vix` silently returns empty Series on Yahoo failure → `VIXLadder.apply` falls back to exposure=1.0; flash-crash protection silently disabled | `compass/vix_ladder.py:179-194`, `:99-100,144-145` |
| 2 | 🔴 HIGH  | `exp1220._walk_spread` returns `0.0` (full profit) when expiration-day spread price is missing — conflates cache miss with expired-worthless | `compass/exp1220_standalone.py:103-104` |
| 3 | 🔴 HIGH  | Continuous futures `GC=F` / `SI=F` from Yahoo used directly with no roll calendar → roll-day price jumps contaminate `spread_ret` | `compass/exp1770_commodity_calendars.py:73-96` |
| 4 | 🔴 HIGH  | No stream-completeness gate in `build_baseline_cube`; stale or missing pickles produce silent zero-return windows that inflate Sharpe | `compass/exp3311_runner.py:207-241` |
| 5 | 🟠 MED   | IronVault `_validate_has_data` only checks `COUNT(*) > 0`; no per-ticker / date-range / staleness check | `shared/iron_vault.py:84-98` |
| 6 | 🟠 MED   | `BACKTEST_CREDIT_FRACTION = 0.35` still exported from `shared/constants.py` AND duplicated in `deploy/macro-api/shared/constants.py` — CLAUDE.md classifies this as a critical-bug footgun | `shared/constants.py:93`, `deploy/macro-api/shared/constants.py:53` |
| 7 | 🟠 MED   | `FOMC_DATES` staleness only warns; never errors. Backtests on 2027+ silently miss every FOMC event | `shared/constants.py:177-183` |
| 8 | 🟠 MED   | `EconomicCalendar` uses deterministic 2nd-Wednesday for CPI, 1st-Friday for NFP — real BLS dates occasionally differ | `compass/exp3311_event_gate.py:91-110` |
| 9 | 🟡 LOW   | Volume gate fails-open on cache miss (documented but permissive) | `backtest/historical_data.py:446` |
| 10| 🟡 LOW   | Inconsistent Yahoo-failure semantics across `fetch_vix` (silent), `_fetch_yahoo_close` (silent), `fetch_close` (raises) | three files |
| 11| 🟡 LOW   | `apply_regime_gate` defaults to leverage=1.0 during ZSCORE_WINDOW warm-up — no regime protection in early fold windows | `compass/exp3303_regime_transition_dd.py:159-163` |
| 12| 🟡 LOW   | `_ensure_exp1220_trades` doesn't validate that downloaded SPY / ^VIX series cover the full required range | `compass/exp3311_runner.py:162-199` |

## 8. Rule Zero verdict

**No `np.random`/synthetic price is injected into any live P&L stream.** The `BACKTEST_CREDIT_FRACTION` constant is dead-but-loaded.

However, **two non-obvious Rule-Zero-adjacent issues** invalidate the spirit of the rule:

1. The `0.0` expiration-day fallback in `exp1220_standalone._walk_spread` silently equates
   "no data" with "max profit" for put credit spreads.
2. Yahoo continuous futures (GC=F, SI=F) inject splice noise into the GLD / SLV calendar
   spread returns without any roll-date awareness.

Both warrant investigation before any of these results are quoted to LPs as "Rule Zero
compliant."

## 9. Data-availability verdict

**The 8-stream cube has no completeness gate.** A missing or stale pickle, or a stale
options DB, will silently produce a sparse cube that biases Sharpe upward and DD downward.
This is the single most actionable hardening item: a single `assert` block in
`build_baseline_cube` validating per-stream non-zero day counts, plus a staleness check on
`options_cache.db`, closes the largest silent-failure surface.
