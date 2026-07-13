# EXP-P2B — Event-Premium Harvesting (FOMC/CPI/NFP) — PRE-REGISTRATION (committed before any run)

**Date:** 2026-07-13 · **Author:** cc2 · **Program:** `research/PROFITABILITY_PROGRAM.md` §EXP-P2B (Carlos Wave-2 GO, 2026-07-13)
**Integrity rule:** committed BEFORE the first variant result is computed; post-hoc changes void the experiment.
**Harness:** `backtest/multileg.py` (shared, `f411fa9`); holdout seal active in the runner.
**Friction ledger citation:** `research/FRICTION_LEDGER.md` — short-DTE iron flies are "alive and friction-cheap" on SPY/QQQ (5.6–8.6% min-edge, the best premium-to-friction ratio of any short structure measured). 4-leg friction $35.20/RT.

## Governance checklist

1. **New mechanism — signal source:** the event calendar + a measured pre-event richness threshold. No deployed or mined strategy conditions on scheduled-event premium richness; EXP-3311's NFP gate is rejection-side evidence only (event days carry uncompensated gap risk for *always-on sellers*), flipped here into a conditional seller, exactly as the program doc frames it. Structure choice per the program doc's provision ("iron flies … decided at prereg time"): **iron flies on SPY and QQQ** — 4-leg defined-risk, short ATM straddle core; not a vertical, outside the closed SPY put-credit-vertical family. Carlos's Wave-2 GO names this experiment; Maximus receives this prereg (and delivers results) per the same GO.
2. **Provenance:** event-vol overpricing literature (`research/lit_review_2024_2026.md`); calendars are real published dates (`compass/orchestrator/calendars/{fomc,cpi}_2020_2025.csv` — Fed/BLS sources documented in-file) plus the deterministic BLS NFP schedule already validated in EXP-P1F's prereg. No variant derives from the mined leaderboard.
3. **Windows:** 2020-01-02 → 2024-12-31 in-sample dev; holdout sealed.
4. **Marketable fills only**; naive-fallback share reported.

## Event set (fixed)

Union of: FOMC **scheduled** decision days (rows marked UNSCHEDULED excluded — an emergency meeting is not forecastable, so no seller could have positioned the day before), CPI release days, NFP release days (first-Friday rule with the two holiday adjustments validated 12/12 in the P1F prereg). ~160 events in-window. Event day T; entry day = last trading day before T; exit = first trading day after T (time-based; see exits).

## Richness signal (fixed — the treatment variable, causal form, no fitting)

R = (ATM straddle close on entry day, front expiry / spot) ÷ (mean |daily close-to-close return| of the underlier over the trailing 21 trading days).
Numerator = implied ~event-window move; denominator = realized daily move. **Enter iff R ≥ 1.25** (pre-stated once, from the literature's order of magnitude for event-vol overpricing; the unconditional control variant E2 exists precisely so this constant's effect is attributed, not assumed). Underlier closes from the shared Polygon-backed loader (real data, cache-backed); straddle marks from `option_daily`.

## Structure and lifecycle (all variants)

- **Iron fly:** SHORT 1 ATM call + SHORT 1 ATM put (strike nearest spot), LONG 1 call at ATM+2% and LONG 1 put at ATM−2% (nearest listed), all same expiry = earliest expiration in [T+1, T+10] (the structure must live through the event and die soon after).
- **Entry:** on the entry day via the harness day-limit (FIX #3 semantics, 4 legs).
- **Exits (fixed, in order):** stop at 2.5× credit (ledger IC convention — tail guard through the event); time exit on the first trading day after T (harness `time_stop(2)` calendar-day rule; weekend events exit the next session). No profit target — the trade IS the event-decay window.
- **Sizing:** contracts = floor($2,500 / ((wing width − credit) × 100)), min 1, cap 25; max 2 concurrent positions (event clusters).

## The 6 variants (final; single-mechanism)

| # | Variant | Definition | Role |
|---|---|---|---|
| E1 | SPY-all-gated | SPY, all events, R ≥ 1.25 | **Primary hypothesis** |
| E2 | SPY-all-uncond | SPY, all events, no richness gate | **Mechanism control** — is the gate doing anything? |
| E3 | QQQ-all-gated | QQQ, all events, R ≥ 1.25 | Second underlier stream |
| E4 | SPY-FOMC-gated | E1 restricted to FOMC | Attribution by event type |
| E5 | SPY-CPI-gated | E1 restricted to CPI | Attribution |
| E6 | SPY-NFP-gated | E1 restricted to NFP | Attribution |

## Acceptance criteria (fixed now)

**Pass (per variant):** total return > 0; expectancy > $0 net; MaxDD ≥ −20%; worst year ≥ −15%; ≥ 40 closed trades; fallback share ≤ 20%. E4–E6 are attribution reads first — with 8–12 events/yr each, the 40-trade floor makes them pass-eligible only if the gate passes most events; a starved E4–E6 is reported as attribution, not failure.
**Gate-informativeness check (pre-stated):** if R ≥ 1.25 admits < 20% or > 95% of events, the richness gate is uninformative — E1 is then judged as (approximately) E2 and the "signal source" claim fails even if P&L passes; report says so explicitly.
**Correlation (Wave-2 rule):** any passer reports Pearson correlation of monthly (primary) and daily (secondary) returns vs A4-as-passed (`results/p1a_A4.json`); "independent stream" language requires < +0.5.
**Multiple comparisons:** 6 variants (E1⊃E4–E6 heavily overlapped; effectively ~3 independent observations) → ~0.3 spurious passers expected; a lone marginal passer is weak evidence by construction.

## Kill criteria (pre-stated)

- E1 **and** E2 both negative → event-premium family closed on SPY at this structure; no threshold search, no structure search.
- Median realized credit in the sample < 2× the $35.20 4-leg friction (ledger DOA applied to the realized trade set) → "friction-dead as traded," regardless of P&L sign.
- Fewer than 60 total qualifying events found in-window (calendar/data defect) → data verdict, not strategy verdict.

## Procedure

1. This prereg commits first. 2. Runner `experiments/wave2/run_p2b.py` (shared harness; holdout guard) runs E1–E6 marketable-only. 3. JSONs → `experiments/wave2/results/` (gitignored). 4. Report → `reports/profitability_program/EXP-P2B.md` with machine-readable JSON (per-variant trades, total_return, cagr, win_rate, sharpe, max_dd, worst_year, expectancy_per_trade, fallback share, events_admitted_pct, realized_median_credit_vs_friction, corr_vs_A4 for passers). 5. No holdout touch.
