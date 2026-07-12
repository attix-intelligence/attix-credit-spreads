# EXP-P1B — Calendar/Diagonal Term-Structure VRP — PRE-REGISTRATION (committed before any run)

**Date:** 2026-07-13 · **Author:** cc2 · **Program:** `research/PROFITABILITY_PROGRAM.md` §EXP-P1B (Carlos Wave-2 GO, 2026-07-13: "write the preregs for the three shared-harness Wave 2 experiments — P1B (GLD calendar/diagonal spreads, term-structure VRP)…")
**Integrity rule:** committed BEFORE the first variant result is computed; any post-hoc change to variants or criteria voids the experiment.
**Harness:** `backtest/multileg.py` (cc4's shared direct-marks multi-leg harness, commit `f411fa9`) — real cached marks only, FIX #3 marketable semantics generalized to N legs, holdout seal (`assert_holdout_seal`) active in the runner.
**Friction ledger citation (program rule):** `research/FRICTION_LEDGER.md` — ATM calendars are the most friction-efficient premium structures measured: SPY 5.2% / QQQ 4.6% min-edge of debit, GLD 13.4%, TLT 23.8%; all four clear DOA. The ledger itself recommends adding SPY/QQQ calendars to this prereg ("calendars are a *new structure*, so SPY/QQQ calendars are governance-eligible").

## Governance checklist

1. **New mechanism:** structure = calendars/diagonals (short front-month + long back-month) — not verticals, not iron condors; payoff and risk driver (term-structure carry, vega) differ in kind from the closed SPY put-credit-vertical family. Named and approved in the program doc and in Carlos's Wave-2 GO relayed 2026-07-13 (checklist item 1 confirmation in writing).
2. **Provenance:** term-structure carry literature (`research/lit_review_2024_2026.md`); v8a's GLD/SLV calendar streams (research pre-dating the mined search). No variant derives from the mined SPY leaderboard. The tail-risk claim is structural: max loss = debit paid, bounded at entry by construction — "addresses 2022 by construction, not by gate."
3. **Windows:** 2020-01-02 → 2024-12-31, explicitly in-sample dev. Holdout sealed (guard enforced in code; `HOLDOUT_SPEND_SIGNED` unset).
4. **Marketable fills only.** All-legs daily-bar day-limit semantics; `naive_fallback` share reported (expected ~0: 100% of 2020–24 bars carry opens — verified pre-commit).

## Reference structure (all variants share unless the variant says otherwise)

- **ATM put calendar:** SHORT 1 front-month put (target 15 DTE, window 10–25), LONG 1 back-month put (target 45 DTE, window 35–60), same strike = nearest listed strike to parity-inferred spot (strike minimizing |C−P| on the front chain — the P0A method; no external feed).
- **Entries:** Mondays (first trading day of the week on the marks clock); max 3 concurrent positions; skip if an open position shares the front expiration.
- **Sizing (fixed):** contracts = floor($2,500 / (net debit × 100)), min 1, **cap 25** — modeled max loss (= debit) ≤ 2.5% of the $100k reference account per trade, ≤ 7.5% book.
- **Exits (fixed, evaluated in order):** profit target +30% of debit; stop −50% of debit; close when front leg ≤ 5 DTE (no pin/expiry risk carried).
- **Friction:** harness engine-parity ($0.65/contract/side; $0.05/$0.10 per pair entry/exit slippage).

## The 6 variants (final — no additions after this commit; single-mechanism: one delta each)

| # | Variant | Definition | Rationale (causal, per-variant provenance) |
|---|---|---|---|
| B1 | GLD-cal | Reference on GLD | The program's named stream; metals term-structure VRP (v8a GLD calendar research, pre-mined-search) |
| B2 | SPY-cal | Reference on SPY | Ledger-recommended addition; most liquid chain, 5.2% min-edge |
| B3 | QQQ-cal | Reference on QQQ | Ledger-recommended; 4.6% min-edge — also the correlation question vs A4 (same underlier, different structure) |
| B4 | TLT-cal | Reference on TLT | Rate-vol term structure; 23.8% min-edge clears DOA; rides the P1F question with a structure whose fills P1F never tested |
| B5 | GLD-diag | B1 but the LONG back leg one listed strike below ATM (~2–3% OTM) | The "diagonal" of the title: cheaper debit, higher theta share — single delta vs B1 |
| B6 | SPY-call-cal | B2 but calls both legs | Is the term premium put-specific or two-sided? Single delta vs B2 |

## Acceptance criteria (fixed now)

**Pass requires ALL of (per variant):** total return > 0; expectancy > $0 net of modeled friction; MaxDD ≥ −20%; worst calendar year ≥ −15%; ≥ 40 closed trades; naive-fallback share ≤ 20%.
**P1B-specific (program doc):** (a) **mark-trust gate** — max single-trade realized loss ≤ 1.5× modeled max (debit + friction); a breach means the pricing path is untrustworthy and **fails the variant regardless of P&L**; (b) **data-sufficiency kill** — stale-mark day share > 20% → verdict "data insufficient," not a strategy result.
**Correlation report (Wave-2 requirement):** any passer reports Pearson correlation of monthly (primary) and daily (secondary) returns vs **A4 as passed** (equity curve from `results/p1a_A4.json`), 2020–2024 overlap. Stacking value claims require correlation < +0.5 (pre-stated threshold for "independent stream" language; higher correlations are reported as overlapping risk, not stacking).
**Multiple comparisons:** 6 variants → ~0.3 expected spurious passers at the 5% level; correlated variants (B1/B5; B2/B6) count as ~one observation each.

## Kill criteria (pre-stated)

- All six variants negative → calendar family closed at these cadences/exits; no parameter escalation.
- Ledger DOA is already cleared for B1–B4 classes; B5/B6 have no direct ledger row (nearest class = ATM calendar, same $17.60/RT friction) — if either prices at median debit where friction > 25% of debit in the realized sample, grade it "friction-marginal" in the report regardless of P&L.

## Procedure

1. This prereg commits first. 2. Runner `experiments/wave2/run_p1b.py` (new; consumes `backtest/multileg.py`; calls the holdout seal guard before touching data) runs B1–B6 marketable-only. 3. Results JSONs → `experiments/wave2/results/` (gitignored). 4. Scored report commits as `reports/profitability_program/EXP-P1B.md` with a machine-readable JSON block (per-variant trades, total_return, cagr, win_rate, sharpe, max_dd, worst_year, expectancy_per_trade, naive_fallback_share, stale_day_share, max_trade_loss_vs_modeled, corr_vs_A4 for passers). 5. No holdout run under any outcome.
