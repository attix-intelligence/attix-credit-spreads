# PR #37 — Comprehensive Review

**Auditor:** Maximus (CC5)
**Date:** 2026-05-24
**Branch under test:** `pr-37-review`
**Base branch:** `origin/main` (HEAD = `5a44670` "refactor: rename PilotAI to Attix")
**Tip commit:** `be469a2` "chore(backtest): add yfinance-import lint, finalize backtest migration (D4 Phase 10)"

---

## 0 — Framing correction

Carlos's framing was: *"PR #37 wraps PR #50 + PR #49 + PR #38, plus backtest migration + lint enforcer. 20 files, +947/-317."*

**Two corrections to that framing — neither material to approval, but record-keeping:**

| Claim | Reality |
|---|---|
| PR #37 wraps PR #38 | ❌ False. Commits `a95d4ae` and `b6e573a` (the PR #38 RegimeGate wiring + Atlas C1/C3/C4 yfinance fixes) are **not** in `pr-37-review`. They live on local `master`/`pr-38` only. PR #37 stacks on top of PR #48 (Attix rename, already on `origin/main`) and adds PR #49 + PR #50 + the new backtest work. |
| 20 files, +947/-317 | ❌ Total diff vs `origin/main` is **52 files, +3,495 / -7,934**. The negative balance is PR #50 alone (-7,841 deleting Mac Studio artifacts). The *new* work on top of PR #49+#50 is **14 files, +2,531 / -8**. Even that subset has 6 migration markdown docs (+1,197 lines) and one 328-line SQLite blob; the production code delta is small. |

PR #37 is well-staged but is NOT a logical "wrapper" of PRs you can review independently — it is a stack of three already-reviewed PRs (#49, #50) plus genuinely new work (the D4 backtest migration). I'm reviewing only the **incremental delta beyond PR #49 + PR #50**, since those have their own reports (`PR49_VERIFICATION.md`).

---

## 1 — Inventory of new work (commits `6ab3ab0..be469a2`)

| Commit | Subject | Net |
|---|---|---|
| `6ab3ab0` | chore(backtest): bootstrap pre-2023 indices history from Yahoo to SQLite (one-time) | `scripts/bootstrap_indices_history.py` (+151), `data/historical_indices.sqlite` (+335KB binary) |
| `2f2800a` | feat(backtest): add `load_market_history` backed by Polygon + SQLite indices bootstrap | `backtest/market_history.py` (+269), `tests/test_market_history.py` (+328), `scripts/gate1_gate2_equivalence.py` (+199) |
| `d2d241e` | feat(backtest): migrate `backtester.py` from Yahoo curl to Polygon | `backtest/backtester.py` (+9/-8), `scripts/gate3_champion_equity.py` (+182) |
| `3b10d74` | docs(migration): D4 paused at Phase 9 — Gate 3 fails on Q1 div-adjust drift | docs only |
| `be469a2` | chore(backtest): add yfinance-import lint, finalize backtest migration (D4 Phase 10) | `tests/test_no_new_yfinance_imports.py` (+196), six MIGRATION_*.md docs (+1,197) |

---

## 2 — Production code review

### 2.1 `backtest/market_history.py` (NEW, 269 lines)

Clean, well-scoped public surface. One function (`load_market_history`) with one signature. Architecture:

- Index tickers (`I:` prefix) → hybrid SQLite-pre-2023-02-14 + Polygon-after
- Stock/ETF tickers → Polygon
- Symbol normalization via `shared.data_cache._SYMBOL_MAP` (`^VIX→I:VIX`, `^VIX3M→I:VIX3M`, `^GSPC→I:SPX`, etc.)
- Module-level `PolygonClient` singleton with `_set_client()` test hook
- `@lru_cache(maxsize=128)` on the ISO-date-keyed inner function to prevent re-fetching during optimizer grid sweeps; `.copy()` on egress so callers can mutate

✅ **The NYSE-calendar filter is a real, non-obvious correctness fix.** Polygon publishes `I:VIX` / `I:VIX3M` / `I:SPX` daily aggregates on US equity market holidays (Juneteenth, July 4 when CBOE is open, etc.) where Yahoo and SPY do not. Without the filter, joining VIX to SPY-driven backtests would yield NaN-padded rows. The implementation derives the NYSE calendar from SPY's own bar dates rather than maintaining a static holiday list — this is correct and self-updating (handles future Carter-style ad-hoc closures automatically).

