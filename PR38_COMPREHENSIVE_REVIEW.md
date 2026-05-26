# PR #38 — Comprehensive Review (EXP-3303b composite-stress regime gate)

**Auditor:** Maximus (CC5)
**Date:** 2026-05-24
**Head:** `b6e573ac8f15cace86f219a39f75afd870ebf0d6`
**Base:** `main`
**Stats:** 11 files changed, +838 / -218

---

## 1. Scope verification

### What is changed

| File | +Δ | −Δ | Type |
|---|---:|---:|---|
| `alerts/earnings_scanner.py` | 4 | 2 | defensive DataCache wiring |
| `alerts/gamma_scanner.py` | 4 | 2 | defensive DataCache wiring |
| `alerts/iron_condor_scanner.py` | 4 | 2 | defensive DataCache wiring |
| `alerts/momentum_scanner.py` | 4 | 2 | defensive DataCache wiring |
| `alerts/zero_dte_scanner.py` | 4 | 2 | defensive DataCache wiring |
| `compass/live_composite_stress.py` | 265 | 0 | **new** — live composite-stress calculator |
| `main.py` | 18 | 0 | scan_opportunities() wires the regime gate (opt-in) |
| `shared/data_cache.py` | 111 | 87 | refactor: PolygonClient → PolygonProvider, lazy init |
| `shared/regime_gate.py` | 66 | 39 | add `RegimeGate` class alongside existing per-ticker gate |
| `tests/test_data_cache.py` | 75 | 96 | rewrite to mock PolygonProvider (10 tests) |
| `tests/test_live_composite_stress.py` | 227 | 0 | **new** — 11 tests |

### What is NOT changed (re Carlos's question)

❌ **`strategy/options_analyzer.py` is not modified by this PR.** Carlos's framing "Breaking changes in options_analyzer.py (98 deletions)" does not match the file list. The PR head's file list (above) contains 11 files; none of them is `options_analyzer.py`. The largest deletion counts are `tests/test_data_cache.py` (−96) and `shared/data_cache.py` (−87) — both intentional rewrites for the Polygon migration, not breaking changes. Maximus's earlier rebuttal in the PR thread (2026-05-23) is consistent: a prior reviewer raised this claim against an older snapshot; `git diff main..feature/live-composite-stress-polygon -- strategy/options_analyzer.py` is empty.

---

## 2. Test coverage (claim 1)

### `tests/test_live_composite_stress.py` — 227 lines, 11 tests

Test classes and what they pin:

| Class | Test | Pins |
|---|---|---|
| `TestFormulaMatchesBacktest` | `test_full_frame_matches_backtest` | live ≡ inlined reference verbatim of `compass.exp3303_regime_transition_dd.build_composite_stress` (atol 1e-12, rtol 0) across all five output columns |
| | `test_term_spread_sign_inverted` | term_spread ↔ term_spread_z correlation < −0.95 (z-score inversion intact) |
| | `test_composite_uses_sqrt3_normalisation` | composite_stress == (term_spread_z + vvix_z + skew_z) / √3 |
| `TestGetCurrent` | `test_returns_float_when_data_available` | happy path |
| | `test_returns_none_when_polygon_unavailable` | Rule Zero — `DataFetchError` → `None`, never fabricate |
| | `test_returns_none_when_window_incomplete` | < 63 rows → `None` |
| `TestShouldGate` | `test_gates_when_composite_exceeds_theta` | True branch |
| | (others) | False branches / theta sensitivity / None-handling |

**Strengths:**
- Formula parity is enforced numerically, not by string compare. atol=1e-12 is appropriate for float arithmetic.
- The reference formula is **inlined** in the test file rather than imported from `compass/exp3303_regime_transition_dd.py`, with a comment explaining why (the research module pulls yfinance + fixtures not present in production). Any silent drift between live and backtest will show up as a test diff, not a stale import.
- `_isolate_cache` fixture uses `autouse=True` and monkeypatches `CACHE_PATH` into a `tmp_path` — prevents tests from polluting `compass/cache/live_composite_stress.pkl` or each other.
- DataFetchError is exercised explicitly for the VVIX/SKEW unavailable case.

