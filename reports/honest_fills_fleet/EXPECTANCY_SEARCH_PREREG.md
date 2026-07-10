# Bounded Expectancy Search — PRE-REGISTRATION (committed before any variant is run)

**Date:** 2026-07-10 · **Author:** cc1 · **Authority:** cc1 proposal Rev 3, step 3
**Integrity rule:** this document is committed to git BEFORE the first variant result is computed. Any change to variants or criteria after results exist voids the search.

## Purpose

Every deployed strategy failed the honest-fills edge gate (`FLEET_ROLLUP.md`: 0/9 positive, 5/9 ruin). This is a **bounded, one-pass search** for a configuration of the SPY put-credit-spread family with positive expectancy under honest (marketable) fills — explicitly NOT a re-run of the 150-experiment fishing era. The instrument is the same faithful harness that retired EXP-1220 (`experiments/honest-fills-fleet/`, FIX #3 `fill_model=marketable`, real marks, offline).

## Base configuration (control, V0)

`exp1220_faithful` as defined in `run.py` (daily entries, 5 % OTM, DTE 21–45 target 30, 5-wide, min-credit 6 %, PT 50 %, SL 2.0×, 9.35 % flat non-compounding, ≤ 20 contracts / 5 positions / 3 per expiration, `vix_max_entry` 35, `manage_dte` 5, combo regime ma_slow 50, ICs off). Known result (full window, marketable): −91.4 %, every year negative. V0 is re-scored on the search window as the reference; it is not a candidate.

## The 12 variants (final — no additions after this commit)

Single-mechanism variants isolate attribution; two composites test the most-causal combinations. All are V0 plus the stated change only. All run **marketable fills only**.

| # | Variant | Change vs V0 | Causal rationale |
|---|---|---|---|
| V1 | weekly-cadence | Entries Mondays only | Fewer overlapping positions → less stacked tail exposure, lower friction share; the (phantom) behavior that flattered the first twin, now tested for real |
| V2 | trend-gate | No entries unless prior-day SPY close > 200d MA | Don't sell puts into downtrends; targets the −70 %/−78 % 2022 bleed directly |
| V3 | real-breaker | HWM month-anchored breaker: DD ≤ −5 % from month-start NAV → halve size; ≤ −10 % → halt entries; resume next month at half, full after a positive month | Bounds loss-compounding; §2 of the cc1 proposal, never actually implemented anywhere |
| V4 | delta-15 | `use_delta_selection`, target Δ 0.15 | Fixed 5 % OTM mis-sizes risk across vol regimes (tiny credit in calm, high Δ in storms); constant-delta normalizes the sold risk |
| V5 | delta-10 | `use_delta_selection`, target Δ 0.10 | Same mechanism, further OTM: fewer stop-outs at lower credit — tests which side of the credit/stop trade-off pays |
| V6 | credit-floor-10 | `min_credit_pct` 6 → 10 | Only sell when premium is rich enough to fund the stop-outs; skips low-VRP days |
| V7 | tight-stop | SL 2.0× → 1.0× credit (PT 50 unchanged) | The dominant loss path is stop-outs at −2× credit vs wins of +0.5×; halving the loss unit flips the win-rate arithmetic if fills allow |
| V8 | wide-exit | PT 50 → 65, SL 2.0× → 1.5× | Capture more of the premium decay per winner while modestly tightening the loss unit |
| V9 | nfp-gate | No entries on T-1 and T0 of NFP releases (deterministic BLS calendar, `run_twin.py` port) | The one mechanism with a live save on the record (EXP-3311 dodging Jun-05); scheduled-event gap risk is uncompensated at entry |
| V10 | contango-gate | No entries when VIX ≥ VIX3M (backwardation) | Backwardation = crash pricing; VRP harvesting historically pays in contango and blows up in backwardation |
| V11 | trend+delta15 | V2 + V4 | The two strongest independent mechanisms if singles show signal; direction-gated, risk-normalized harvest |
| V12 | all-protections | V2 + V3 + V9 | "The config the YAML pretended to be": trend filter + real breaker + event gate together |

## Windows and procedure

- **Search window:** 2020-01-02 → 2024-12-31. All 13 runs (V0 + 12) execute here.
- **Holdout:** 2025-01-02 → 2026-04-02. **Only search-window passers run the holdout, exactly once, unmodified.** A variant that fails holdout is dead — no tuning, no second shot. Failed variants' holdout is never run (keeps the holdout unmined for any future search iteration, which would require a fresh pre-registration).
- Runs execute from the committed harness; results land in `experiments/honest-fills-fleet/results/search_*.json` (gitignored per repo convention); the scored report is committed as `EXPECTANCY_SEARCH_RESULTS.md`.

## Acceptance criteria (fixed now)

**Search-window pass — ALL of:**
1. Total return > 0 %
2. Expectancy per trade > $0 (net of modeled commissions + slippage, marketable fills)
3. Max drawdown ≥ −20 %
4. Worst calendar year ≥ −15 %
5. ≥ 40 closed trades (statistical floor; a passer with < 40 trades is "insufficient sample," not a pass)

**Holdout pass — ALL of:** total return > 0 %, expectancy > $0, MaxDD ≥ −20 %.

**Program outcome:** variants passing BOTH windows re-enter the launch pipeline at G2 (fresh-paper fidelity, ≥ 2 NFP prints) per proposal Rev 2/3. If zero variants pass, the search reports that result and stops — the documented conclusion becomes "this family cannot clear retail frictions at survivable sizing," and any further search requires a new pre-registration with new mechanisms (not parameter jitter on these).

## Multiple-comparisons honesty

Twelve candidates, one-sided selection: at ~5 % false-positive rate per variant, the expected number of spurious search-window passers is ~0.6 — the single-shot holdout exists to absorb exactly that. A holdout pass after a search pass is still only ~2 quarters × 1 regime of out-of-sample evidence; G2 paper fidelity and the G4 micro-live remain mandatory. No result from this search authorizes capital by itself.
