# CC3 FINDINGS — Data Pipeline & Market Data Audit

**Auditor:** CC3 (Claude Opus 4)
**Date:** 2026-05-24
**Branch audited:** `feature/experiment-manager-phase-6` @ HEAD
**Verdict:** 🔴 **NO-GO for Monday May 26 open** — multiple CRITICAL issues.

---

## TL;DR

The brief's mental model is **partially wrong**, which itself is a finding:

- There is no `pilots/data_manager.py` or `pilots/ironvault_client.py` in this repo. The `pilots/` directory does not exist. Audit re-scoped to the actual modules: `shared/iron_vault.py`, `shared/data_cache.py`, `shared/live_pricing.py`, `strategy/polygon_provider.py`, `scheduler/data_providers.py`.
- **IronVault is backtest-only** (`HistoricalOptionsData(..., offline_mode=True)`). It does NOT supply Monday-morning live chains.
- **Live option chains** come from `strategy/polygon_provider.py` → Polygon REST. No Yahoo Finance fallback exists for option chains anywhere in the codebase.
- **`yfinance`** is only an L3 fallback in `scheduler/data_providers.py` for ETF prices and VIX/VIX3M values — never for option chains and never for `shared/data_cache.py` OHLCV.

That said, the underlying questions in the brief are still answerable, and several answers are alarming.

---

## CRITICAL findings

### C1. `options_cache.db` is NOT shipped in the Railway image
**File:** `Dockerfile.scheduler` (lines copying source dirs)
**Evidence:** the Dockerfile copies `compass/ scheduler/ sentinel/ shared/ alerts/ backtest/ strategy/ tracker/ configs/ scripts/ main.py utils.py` — **not `data/`**. The image then runs `RUN mkdir -p /data/logs /data/signals` and sets `ENV COMPASS_DATA_DIR=/data`. The 978 MB `data/options_cache.db` will not be present in the container unless Railway has a persistent volume mounted at `/data` that was pre-populated out-of-band.

**Impact (backtest):** Any backtest-using code path inside the container will hard-fail with `IronVaultError("options_cache.db not found at /data/options_cache.db")`. The scheduler may not need this on the live path, but anything that imports `shared.iron_vault.IronVault.instance()` at startup will crash.

**Action:** Verify Railway volume mount and contents on each service (`vesper`, `sentinel-watchdog`, `dashboard`). If absent, either (a) bake the DB into the image (not recommended at 978 MB), (b) sync at boot via a startup script, or (c) confirm no live code path requires IronVault.

---

### C2. `options_cache.db` is 52 days stale; two underliers are 5+ months stale; SLV is entirely absent
**File:** `data/options_cache.db` (file mtime 2026-04-06; queried directly)
**Evidence:**
```
file size:        1025.2 MB
file mtime:       2026-04-06 08:40 UTC
integrity_check:  ok
tables:           lost_and_found, option_contracts, option_daily, option_intraday
row counts:       contracts=276,221  daily=6,278,985  intraday=1,591,036
```
Per-required-underlier coverage (joined `option_daily` × `option_contracts`):

| Ticker | Daily bars | Last date | Days stale (as of 2026-05-24) |
|---|---:|---|---:|
| SPY  | 4,378,094 | 2026-04-02 | **52** |
| QQQ  |   779,955 | **2025-12-19** | **156** |
| XLF  |   243,583 | 2026-04-02 | 52 |
| XLI  |   200,761 | 2026-04-02 | 52 |
| GLD  |   189,921 | **2025-12-19** | **156** |
| **SLV** | **0** | — | **MISSING ENTIRELY** |

Top tickers by contract count include `TLT/SOXX/XLK/XLE` (not in the required set) but **no SLV row whatsoever**.

**Impact:** Any backtest re-validation or signal-replay using IronVault for SLV will fail outright. QQQ and GLD have a 5-month gap. Even SPY is 52 days behind — well outside any reasonable freshness window for production validation.

**Action (must precede Monday open):**
1. Run `scripts/iron_vault_setup.py` (referenced by `iron_vault.py:77,96-98`) to inventory and re-fetch.
2. Backfill 2026-04-03 → 2026-05-23 for SPY/XLF/XLI; 2025-12-20 → 2026-05-23 for QQQ/GLD; full history for SLV.
3. Confirm same DB lands on Railway volume.

---

### C3. No staleness check anywhere in `IronVault` or `DataCache`
**Files:** `shared/iron_vault.py:84-98`, `shared/data_cache.py:63-119`
**Evidence:**
- `IronVault._validate_has_data()` checks only `SELECT COUNT(*) FROM option_contracts > 0`. There is no `MAX(date)` check, no age-vs-today comparison, no warn-if-stale.
- `DataCache.get_history()` uses a **TTL on the in-memory dict cache** (default 900 s) but the underlying Polygon call has no "is the most recent bar within N days of today" assertion — it will happily return year-old data if that's what Polygon returns.
- `grep -rE 'staleness|stale_check|max_age|data_freshness' shared/**/*.py` → **0 matches**.