**Gaps / what is not tested:**
- No test for `_save_disk_cache` writing to a read-only filesystem (Railway containers can be read-only). The code catches the exception and logs, but the behaviour isn't pinned.
- No test that two concurrent calls don't race on the pickle file (`_load_disk_cache` and `_save_disk_cache` are not under a lock).
- `_set_cache_for_test` exists as a test-only public API. Acceptable for testability but smells; an explicit DI parameter would be cleaner.
- The cache age check uses `CACHE_MAX_AGE_SECONDS = 24 * 3600`, not UTC-day boundary. If a fetch happens at 23:59 UTC, the cache is served well into the next trading day. There's no test that pins this boundary behaviour either way.

### `tests/test_data_cache.py` — rewritten (+75 / −96)

10 tests. Mocks `PolygonProvider.get_historical` instead of the removed `PolygonClient.aggregates`. New coverage:
- `TestTickerTranslation.test_yahoo_index_maps_to_polygon` — `^VIX → I:VIX`, `^VIX3M → I:VIX3M`, `^VVIX → I:VVIX`, `^SKEW → I:SKEW`
- `TestTickerTranslation.test_equity_ticker_passthrough` — `SPY → SPY`, `tlt → TLT` (uppercased)
- `test_vix_routes_to_polygon_index_ticker` — end-to-end verifies the call argument hit `I:VIX`
- `test_empty_polygon_response_raises`

Coverage looks adequate for the refactor.

---

## 3. Scanner changes (claim 3) — all 5 modified

Each of `alerts/{earnings,gamma,iron_condor,momentum,zero_dte}_scanner.py` has an identical patch:

```python
+from shared.data_cache import DataCache
...
-        # Fetch price data (Polygon-backed DataCache; required)
-        price_data = self._data_cache.get_history(ticker, period="1y")
+        # Fetch price data (Polygon via DataCache; no yfinance fallback)
+        cache = self._data_cache or DataCache()
+        price_data = cache.get_history(ticker, period="1y")
```

