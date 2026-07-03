# EXP-3311b — VIX-Blind Fix Validation (commit 8f1bc8c)

**Date:** 2026-07-03 · **Status:** completed
**Question:** does the production engine now see real VIX end-to-end, with no monkeypatch, when run offline with no Polygon indices key?

## PASS/FAIL

**PASS — the production engine now loads real VIX with 0/1508 fallback days and reproduces the EXP-3510 realvix arm bit-for-bit (all metrics and all 1198 trades identical), with no `_POLYGON_INDICES_START` patch.**

## What was fixed

Pre-fix, `backtest/market_history._load_indices_hybrid` raised on the Polygon slice when no indices API key was configured, the caller swallowed the error, and the backtester silently ran the ENTIRE window on `vix=20 / iv_rank=25` defaults (EXP-3510 finding: all 1508 days VIX-blind, producing fake-good results). Commit `8f1bc8c` wraps the Polygon load in a try/except that degrades to the SQLite indices DB (real Yahoo-sourced VIX/VIX3M/SPX through 2026, backfilled in EXP-3510 step 1) and logs a loud warning instead of aborting the load.

## Method

Re-ran the canonical V8A replay through the **unmodified production path**: real `backtest/backtester.py`, `configs/paper_expv8a.yaml`, SPY 2020-01-02 → 2025-12-31, offline `data/options_cache.db`, leg-collision guard ON — byte-identical setup to `scripts/exp3310_collision_rebacktest.py` / EXP-3510's `run_replay.py`, but with **no monkeypatch** (`run_replay.py` in this directory; it asserts `POLYGON_INDICES_API_KEY` is unset). Same VIX-fidelity instrumentation as EXP-3510, plus capture of the new fallback warning on the `backtest.market_history` logger.

## Results — before / after

| | EXP-3310/3510 "fallback" (pre-fix prod path) | **EXP-3311b (fixed prod path)** | EXP-3510 "realvix" (monkeypatched reference) |
|---|---|---|---|
| VIX days fallback/defaulted | **1508 / 1508** | **0 / 1508** | 0 / 1508 |
| VIX range seen | 20.0 flat | 11.86 – 82.69 | 11.86 – 82.69 |
| VIX series | empty | 1656 rows, 2019-06-03 → 2025-12-31 | identical |
| Total trades | 1167 | **1198** | 1198 |
| Return | +4.94 % | **−8.91 %** | −8.91 % |
| Sharpe | 0.12 | **−0.06** | −0.06 |
| MaxDD | −24.16 % | **−31.78 %** | −31.78 % |
| Win rate | — | 70.12 % | 70.12 % |
| Trade mix (bp/bc/IC) | — | 455 / 53 / 690 | 455 / 53 / 690 |

Match quality vs the realvix reference: every metric equal, and the full 1198-trade log is identical on entry date, exit date, type, and PnL. The `_POLYGON_INDICES_START` monkeypatch is now unnecessary — the production fallback reaches the same SQLite data.

The new warning fired exactly as designed (2 lines, one per index; captured in `results/replay_prodpath.json → sqlite_fallback_warnings`):

```
WARNING Polygon indices unavailable for I:VIX (2023-02-14..2026-01-01): No API key configured … — falling back to SQLite indices for this slice.
WARNING Polygon indices unavailable for I:VIX3M (2023-02-14..2026-01-01): … falling back to SQLite indices for this slice.
```

The silent-VIX-blind failure mode is gone: the engine either sees real VIX or says loudly that it can't.

## Test suite

`pytest tests/ -q --no-cov`: **4221 passed, 20 failed, 19 skipped, 8 xfailed** (97 s).

**None of the 20 failures are regressions from 8f1bc8c**, verified by running the same tests at the parent commit (0bc9e40) in a clean worktree:

- 19/20 fail identically at the parent (pre-existing branch failures: `test_backtester` intraday-scan expectations incl. `TestICIntradayEntryScanSkip` — independently confirmed pre-existing, got 130 vs expected 20 at parent too — `test_scheduler` scan-time counts, `test_sentinel_g22_producers` EXP-1220 wiring, `test_compass_scanner` fear/greed flags, `test_no_new_yfinance_imports`, etc.). `tests/KNOWN_FAILURES.md` is stale (2026-03-20) and lists a different set.
- The 20th, `test_data_cache::test_missing_api_key_raises`, **passes at HEAD in a clean worktree** (both in isolation and in the polluting pairing) — its full-suite failure here is working-tree state left by today's experiment runs (shared bar-cache), not the commit. The production no-key contract for stock bars still raises `DataFetchError`; only the *index* loader falls back by design.

## Files

- `run_replay.py` — no-patch production-path replay with VIX-fidelity instrumentation
- `results/replay_prodpath.json` — metrics, VIX fidelity block, fallback warnings, full trade log

## Conclusion

Fix validated end-to-end. The corrected canonical V8A baseline (−8.91 % / Sharpe −0.06 / MaxDD −31.78 %, 2020–2025) is now what the production engine produces by default, and EXP-3520/3540/3550-style experiments no longer need the indices monkeypatch.