**Impact:** A silently-stale DB or a misconfigured date range will not raise. The system will trade on weeks-old IV/skew assumptions without alarming.

**Action:** Add a startup-time assertion: `MAX(date) >= today - N business days` (suggest N=3) in `IronVault._validate_has_data`, raising `IronVaultError` if violated. Also add a per-fetch "most recent bar age" check in `DataCache.get_history`.

---

### C4. `PolygonProvider` (live option chains) uses `POLYGON_API_KEY`, not an options-specific key
**File:** `strategy/polygon_provider.py:415` and `strategy/options_analyzer.py:55`
**Evidence:**
```python
provider = PolygonProvider(api_key=os.environ.get("POLYGON_API_KEY", ""))
...
self.polygon = PolygonProvider(api_key)
```
There is **no** `POLYGON_OPTIONS_API_KEY` referenced anywhere (`grep` → 0 matches). PR #42 already established that Polygon's stocks plan returns 403 for index tickers (`I:VIX` etc.). Polygon similarly bills options chains as a separate entitlement. If the account on `POLYGON_API_KEY` doesn't include options, every `get_options_chain` call 403s and the live path has **no fallback for chains**.

**Impact:** Could be silent failure on Monday morning. `LivePricing._fetch_chain` catches all exceptions and returns `None`; callers either skip the position (no trades fired) or fall back to a synthetic Black-Scholes estimate (see C5).

**Action:**
1. Confirm `POLYGON_API_KEY` includes the options entitlement, OR
2. Mirror PR #42's pattern: introduce `POLYGON_OPTIONS_API_KEY` and a `_pick_key(asset_class)` helper, wire it through `PolygonProvider`.
3. Run a live probe Monday pre-open (similar to `scripts/_p0_2_live_probe.py`) hitting `/v3/snapshot/options/SPY` and asserting 200.

---

### C5. Option chain failure silently falls back to synthetic pricing — direct `CLAUDE.md` violation
**File:** `shared/live_pricing.py:53-55, 73, 123-145`
**Evidence:**
- Docstring on `get_spread_value` (lines 53-55): *"Returns `None` if any leg cannot be priced (**caller should fall back to Black-Scholes**)."*
- Internal `_fetch_chain` catches every exception and returns `None`.
- `CLAUDE.md` (loaded into context): *"NEVER use heuristic or synthetic data. … Any code path that falls back to synthetic pricing (fixed credit fractions, Black-Scholes estimates used as 'prices', `BACKTEST_CREDIT_FRACTION`) is a critical bug. This is a Carlos directive — no exceptions."*

The audit was not asked to *fix* this, but the design intent encoded in the docstring directly contradicts the project rule. If the Polygon options endpoint is degraded Monday, paper_trader will quote Black-Scholes "prices" as fills.

**Action:** Decide policy. Either (a) kill the position evaluation on `None` (block trade), or (b) explicitly authorize the BS-fallback as an exception. Currently the policy is ambiguous between code and rules.

---

## HIGH findings

### H1. `shared/data_cache.py` has no `yfinance` fallback path
**File:** `shared/data_cache.py:114-118`
**Evidence:** On any `DataFetchError` from Polygon, `get_history` re-raises. The yfinance fallback that existed pre-Polygon migration is gone. The TTL-cached in-memory data could be served from a previous successful call within the 900 s window, but a cold-start scenario (process restart) with Polygon down is unrecoverable for OHLCV. `shared/data_cache.py:142-150` actively raises `NotImplementedError` for `get_ticker_obj`.

**Impact:** All scanners that import `DataCache` (alerts/, strategy/, compass/ — confirmed: 183 files reference `yfinance` symbols but most are migration artefacts) will fail on Polygon outage. The scheduler's `scheduler/data_providers.py` still has L3 yfinance for ETF/VIX *prices*, but `DataCache` itself does not.

**Action:** Either restore an L2/L3 fallback in `DataCache` or document that DataCache deliberately has no fallback and the scheduler is the only fallback-tier consumer.

---

### H2. `get_spot_price` claims index routing but uses stocks snapshot URL (same nit from PR #42)
**File:** `scheduler/data_providers.py:389-407`
**Evidence:** `_pick_key(ticker)` returns indices key for `I:VIX`-style tickers, but the URL is hardcoded `…/markets/stocks/tickers/{ticker}`. If anyone calls `get_spot_price("I:VIX")`, the indices key hits the stocks endpoint → 404/403. Currently safe because only `SPY` is the documented caller (`scheduler/jobs.py:162`), but the routing implies a capability that doesn't exist.

**Action:** Same as in PR #42 review — either keep stocks-only here or branch on `I:` prefix.

---

### H3. `_polygon_get_historical` silently returns `None` on every non-OK response
**File:** `scheduler/data_providers.py:121-123`
**Evidence:** A broad `except Exception` swallows 403, 429, 500, JSON parse errors, etc., and just logs a `DATA_FALLBACK` warning. No distinction between "tickerless" vs "rate-limited" vs "auth bad" — they all look identical to the caller.