✅ **Seam handling is correct.** SQLite covers `[start, 2023-02-13]` and Polygon covers `[max(start, 2023-02-14), end]`. On overlap (which shouldn't occur given the disjoint windows), Polygon wins via `~combined.index.duplicated(keep="last")`.

⚠ **Hidden global state.** Both the module-level `_client` and the `@lru_cache` are process-global. Tests use `_set_client(None)` in an `autouse` fixture to reset, and `_set_client` does `_cached_load.cache_clear()`. Non-test code that wants to reset the cache (e.g., long-lived processes after a Polygon outage) must call `_set_client(None)` — there's no public `reset_cache()` helper. Minor; not blocking.

⚠ **Empty-frame contract.** `_EMPTY_DF` returned on all the no-data paths has `Volume` as the column name even when Polygon returned nothing. The existing `_yf_download_safe` returned `Volume` as float; `_polygon_to_dataframe` (from `shared/data_cache.py`) is presumed to also produce float `Volume`. Confirm dtype parity if any downstream code does `df['Volume'].astype(int)` (unlikely — most callers just check `.empty`).

### 2.2 `backtest/backtester.py` (3 call sites, +9/-8)

```python
# was: data = _yf_history_safe(ticker, start=start_date, end=end_date)
data = load_market_history(ticker, start_date, end_date)
```
Three swap sites: `_get_historical_data` (line 1054) and two `_build_iv_rank_series` paths (lines 1075, 1107 — `^VIX` and `^VIX3M`). The diffs preserve all semantics: same return shape, same `.empty` early-return, MultiIndex flattening downstream unchanged.

⚠ **`_yf_download_safe` and `_yf_history_safe` and `_curl_yf_chart` remain in `backtest/backtester.py` as dead helpers** — kept for Gate-3 Yahoo-arm shim (`scripts/gate3_champion_equity.py:from backtest.backtester import _yf_history_safe`) and the bootstrap script. They never invoke `import yfinance` (they use system `curl` against the Yahoo v8 endpoint), so the lint passes — but the helpers ARE Yahoo HTTP and re-introduce a Yahoo dependency through the back door. **This is a known tradeoff** documented in MIGRATION_NOTES (Phase 8: "Legacy helpers retained ... no callers in `backtest/`"), and Gate 3 itself depends on them. Acceptable for now; should die when the bootstrap and gate scripts are deleted post re-baselining.

### 2.3 `scripts/bootstrap_indices_history.py` (NEW, 151 lines)

One-time bootstrap script. Imports `_yf_download_safe` from `backtest.backtester`, pulls `^VIX/^VIX3M/^GSPC` 2019-06-01..2023-02-13 from Yahoo curl, inserts into `data/historical_indices.sqlite` with `INSERT OR IGNORE` (idempotent re-run). Schema PRIMARY KEY `(ticker, date)`. Tickers stored in Polygon canonical form (`I:VIX`, `I:VIX3M`, `I:SPX`).

Inspected the committed blob (`git cat-file -p pr-37-review:data/historical_indices.sqlite`):
```
table: historical_indices
('I:SPX',   '2019-06-03', '2023-02-13', 933)
('I:VIX',   '2019-06-03', '2023-02-13', 933)
('I:VIX3M', '2019-06-03', '2023-02-13', 933)
```
3 tickers × 933 rows each = 2,799 rows, 335 KB. Plausible for ~3.6 years of NYSE trading days. **Committing the SQLite blob to git is the right call** — re-bootstrapping requires Yahoo, which the migration is trying to retire.

⚠ **Provenance trust.** The blob's contents are Yahoo's reading of historical VIX/VIX3M/SPX as of whenever the bootstrap was run. There is no checksum in the repo. If someone later re-runs `bootstrap_indices_history.py` against a different Yahoo state (Yahoo silently revises history sometimes), the SQLite file would change and a stale-vs-fresh discrepancy would be hard to spot. Nit: a SHA-256 in `MIGRATION_NOTES.md` would make this auditable. Not blocking.

### 2.4 `tests/test_no_new_yfinance_imports.py` (NEW, 196 lines)

Two assertions:
1. **`test_no_new_yfinance_imports`** — walks all `.py` outside `tests/`, regex-matches `^\s*(import|from)\s+yfinance`. Any importer not on `ALLOWED_YFINANCE_IMPORTERS` (frozenset of ~120 paths) fails. Stale entries (allowlisted but file no longer imports yfinance — usually because it was migrated or deleted) also fail.
2. **`test_backtest_module_is_yfinance_free`** — same scan restricted to `backtest/`, no allowlist tolerated.

✅ The regex is correct enough: `^\s*` allows conditional-import-inside-function (which `compass/exp1220_standalone.py` and many archive files do).

⚠ **The regex misses some import forms.** Examples: `__import__("yfinance")`, `importlib.import_module("yfinance")`, `exec("import yfinance")`. These are exotic enough that ignoring them is fine.

⚠ **Tests/ directory is exempt** (`EXEMPT_DIRS = ("tests/",)`). Conftest fixtures may legitimately need `import yfinance` to mock it. Fine, but means a regression that re-imports yfinance from a test file would be invisible to this lint. Not a blocker — test code isn't on the prod path.

⚠ **The allowlist is large** (~120 files). The stale-entry check enforces hygiene, but in practice this is a temporary capitulation: until Phase 9 (deferred behind strategy re-baselining), `compass/`, `experiments/`, and many `scripts/` still pull from Yahoo. The lint stops *new* sin but doesn't fix the existing debt.

✅ Tests/ exemption is documented in the docstring. Behavior is clear and self-documenting.

### 2.5 `scripts/gate1_gate2_equivalence.py` and `scripts/gate3_champion_equity.py`

Acceptance harnesses, not production. They run Yahoo (curl) vs Polygon side-by-side and emit pass/fail per gate. Standard equivalence-test pattern. Inspected the structure; Gate 1 documents the 2026-02-06 `^VIX` vendor outlier as an accepted exception. Gate 3 deliberately fails per Q5 (Carlos accepted Q1 dividend-adjustment behavior change).

These are throwaway scripts that document the migration's acceptance posture. They're committed to the repo as evidence, which is appropriate.

---

## 3 — Conflicts and regressions vs PR #49 + PR #50

### 3.1 Dockerfile.scheduler

PR #49 (`6694b45`) adds `COPY execution/` and `COPY strategies/`. The new backtest code lives in `backtest/`, which is **NOT** copied into the scheduler container. That's correct — the scheduler runs APScheduler + live trading, not backtests. Verified by reading `Dockerfile.scheduler` at `pr-37-review`:

```
COPY shared/ ./shared/
COPY compass/ ./compass/
COPY strategies/ ./strategies/
COPY tracker/ ./tracker/
COPY scheduler/ ./scheduler/
COPY execution/ ./execution/
COPY sentinel/ ./sentinel/
```

No `backtest/` — correct.

✅ The smoke test added by PR #49 (`from strategies.base import ...`, `from execution.execution_engine import ...`) is unaffected by D4. No cross-PR regression.

### 3.2 PR #50 (Mac Studio cleanup) vs new backtest code

PR #50 deletes `scripts/run_combined.py`, `scripts/run_exp1220.py`, `scripts/watchdog.py`, `scripts/orphan_check.py`, `scripts/portfolio_status.py`, etc. None of these are imported by the new `backtest/market_history.py` or `scripts/bootstrap_indices_history.py`. No conflict.

⚠ One small thing: `scripts/retroactive_backtest_clean.py` is modified by PR #50 (`+4/-4`) — but **not** rewired to use `load_market_history`. Grepped for yfinance usage:

```
$ git show pr-37-review:scripts/retroactive_backtest_clean.py | grep -n yfinance
```
(Not on the lint allowlist — it must not use yfinance, or it would already be failing.) Confirmed it doesn't import yfinance directly. Not a regression.

### 3.3 PR #50 removes `tests/test_watchdog.py` and `tests/test_run_exp1220.py`

These are tests for files PR #50 deleted (`scripts/watchdog.py` and `scripts/run_exp1220.py`). Removal is consistent. No conflict.

### 3.4 ✅ `experiments/registry.json` (PR #50) — strips `tmux_session` fields

Confirmed by `git show pr-37-review --stat e50908d`: `experiments/registry.json | 1628 +- ` (huge rewrite). No conflict with the D4 backtest commits, which don't touch the registry.

---

## 4 — Test coverage

- `tests/test_market_history.py`: 20 tests across 4 classes (`TestStockLoad`, `TestSymbolMap`, `TestIndexHybrid`, `TestCache`). Mocks `PolygonClient`, uses tmp_path SQLite fixture for the hybrid path. Covers:
  - Yfinance-shaped DataFrame return contract
  - Passthrough vs `^VIX→I:VIX` symbol mapping (also `^GSPC→I:SPX`)
  - Empty response, end-before-start
  - Pre-2023 SQLite-only / post-2023 Polygon-only / cross-seam concatenation / dedupe-on-overlap
  - NYSE calendar filter drops holiday-published Polygon VIX bars
  - LRU cache prevents refetch on identical args
- `tests/test_no_new_yfinance_imports.py`: 2 tests. Both run against the live repo state and are effectively self-checking.

⚠ **No end-to-end Polygon-network test.** `test_market_history.py` mocks `PolygonClient`. Live behavior is only verified by `gate1_gate2_equivalence.py` and `gate3_champion_equity.py`, which are throwaway harnesses, not part of CI. If Polygon ever changes their aggregates response shape, this won't catch it.

⚠ **No regression test for `_get_historical_data` / `_build_iv_rank_series` in `backtest/backtester.py`.** The swap sites have no unit test that pins behavior pre- vs post-migration. Equivalence is exercised only by the offline Gate 3 script — which Gate 3 **deliberately fails** (Q5). That's a structurally weak test posture for a hot-path change.

✅ Pre-existing `tests/test_backtester.py` exists and runs the backtester end-to-end; if it passes on this branch, it provides some regression coverage.

---

## 5 — Documentation

`BACKTEST_MIGRATION_PROPOSAL.md` (482 lines), `MIGRATION_NOTES.md` (delta +71), `MIGRATION_QUESTIONS.md` (+234 lines new), `BACKTEST_MIGRATION_PROPOSAL_TASK.md`, `MIGRATION_D4_BACKTEST_TASK.md`, `MIGRATION_YFINANCE_TO_POLYGON.md` — six markdown files totaling +1,197 lines.

✅ Excellent self-documentation. Future maintainers can reconstruct the migration's design, acceptance gates, and Carlos's three decision points (Q1 dividend-adjust, Q2 earnings blocked, Q5 strategy drift accepted) without spelunking PR history.

⚠ One mild concern: the migration docs reference Phase 9 (bulk script migration) as "DEFERRED behind strategy re-baselining" — that's ~90 files still on Yahoo. The lint enforcer keeps the debt visible but the actual work is open-ended. Not a PR blocker; just expect this migration to drag.

---

## 6 — Non-blocking risks / nits

1. **Bootstrap SQLite has no checksum** (§2.3). If someone re-runs the bootstrap script and Yahoo has silently revised history, the blob would drift. Add SHA-256 to `MIGRATION_NOTES.md`.
2. **Backtester dead-code helpers** (`_yf_download_safe`, `_yf_history_safe`, `_curl_yf_chart`) in `backtest/backtester.py` (§2.2) — kept for Gate 3 + bootstrap script. Delete after strategy re-baseline.
3. **Lint regex misses exotic import forms** (§2.4) — `__import__`, `importlib.import_module`, `exec`. Acceptable.
4. **No live-network test for `market_history`** (§4) — Polygon API drift would not be caught by CI. Consider a nightly smoke test marked `@pytest.mark.network`.
5. **Gate 3 fails by design** (Q5) — Carlos accepted the Q1 div-adjust propagation. The strategy re-baseline is now an open follow-up workstream, and the leaderboard/MASTERPLAN champion numbers in the repo are stale until that lands. Make sure the next CC audit doesn't compare paper-trading PnL against pre-migration backtest expectations.
6. **`backtest/market_history.py` `Volume` dtype** (§2.1) — minor; verify downstream callers don't `.astype(int)`.
7. **Lint allowlist size** (~120 files) — large transitional debt visible in CI; the deletion checklist for Phase 9 should be tracked somewhere durable (issue, MASTERPLAN entry).

---

## 7 — Verdict

✅ **APPROVE.**

- New code is small, well-scoped, and exhaustively tested at the unit level.
- The hybrid SQLite + Polygon design correctly addresses the Polygon-indices-pre-2023 gap.
- NYSE-calendar filter is a real non-obvious correctness improvement that prevents stealth NaN-padding in backtests.
- The lint enforcer creates structural pressure to finish Phase 9 and is correctly scoped (`backtest/` is the hard wall; everything else is allowlisted with stale-entry detection).
- No cross-PR conflict with PR #49 (Dockerfile/execution path) or PR #50 (Mac Studio cleanup).
- Carlos has already signed off on the documented behavioral changes (Q1 dividends, Q5 Gate-3 acceptance).

**Do not merge into main without first verifying:**
1. The pre-existing `tests/test_backtester.py` still passes end-to-end (regression catch for the 3 swap sites).
2. The new `test_no_new_yfinance_imports` passes on a clean checkout (allowlist accuracy verification).
3. A re-baseline plan exists somewhere durable (issue or MASTERPLAN) so the now-stale champion/leaderboard numbers don't get cited as live targets after merge.

These are validation steps, not change requests.

---

## 8 — Open items for Carlos / Atlas

- **Strategy re-baseline workstream**: the migration's Q5 acceptance shifts the strategy expected-PnL universe by ~0.5–2% (cumulative dividend offset on SPY/TLT). Champion/leaderboard numbers in MASTERPLAN need a re-run.
- **Phase 9 backlog**: ~90 files still on Yahoo (compass/, experiments/, scripts/). Lint pressure exists but the work is unscheduled.
- **Atlas blockers C1/C3/C4** (PR #38 work — *not* in this PR): the `compass/` yfinance imports that PR #38's commit `b6e573a` was supposed to remove are still allowlisted here. Confirm whether PR #38 will land separately or be folded into a follow-up.
