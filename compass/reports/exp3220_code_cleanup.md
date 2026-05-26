# EXP-3220 — Code Archaeology and Cleanup

**Generated:** 2026-05-06
**Scope:** `/home/node/.openclaw/workspace/pilotai-credit-spreads/compass/`
**Mode:** Static import-graph analysis + import smoke test + scoped pytest run
**Action taken:** **Zero file moves.** See §4 for rationale.
**Baseline tests:** 250 passed, 1 skipped (compass-related subset).

---

## 1. Brief vs. reality

The task brief described "264 archival candidates in compass/" and asked for a
move into `compass/archive/`. Two prior facts change the operating context:

1. **`compass/archive/` already exists** with **357 `.py` files**, populated by
   commit `f93e0a8 chore: archive 357 dead code modules per DEAD_CODE_INVENTORY`.
   Further archival would extend, not initiate, that effort.
2. **The "264" figure** comes from `compass/PRODUCTION_MANIFEST.md` line 85
   ("Unlinked Modules (~264)"), not from MASTERPLAN. Two prior reports
   already document this provenance:
   - `compass/reports/code_archaeology_audit.md` (2026-04-28)
   - `compass/reports/code_archaeology_20260429.md`

   Both reports recommend pausing further archival until the §3.1 reconciliation
   issue (production files mislocated in `archive/`) is resolved.