**Impact:** A bad `POLYGON_INDICES_API_KEY` on Railway will look indistinguishable from a transient timeout. Combined with no staleness check (C3), this can silently degrade.

**Action:** Surface the HTTP status in the warning; consider raising on 401/403 so an env-var problem aborts startup rather than degrades quietly.

---

## MEDIUM findings

### M1. `shared/options_cache.db` is a 0-byte ghost file
**File:** `shared/options_cache.db` (0 bytes, mtime 2026-04-05)
**Evidence:** A second `options_cache.db` exists at `shared/` (empty). This is confusing and could be picked up by glob-based path-resolution code.
**Action:** Delete `shared/options_cache.db` — only `data/options_cache.db` is the real DB.

---

### M2. Two `Dockerfile`s but no `railway.toml`
**Evidence:** `railway.toml` not present in repo. `Dockerfile.old`, `Dockerfile.scheduler`, `Procfile` exist. `Procfile` says `web: uvicorn web_dashboard.app:app …` — only the web dashboard. The scheduler/sentinel services on Railway must be configured elsewhere (Railway dashboard or per-service config).
**Action:** CC4 (Railway audit) should verify each service's build context and start command. Not a CC3 issue per se but cross-cutting.

---

### M3. No `POLYGON_OPTIONS_API_KEY` discriminator + no per-asset-class routing on options
**Reiteration of C4 at lower scope.** PR #42 introduced `_pick_key` for indices vs stocks. There is no equivalent for stocks vs options. If/when Polygon's options plan is on a separate key, the codebase will need the same pattern applied to `PolygonProvider`.

---

## LOW findings

### L1. `_pick_key` is underscore-prefixed but imported across modules
Same nit as the PR #42 review. Style only.

### L2. No automated freshness test in CI
There is no test that asserts `MAX(date) >= today - 5 business days` against `options_cache.db`. A simple unit test would catch C2 type drift.

---

## Direct answers to the brief's 5 critical questions

| # | Question | Answer |
|---|---|---|
| 1 | When was `options_cache.db` last updated? | File mtime **2026-04-06**; last `option_daily` bar **2026-04-02** (SPY/XLF/XLI). QQQ & GLD frozen at **2025-12-19**. **52–156 days stale.** |
| 2 | Are all 6 underliers present? | **NO.** SLV has **0 bars**. QQQ and GLD are 5 months stale. Only SPY/XLF/XLI have "recent" (≤52d) data. |
| 3 | What happens if an underlier has no data? | `IronVault.get_contract_price` (delegated to `HistoricalOptionsData`) returns `None` per cache miss — the docstring (`iron_vault.py:37-39`) calls this "the correct behaviour, NOT a fallback to synthetic pricing". So a SLV backtest will silently produce zero trades. There is no top-level "this underlier has no data" alert. |
| 4 | What happens if IronVault API is down? | IronVault is in-process SQLite, so "API down" maps to "DB file missing/corrupt". Initialization raises `IronVaultError` and the importer crashes. There is no fallback. **This is also what happens on Railway if the volume isn't mounted (C1).** |
| 5 | What happens if Yahoo Finance is down? | yfinance is only used in `scheduler/data_providers.py` as L3 fallback for ETF prices and VIX/VIX3M scalars. If down: L4 stale cache kicks in (`_use_cached`, `data_providers.py:255-287`) with max-age 48 h (ETF) or 24 h (VIX). After that → `DATA_FAILURE` alert and conservative-block in the regime gate. **yfinance is not in the live option chain path at all.** |

---

## GO / NO-GO

**🔴 NO-GO for Monday May 26, 2026 open.**

Blocking issues (must clear before any GO):

1. **C2** — DB staleness/missing SLV → backtest validation impossible.
2. **C1** — confirm `options_cache.db` is actually on the Railway volume, not just in the dev directory.
3. **C4** — verify Polygon options plan entitlement on `POLYGON_API_KEY` via live probe before market open.

Strong recommendation:

4. **C5** — Carlos must explicitly decide whether the Black-Scholes fallback at `live_pricing.py` is allowed (the docstring contradicts `CLAUDE.md`). If not allowed, code change required before Monday.
5. **C3** — Land a startup-time freshness assertion. Five-line patch, prevents whole class of silent-stale incidents.

---

## Files inspected

- `shared/iron_vault.py` (full)
- `shared/data_cache.py` (full)
- `shared/live_pricing.py` (full)
- `scheduler/data_providers.py` (full — also covered by PR #42 review earlier today)
- `strategy/polygon_provider.py` (first 100 lines + grep for entry points)
- `data/options_cache.db` (schema + counts + per-ticker freshness via Python `sqlite3`)
- `Dockerfile.scheduler`, `Procfile`
- `SKEPTICAL_AUDIT_2026_05_24.md`

## Files referenced in brief but not present in repo

- `pilots/data_manager.py` — does not exist
- `pilots/ironvault_client.py` — does not exist
- `pilots/` directory — does not exist

This brief-vs-reality drift is itself a process finding: the audit template was written against an outdated mental model of the codebase.