**Assessment:**
- ✅ The change is defensive — adds an `or DataCache()` fallback so the scanner works whether or not the caller injected `_data_cache`. Backward-compatible (callers that inject still win).
- ✅ Single new import: `from shared.data_cache import DataCache`. **No new yfinance imports.** No new Polygon imports either (DataCache encapsulates Polygon). The earlier CC3 claim "migration explicitly removed yfinance from these scanners — why are they back" is incorrect against this head.
- ⚠️ The pre-existing yfinance imports inside the scanner modules (referenced by Maximus's 2026-05-23 PR comment) are NOT removed by this PR. They live in dead/fallback paths but they are still present. Truly completing the Polygon migration requires a follow-up PR. Not a blocker for #38 since the imports aren't on the hot path, but the system is not "yfinance-free" yet.
- ⚠️ `DataCache()` no-arg construction reads `POLYGON_API_KEY` from env at construction time but raises `DataFetchError` **lazily** (in `_get_provider()`). A scanner that constructs `DataCache()` without keys will not fail until first call. Likely intentional (tests inject `_provider` directly), but it does mean a missing-key bug is deferred from import time to first scan.

Net: scanner changes are trivial, additive, and not breaking.

---

## 4. Core change — `compass/live_composite_stress.py`

### Strengths
- Formula is line-for-line consistent with the backtest entry point (pinned by `TestFormulaMatchesBacktest`).
- `_fetch_features` fails closed if any of the four indices is missing (logged warning, returns `None`). Matches Rule Zero (no synthetic data).
- TODO marker for an Unusual Whales fallback (`UNUSUAL_WHALES_API_KEY`) is well-scoped and clearly out-of-PR.
- Lazy `PolygonProvider` construction allows tests to inject a mocked DataCache without ever touching the network.

### Concerns
1. **Pickle deserialization (`_load_disk_cache`).** `pickle.load(fh)` on a path under repo control is acceptable today, but: if `compass/cache/` is ever (a) restored from backup, (b) shared between containers via a mounted volume, or (c) part of a CI artefact pull, a malicious pickle could execute arbitrary code on load. Strongly prefer `json` or a dataclass schema serialised to disk. At minimum, gate on file ownership + size.
2. **24h fixed-age cache vs UTC-day rollover.** If a fetch lands at 23:59 UTC Sunday, the cache stays valid until 23:59 UTC Monday — well past Monday's open. Pinning the cache to UTC-day or America/New_York trading-day is more aligned with the use-case (`should_gate_spx_streams`).
3. **No lock around `_load_disk_cache` / `_save_disk_cache`.** Two concurrent scans (e.g. main.py and a manual REPL) could race on the pickle file. Low likelihood in practice, but trivial to fix with `fcntl.flock`.
4. **Write to `compass/cache/` may fail on read-only filesystems.** The code catches the exception and logs a warning — safe — but means every cycle will re-fetch from Polygon. On Railway with a 5-call-per-scan budget (4 indices × N scans/day × 5 days/week) this can add up. Worth confirming Railway compass-scheduler has a writable volume mount.

---

## 5. `shared/data_cache.py` refactor

`PolygonClient` (low-level HTTP) is replaced with `PolygonProvider` (higher-level, owns ticker translation via `_to_polygon_ticker`). New `_INDEX_TICKER_MAP` is extended to include `^VVIX`, `^SKEW`, `^RUT`. Fetch window widened from 1y to ~760 calendar days (covers `2y` callers).

- ✅ Drop-in compatible: signature `get_history(ticker, period)` unchanged; returned shape unchanged.
- ✅ `_get_provider()` is lazy — tests inject `_provider` directly.
- ⚠️ `_to_polygon_ticker(ticker)` uppercases unconditionally before lookup. Polygon equities are case-insensitive, but if an upstream caller has a strict comparison this could surface. Looking at the tests (`test_equity_ticker_passthrough` asserts `_to_polygon_ticker("tlt") == "TLT"`), the upper-casing is intentional. Document it.
- ⚠️ The old `_polygon_to_dataframe` and direct `aggregates(...)` path is gone — anything outside this module that imported those private helpers will break. Grepping the diff there's nothing referencing them outside `tests/test_data_cache.py` (which is updated). Safe.

---

## 6. `shared/regime_gate.py`

Two independent gates now coexist in this file:

1. **Per-ticker selective gate** (`should_gate_for_regime`) — unchanged behaviour. Used by existing experiments.
2. **Composite-stress gate** (`RegimeGate` dataclass + `from_env()`) — new. Reads `REGIME_GATE_THETA` env var (default 2.5).

Both gates are independent and opt-in. `RegimeGate.current_stress()` and `.should_gate_spx_streams()` both lazily import `compass.live_composite_stress` to avoid pulling Polygon at module import time.

- ✅ Dataclass with `theta` attribute is testable.
- ✅ `_theta_from_env` rejects non-float env values with a warning + falls back to default (no crash).
- ⚠️ No test in this PR for `RegimeGate.from_env()` env-var parsing. The behaviour is covered indirectly by `TestShouldGate` but a unit test on `_theta_from_env` would be cheap.

---

## 7. `main.py` wiring

```python
regime_gate_cfg = self.config.get('regime_gate', {}) or {}
if regime_gate_cfg.get('enabled', False):
    from shared.regime_gate import RegimeGate
    gate = RegimeGate.from_env()
    if gate.should_gate_spx_streams():
        logger.info(...)
        metrics.inc('scans_skipped_regime_gate')
        return []
```

- ✅ Opt-in via config — existing experiments see zero behavioural change.
- ✅ Mirrors the existing NFP / execution-window gate pattern; consistent with codebase conventions.
- ✅ Metric incremented so it's observable in the dashboard.
- ⚠️ The gate is checked once per `scan_opportunities()` call. If the scan loop runs 14 times per day (per the `ScanScheduler` schedule referenced elsewhere), that's up to 14 Polygon round-trips per day just for the gate — but the 24h disk cache should absorb 13 of those. Fine.
- ⚠️ No config flag is set anywhere in this PR. The gate will not actually run for any experiment until somebody adds `regime_gate.enabled: true` to a YAML. That is a deliberate ship-dark choice but worth Carlos knowing.

---

## 8. Status of prior CC3 review issues

| Claim | Status | Evidence |
|---|---|---|
| C1 — `exp3303_regime_transition_dd` module missing | FALSE (Maximus) | Confirmed: module exists on `main`; live file does NOT import it; reference formula is inlined in the test. |
| C2 — Gate not wired into scan loop | FIXED (Maximus, commit a95d4ae) | `main.py` +18 lines verified above. |
| C3 — Scanners had yfinance imports re-added | FALSE (Maximus, rebutted 2026-05-23) | Verified: the only scanner addition is `from shared.data_cache import DataCache`. No yfinance imports added. Pre-existing yfinance imports in scanners are unchanged by this PR. |
| C4 — `options_analyzer.py` modified with yfinance restored | FALSE (Maximus) | Verified: `strategy/options_analyzer.py` is NOT in the PR's file list. |
| Pickle / cache-staleness / deleted-tests / registry-rollbacks | Not actioned | See section 4 above — pickle and 24h cache window remain open MEDIUM concerns. |

---

## 9. Risks / open issues

| ID | Severity | Issue |
|---|---|---|
| R1 | MEDIUM | `pickle.load` on the disk cache — replace with JSON / dataclass schema before sharing the cache across containers. |
| R2 | MEDIUM | 24-hour fixed cache age doesn't align with US trading day boundaries — cache can outlive its useful window. |
| R3 | MEDIUM | Scanners still carry pre-existing yfinance imports in fallback paths; "Polygon-only" migration is partial. Follow-up PR needed. |
| R4 | LOW | No test for `_save_disk_cache` failure on read-only FS or concurrent writers. |
| R5 | LOW | `_set_cache_for_test` is a test-shaped public API; consider DI through the constructor instead. |
| R6 | LOW | `RegimeGate.from_env()` env-parsing has no direct unit test. |
| R7 | LOW | No YAML configures `regime_gate.enabled: true` — gate is dark by default. Carlos: confirm intended. |

None of these are blockers.

---

## 10. Final verdict

✅ **APPROVE.**

Scope is correctly limited; tests pin the headline invariant (live formula ≡ backtest); migration is non-breaking and opt-in. Carlos's headline concerns:

- ✅ Test coverage: 11 tests + autouse fixture isolation. Formula parity asserted at 1e-12 tolerance. Adequate.
- ✅ "Breaking changes in options_analyzer.py (98 deletions)" — **false premise.** PR doesn't touch that file. The 98-deletion number likely came from `tests/test_data_cache.py` (-96) or `shared/data_cache.py` (-87), both of which are intentional Polygon-migration rewrites.
- ✅ Scanner changes are 4-line defensive wiring per file, identical pattern, no new yfinance imports.
- ✅ Prior CC3 review issues: 1 valid (C2 — gate wiring) was fixed in a95d4ae; the other three were demonstrably wrong against the actual diff.

Follow-up PRs to schedule (NOT blockers):
1. Replace pickle with JSON in `live_composite_stress` disk cache.
2. UTC-day → America/New_York trading-day cache invalidation.
3. Remove residual yfinance imports from `alerts/*_scanner.py`.
4. Decide and document which experiments will set `regime_gate.enabled: true`.