This report respects the user-set criterion ("ZERO imports from production
code") and re-runs the analysis on today's tree.

---

## 2. Inventory snapshot

| Location | `.py` files |
|---|---:|
| `compass/` (top-level) | 54 |
| `compass/archive/` | 357 (already archived) |
| `compass/crypto/` | 11 |
| `compass/experiments/killed/` | 16 |
| `compass/scripts/` | 1 |
| `compass/tests/` | 1 |
| **Total** | **440** |

---

## 3. Import-graph results — top-level `compass/*.py`

For each top-level module, counted distinct files anywhere in the workspace
(excluding the module itself) that contain `from compass.<mod>`,
`from .<mod>`, `import compass.<mod>`, or `compass.<mod>.` references.

### 3.1 Zero-inbound modules (5 of 54)

| Module | Inbound | `__main__`? | Verdict |
|---|---:|:---:|---|
| `alpaca_connector.py` | 0 | yes | **KEEP — production entry point** (manifest §"Production Entry Points"). Alpaca order/position CLI; cron-invoked. |
| `exp2300_portfolio_runner.py` | 0 | yes | **KEEP — completed standalone experiment** (Wave 8 per audit §2.2). Manifest's documented "105 standalone experiments" policy. |
| `exp3150_post2020_retest.py` | 0 | yes | **KEEP — recent standalone experiment**. Same policy. |
| `exp3151_stream_attribution.py` | 0 | yes | **KEEP — recent standalone experiment**. Same policy. |
| `exp3200_monte_carlo_stress.py` | 0 | yes | **KEEP — recent standalone experiment** (the EXP-3200 work that immediately precedes this EXP-3220 task). Same policy. |

All five are intentional artifacts: one CLI entry point, four `__main__`-bearing
research scripts. **None match "killed or superseded" dead code.**

### 3.2 Low-inbound (1–3) — all production-stack

| Module | Inbound | Manifest tier |
|---|---:|---|
| `dollar_notional_sizer.py` | 1 | Phase 10 prereq (MASTERPLAN §9) |
| `exp2370_dd_circuit_breaker.py` | 1 | Transitive dep |
| `exp2850_v8a_with_vix_ladder.py` | 1 | Production dep |
| `exp1660_vrp_deepening.py` | 2 | Wave 1 standalone |
| `exp1850_regime_portfolio.py` | 2 | Transitive dep |
| `exp2830_paper_signal_generator.py` | 2 | Production entry point |
| `exp2200_north_star_v6.py` | 3 | Production dep |
| `exp2240_qqq_iwm_credit_spreads.py` | 3 | Production dep |
| `exp2390_robust_cov_audit.py` | 3 | Transitive dep |

Every low-inbound module is named in `PRODUCTION_MANIFEST.md`. None are dead.

### 3.3 ML stack — flagged by prior audit, not dead

The prior audit (§2.5) flagged five top-level ML modules as candidates for
"decide" because they're absent from the production manifest. Today's
inbound trace:

| Module | Inbound | Importers (sample) | Verdict |
|---|---:|---|---|
| `ml_strategy.py` | 5 | `tests/test_ml_strategy*.py`, `compass/__init__.py` | KEEP — actively tested |
| `shadow_ensemble.py` | 5 | `ml/regime_model_router.py`, `tests/test_shadow_ensemble.py` | KEEP — used by `ml/` |
| `online_retrain.py` | 8 | `tests/test_online_retrain.py`, `tests/test_shadow_ensemble.py`, `compass/archive/retrain_scheduler.py` | KEEP — actively tested |
| `signal_model.py` | 18 | `ml/__init__.py`, `scripts/run_x003_combined.py`, `compass/{ml_strategy,online_retrain,shadow_ensemble}.py`, many tests | KEEP — heavily used |
| `ensemble_signal_model.py` | 25 | `main.py`, `ml/regime_model_router.py`, `scripts/{backtest_ml_filter,safe_kelly_backtest,exp700_*,retrain_*}.py`, many tests | KEEP — production for the non-paper ML pipeline |

The manifest is paper-trading-pipeline-scoped; `ml/`, `main.py`, and
`scripts/` constitute a *separate* production surface that imports this
stack. The audit's "absent from manifest" flag is correct but the implied
"dead" inference was wrong.

### 3.4 `compass/crypto/` — flagged "unused" by audit, not dead

| Path | Inbound refs |
|---|---:|
| `compass/crypto/*` | 62 references across 5 files |

Importers: `backtest/backtester.py`, `scripts/run_crypto_snapshot.py`,
`tests/test_crypto_collectors.py`, `tests/test_crypto_score.py`,
`tests/test_historical_score.py`. **Not dead.**

### 3.5 Utility modules (top-level)

| Module | Inbound | Verdict |
|---|---:|---|
| `regime.py` | 56 | core, KEEP |
| `metrics.py` | 41 | core, KEEP |
| `crisis_alpha.py` | 28 | transitive dep, KEEP |
| `crisis_alpha_v3.py` | 21 | transitive dep, KEEP |
| `exp1220_standalone.py` | 19 | production dep, KEEP |
| `signal_model.py`, `macro_db.py`, `exp2080_corr_regime.py` | 18 each | KEEP |
| `crisis_hedge.py`, `macro.py`, `risk_gate.py` | 14–17 | KEEP |
| `stress_test.py`, `exp2160_high_capacity_alts.py`, `exp2360_robust_cov.py` | 15–16 | KEEP |
| `crisis_alpha_v5.py` | 14 | production dep, KEEP |
| (… all remaining ≥1 inbound …) | 4–13 | KEEP |

No module above the zero-inbound cutoff lacks a documented role.

---

## 4. Action: zero moves

Under the user-set criterion *"files that have ZERO imports from production
code"* applied to today's tree, **the safe move-set is empty**:

- The five zero-inbound top-level files are intentional standalone
  artifacts (one CLI, four `__main__` experiments).
- Every other top-level file has at least one inbound import from
  production code, tests, scripts, the `ml/` package, or other compass
  modules.
- The 357 files that *do* meet the criterion are *already* in
  `compass/archive/` from the prior cleanup commit `f93e0a8`.
- `compass/crypto/` and `compass/experiments/killed/` both have
  documented, active roles and are out of scope for archival.

**No files were moved, deleted, or renamed.** Adding sub-bucket directories
under `compass/archive/` (`experiments/`, `prototypes/`, `superseded/`)
without first establishing a verdict registry would worsen, not improve,
the existing provenance gap (audit §3.2). It is deferred to the
reconciliation work in §6.

---

## 5. Test status

**Smoke import test** (20 critical production + ML stack modules):
`20/20 OK`.

**Scoped pytest run** (`-k "compass or crisis_alpha or signal_model or
ensemble or shadow"`, `--ignore=tests/archive`, `--no-cov`):
**250 passed, 1 skipped, 0 failed** in 3.95s.

This is a baseline only — no code changed in this experiment, so the
result equals the pre-EXP-3220 state. Recorded for completeness.

---

## 6. Real cleanup work, deferred to a follow-up

The actual outstanding cleanup risk is *not* "move more files into
`archive/`." It is the inverse problem: `compass/archive/` currently
contains 13 files that `PRODUCTION_MANIFEST.md` (2026-04-23) names as
production entry points or dependencies. Audit §3.1 enumerates them:

```
exp2670_paper_gonogo.py            (Entry point)
exp2860_paper_dry_run.py           (Entry point)
exp2900_v8a_consistency_audit.py   (Entry point)
exp2580_spy_weekly_cs.py           (Production dep)
exp2820_flash_crash_protection.py  (Production dep)
paper_monitor_dashboard.py         (Production dep)
paper_trading_monitor.py           (Production dep)
prod_monitor.py                    (Production dep)
exp2710_xle_integration.py         (Transitive dep)
exp2750_oos_regime_stress.py       (Transitive dep)
exp2470_execution_optimization.py  (MASTERPLAN §9)
exp2510_broker_analysis.py         (MASTERPLAN §9)
exp2540_regime_tc_model.py         (MASTERPLAN §9)
exp2570_commfree_net_sharpe.py     (MASTERPLAN §9 — Sharpe 6.00 calc)
exp2640_vix_stress_hardening.py    (MASTERPLAN §9)
```

`compass/archive/` deliberately lacks `__init__.py`, so any production
import of these modules would fail at runtime. Today's smoke test passed
because nothing in the test surface actually imports them by their
manifest-claimed paths — i.e., **either the manifest is stale or paper
trading is silently broken at the entry-point level.** Verifying which is
the case is the real EXP-3220 follow-up.

### Recommended next actions (in order)

1. **Reconcile manifest vs. archive.** Decide per-file: (a) restore to
   top-level if still production, (b) update manifest if genuinely
   archived. Do this before any further archival.
2. **Add `compass/archive/README.md`** with a per-file verdict registry
   mirroring `experiments/killed/README.md`. Without it, the 357
   already-archived files have no provenance trail.
3. **Fix `experiments/killed/README.md` header** — it claims
   `compass/archive/` and "(23 files)" but lives at
   `experiments/killed/` with 16 files.
4. **Reclassify the late-numbered killed experiments** flagged in
   `PRODUCTION_MANIFEST.md` §"Standalone Experiments"
   (`exp2810_9stream_portfolio.py`, `exp2910_tlt_credit_spreads.py`,
   `exp2920_tlt_ivrv_arb.py`, `exp2950_sector_momentum.py`) into
   `experiments/killed/` so they get verdicts.

None of the above were performed in this experiment.

---

## 7. Summary

| Item | Result |
|---|---|
| Files moved | 0 |
| Files deleted | 0 |
| Imports rewritten | 0 |
| `compass/archive/` size | unchanged (357 files) |
| Top-level zero-inbound files identified | 5 (all intentional, all KEEP) |
| Tests run | 251 (250 pass, 1 skip, 0 fail) |
| Reconciliation issues surfaced | 13 manifest-vs-archive mismatches (deferred) |

The honest answer to "what's truly dead at compass/ top-level?" today is
**nothing** — under any reasonable criterion. The dead code was already
moved by commit `f93e0a8`. The remaining work is reconciliation, not
archival, and is documented for the next experiment.

---

*Report is read-only inventory + test baseline. No file system mutations
occurred.*
