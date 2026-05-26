# CC3 FAILURE MODES — Scan Path (`scan_opportunities` → `_analyze_ticker`)

**Auditor:** CC3
**Date:** 2026-05-24 (Sunday)
**Branch:** `feature/experiment-manager-phase-6`
**Posture:** Assume the system is broken; prove how.
**Target market open:** Tuesday **May 26, 2026** (Monday May 25 = Memorial Day, market closed).
**Verdict:** 🔴 **NO-GO** — at least 4 CRITICAL silent-fail modes in the scan path, several already triggered by issues from CC3_FINDINGS.md.

---

## Failure-mode table (severity, where, blast radius, safety net)

### CRITICAL

| ID | Failure | Where | What breaks | Safety net? | Recovery |
|---|---|---|---|---|---|
| F-C1 | **Top-level `_analyze_ticker` swallows every exception** | `main.py:392–548` (the `try:` at 392 + `except Exception` at 546–548 returns `[]`) | Any error in price fetch, options chain, regime detect, snapshot build, signal gen, scoring, repricing, etc. silently emits `[]` for that ticker. The scan finishes with `"No opportunities found"` and a SUCCESS log. | Per-future error path at `main.py:342–348` calls `notify_api_failure` Telegram, BUT that path only fires when `future.result()` itself raises. The inner `except` at line 546 prevents the future from ever raising — so the Telegram alert is **unreachable** through normal failures. | None. Carlos has to inspect logs to know nothing scanned. **Silent failure of entire scan**. |
| F-C2 | **No options provider configured** | `strategy/options_analyzer.py:74–77` (`raise RuntimeError("No options provider configured…")`) | All tickers raise; F-C1 swallows; scan returns `[]`. | None — exception is swallowed before reaching the future-level alert. | Manually set `data.provider` in YAML and verify env. |
| F-C3 | **Polygon options chain endpoint 403 (no options entitlement)** | `strategy/polygon_provider.py:60–87` (`_get` → `ProviderError` → circuit breaker). `options_analyzer.py:111–112` catches `Exception`, returns empty DataFrame. `main.py:407–409` sees empty chain → `return []`. | Every ticker logs `"No options data for X"` and produces zero opportunities. Scan completes "successfully". | Circuit breaker at `polygon_provider.py:41` (failure_threshold=5, reset 60s) — protects rate-limit cost but **does not alert**. | Verify Polygon plan covers options; live-probe `/v3/snapshot/options/SPY` Monday pre-open. |
| F-C4 | **VIX history fetch fails → combo regime = None → all entries blocked** | `main.py:427–456`. Try block catches Polygon errors on `^VIX`/`^VIX3M`, sets `regime=None`. Line 468–470 returns `[]` when combo mode is active and regime is None. | If `data_cache.get_history('^VIX')` raises (Polygon down, key wrong, no `I:VIX` entitlement — see PR #42), every combo-mode ticker returns []. | Logged at ERROR level (`"…regime=None with combo mode active — skipping all entries"`) but **no Telegram alert**. | Verify `POLYGON_INDICES_API_KEY` (PR #42) is set on all 3 Railway services. |

---

### HIGH

| ID | Failure | Where | What breaks | Safety net? | Recovery |
|---|---|---|---|---|---|
| F-H1 | **`_get_compass_universe` falls back to static tickers on any DB error** | `main.py:200–222` ("On any DB error the method falls back to the static `config.tickers` list with no overrides"). | If COMPASS DB is unreachable on Railway, the universe silently collapses to the static list. This is a *fail-open* — system trades a different universe than the backtest validated. CC2's "backtest match" criterion is broken. | Logged but does not block. | Verify COMPASS DB is mounted/readable on the Railway service. |
| F-H2 | **`notify_api_failure` not in nested try — could cascade-kill `as_completed` loop** | `main.py:342–348`. `notify_api_failure` is invoked inside the `except` block but is itself unguarded. | If Telegram bot raises (token bad, network down), the surrounding `for future in as_completed(...)` exception handler propagates the new exception out of the loop. Remaining futures are abandoned; `executor.__exit__` cancels them. Scan returns partial results. | None — Telegram failure becomes a scan failure. | Wrap `notify_api_failure` in `try/except` or move to a synchronous logger-side handler. |
| F-H3 | **NFP blacklist not found → fail-open (no skip)** | `shared/entry_gate.py:42–44`. Missing file → empty list → no gate, ever. | If `configs/event_blacklist.json` isn't in the Docker image / Railway working dir, the NFP filter silently disables. The system enters trades the day-before-NFP, which the experiments explicitly avoid. | None — just a WARNING log. | Bake `configs/` into image (confirm); add a startup-time sanity check that the file loads and contains at least one future date. |
| F-H4 | **NFP blacklist only valid through 2026-12-04** | `configs/event_blacklist.json` (7 dates, last is 2026-12-04). Comment says "Quarterly cron job re-verifies against BLS when reachable" but the last `_verified` note says BLS WebFetch returned **403**. | After Dec 4, 2026, the gate silently disables (empty future-date set). Long-term silent regression. | None visible. | Manual refresh + verify the quarterly cron is actually running. |
| F-H5 | **Provider returns options but **all rows have bid≤$0.05`** | `options_analyzer.py:100–106` *warns* if fewer than 10% of rows have bid/ask > 0.05; still returns the full chain. `_clean_options_data:144` later filters `bid>0 & ask>0`. Some rows survive but pricing is unreliable. | Spread strategies score the bad chain, generate "opportunities", and route them to alerts. RiskGate at the router level is downstream of scoring. | Warning log only. | Add a hard floor: refuse to evaluate when valid_pricing < 50% of expected strikes. |
| F-H6 | **DataCache has no fallback path** | `shared/data_cache.py:114–118`. Polygon outage at cold start → `DataFetchError` → `_analyze_ticker` swallows → return []. | Same end-state as F-C1. Combined with no in-process cache on first call after a restart, a brief Polygon hiccup at scan time produces an empty-scan with no alarm. | The 900s in-memory TTL helps only after the first success. | Restore an L2 fallback (Alpaca data API has historical bars) for the cold-start case. |
| F-H7 | **Execution window gate evaluated in container local time vs ET tz string** | `shared/execution_window.py:46–64` uses `ZoneInfo(tz)` if available. On a `python:3.11-slim` image, `tzdata` is installed by `Dockerfile.scheduler:18` — OK. But if any Railway service is built from `Dockerfile.old` without tzdata, `ZoneInfo` raises `ZoneInfoNotFoundError`, falling through to **naive `datetime.now()`** (line 62 — comment: "tests should always pass `now`"). Naive container time may not be ET. | Result: window could be evaluated against UTC instead of ET, skipping or admitting at the wrong hours. | None — the fallback is silent. | Confirm scheduler image is `Dockerfile.scheduler`; pin tzdata. |
| F-H8 | **`get_history` raises on `^VIX3M` → only VIX populated → ComboRegime degraded but not None** | `main.py:435–441`. The `try/except Exception: pass` around the VIX3M fetch means if VIX3M unavailable, regime detector runs with `vix3m_by_date={}`. Detector may compute a regime anyway (depends on its handling of missing VIX3M). | Regime label could be biased toward a state that doesn't match the backtest (which had real VIX3M). Subtle but real. | None. | Either propagate the VIX3M error or document the missing-data branch's behavior in `ComboRegimeDetector`. |

---

### MEDIUM

| ID | Failure | Where | What breaks | Safety net? | Recovery |
|---|---|---|---|---|---|
| F-M1 | **Empty scan result produces no alert** | `main.py:350–352`. `"No opportunities found"` is INFO-level. | Monitoring depends on someone reading logs. With F-C1/F-C3 active, the system could run silent for days. | None. | Add a Telegram heartbeat-with-opportunity-count after each scan; alert if 0 opportunities for N consecutive scans. |
| F-M2 | **`metrics.inc('scans_skipped_*')` not surfaced** | Used at `main.py:304,318,481`. | The skip-counters exist in memory but no `metrics`-style endpoint is documented; cannot easily tell if NFP/window/regime-gate is silently eating every scan. | None at the audit level. | Add a `/metrics` endpoint or daily Telegram digest. |
| F-M3 | **Per-thread Polygon rate limit may starve under burst** | `polygon_provider.py:54–61` is a global `_min_call_interval=0.2` (5/sec). 4 worker threads × multiple subcalls per ticker × pagination loops in `_paginate` (up to 50 pages — `polygon_provider.py:27`) can serialize on the rate-lock. | Scan latency balloons; could miss execution window for window-gated configs. | The rate limiter itself is the safety net — won't 429 — but downstream timing assumptions can break. | Either raise `max_workers` only when entitlement allows, or pre-fetch SPY first sequentially. |
| F-M4 | **`reprice_signals_from_chain` failure path not visible from this audit** | `main.py:531–533`. If reprice raises, it falls into the line-546 catch. | Same silent-skip pattern as F-C1. | None. | Wrap reprice in its own try and log/raise distinctly. |
| F-M5 | **Per-strategy `try/except` in signal generation logs WARNING not ERROR** | `main.py:520–524`. | If a strategy's `generate_signals` is broken, it logs a warning per ticker per scan — easy to overlook. | Warning log. | Promote to error after N consecutive failures for a given strategy. |
| F-M6 | **Insert-alert failure non-fatal but loses data** | `main.py:566–570`. If SQLite locked/path wrong, alerts are dropped with a warning. | Web dashboard goes dark. | Warning only. | Promote on first failure; alert on persistent failure. |

---

### LOW

| ID | Failure | Where | Notes |
|---|---|---|---|
| F-L1 | Telegram path uses `score >= 60` hard threshold (`main.py:574–578`) — magic number. If signals never reach 60, scan completes but Telegram sends 0. Could be misread as "scan didn't run". |
| F-L2 | `_analyze_ticker` returns `[]` for *any* failure mode without distinguishing "no signal" from "system error". Aggregation can't tell them apart. |
| F-L3 | `current_price = float(price_data['Close'].iloc[-1])` (`main.py:402`) crashes if `'Close'` column missing but `price_data.empty` was False (degenerate one-row DataFrame without Close). Same swallow. |

---

## Pre-existing CRITICAL findings from CC3_FINDINGS.md that also block scans

These were filed already; restating with scan-path impact:

| Ref | Issue | Scan-path consequence |
|---|---|---|
| C1 (FINDINGS) | `options_cache.db` not in Docker image | Backtest validation crashes at import (`IronVault.instance()`); live scan only crashes if any live module imports IronVault. Confirm none does on the production path. |
| C2 (FINDINGS) | DB last bar 2026-04-02; **SLV has 0 rows**; QQQ/GLD 5 months stale | Live scan unaffected (live chains come from Polygon REST). But if `unified_strategies` or `score_signal` consults the DB for IV-rank history, SLV silently scores at default. |
| C3 (FINDINGS) | No staleness assertion anywhere | F-C4 + F-H6 amplified: stale or stuck data flows through scan with no tripwire. |
| C4 (FINDINGS) | `PolygonProvider` uses `POLYGON_API_KEY` only; no `POLYGON_OPTIONS_API_KEY` | Direct cause of F-C3 if account lacks options entitlement. |
| C5 (FINDINGS) | `live_pricing.py` docstring authorizes BS fallback | Not in scan path, but downstream `paper_trader._evaluate_position()` uses it — exit pricing could be synthetic when chain fetch fails. |

---

## Direct answers to CC3 phase questions

| # | Question | Answer |
|---|---|---|
| 1 | Will `scan_opportunities()` work? | **Only if** (a) at least one of Polygon/Tradier options provider is configured, (b) Polygon options entitlement is active, (c) `^VIX`/`^VIX3M` fetch via PR-#42's indices key actually works on Railway, (d) `configs/event_blacklist.json` is present, (e) combo-regime detector returns a non-None label, AND (f) the execution window is currently open (if `window_only=true`). Anything missing → silent empty scan. |
| 2 | What if market data unavailable? | Each ticker individually catches the exception, logs at WARNING/ERROR, returns `[]`. Scan completes "successfully" with 0 opportunities. **No alarm fires.** This is the dominant silent-fail mode. |
| 3 | What if IronVault DB missing? | Live scan path does NOT use IronVault. But any module that calls `IronVault.instance()` at import will hard-crash the process (`IronVaultError`). Need to verify live import graph — none should touch IronVault on the scan path, but I did not exhaustively trace `unified_strategies`. |
| 4 | What if options chain empty? | `_analyze_ticker:407–409` returns `[]`. No alert. Scan logs "No options data for X". |
| 5 | What if regime detection fails? | `regime=None` → `_analyze_ticker:468–470` returns `[]`. Logged at ERROR but no Telegram. With combo mode the **entire scan returns empty** if VIX/VIX3M fails. |
| 6 | What if all gates block? | NFP gate (`scan_opportunities:303–305`) or window gate (`315–319`) returns `[]` directly. Per-stream regime gate (`479–482`) returns `[]` per ticker. No aggregated alert; just `INFO` log. The "all blocked" state is **indistinguishable from "no signals found"** in current monitoring. |

---

## Tuesday May 26 (target open) — concrete risks

Today is **Sunday May 24**. Tomorrow is Memorial Day (closed). First open is **Tuesday May 26**.

Gate evaluation for the first scan on Tuesday May 26:
- NFP filter: `today=2026-05-26`, `tomorrow=2026-05-27`. Not in blacklist (next is 2026-06-05). **PASS.**
- Window gate: Depends on cron schedule + config's `window`. If `window_only: true` and cron fires at 09:30 ET, the window `15:30-16:00` is closed and **scan returns []**. Verify which config is deployed and what the cron schedule is.
- Combo regime: VIX/VIX3M must be reachable via `POLYGON_INDICES_API_KEY`. **PR #42 fix is on a different branch** (`fix/p0-2-polygon-indices-routing`); confirm it has merged before Tuesday or this branch carries the equivalent fix.
- Regime gate: If active and regime is `transition`/`high_stress`, SPY/QQQ are skipped — sector ETFs continue. With current options DB missing SLV entirely, sector backtest comparison won't validate for SLV regardless.

---

## Recommended pre-open verification (Monday May 25, market closed)

1. **Live probe Polygon options endpoint** with both `POLYGON_API_KEY` and a hypothetical `POLYGON_OPTIONS_API_KEY` (if exists). Hit `/v3/snapshot/options/SPY`; assert 200 with chain.
2. **Confirm PR #42 has merged** into the production branch and `POLYGON_INDICES_API_KEY` is set on all 3 Railway services (carry-over from PR #42 review).
3. **Verify `configs/event_blacklist.json` is in the deployed image** (`docker run … ls /app/configs/`).
4. **Verify `tzdata` is in the runtime image** — `Dockerfile.scheduler:18` installs it; `Dockerfile.old` may not.
5. **Dry-run `scan_opportunities()`** with a synthetic "Polygon down" injection — confirm Telegram alert fires (F-H2 test).
6. **Add a one-shot Telegram heartbeat** that reports the post-scan opportunity count, scan_skipped counters, and circuit-breaker state. Without this, silent fails are invisible.

---

## Files inspected

- `main.py:280–720` (scan path)
- `strategy/options_analyzer.py:60–146` (chain fetch + cleaning)
- `strategy/polygon_provider.py:1–100` (rate-limit + circuit breaker)
- `shared/entry_gate.py` (full)
- `shared/execution_window.py` (full)
- `shared/regime_gate.py` (full)
- `shared/data_cache.py` (revisited from CC3_FINDINGS)
- `shared/live_pricing.py` (revisited)
- `configs/event_blacklist.json`
- `Procfile`, `Dockerfile.scheduler`

## Files referenced in brief that do not exist in repo

- `pilots/data_manager.py`, `pilots/ironvault_client.py`, `railway_worker.py` — none present on this branch.

---

## GO / NO-GO for Tuesday May 26

🔴 **NO-GO**. The dominant pattern is **silent empty scans**: F-C1 swallows every per-ticker error, F-C3/F-C4 are likely to fire on Tuesday morning if anything about Polygon entitlements is off, and there is no aggregated "scan returned nothing" alert. Combined with the data-staleness issues in CC3_FINDINGS.md, the realistic Tuesday outcome is: **scanner runs, logs success, generates zero trades, nobody notices for hours**.

Minimum patches before GO:
1. Add a post-scan opportunity-count Telegram alert (closes F-M1).
2. Wrap `notify_api_failure` call in try/except (closes F-H2).
3. Make `_analyze_ticker`'s top-level exception handler raise after logging when the exception is in a critical-path call (price/chain/regime) — so the future-level Telegram alert fires (mitigates F-C1).
4. Verify PR #42 (or equivalent) is live + `POLYGON_INDICES_API_KEY` set on Railway.
5. Verify Polygon options entitlement via live probe (closes F-C3).
