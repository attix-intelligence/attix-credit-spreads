# Profitability Experiment Slate — Draft for Carlos Review

**Date:** 2026-07-12 · **Author:** Maximus · **Status:** DRAFT — not a pre-registration. Each approved item becomes its own prereg per the binding checklist in `EXPECTANCY_SEARCH_GOVERNANCE_DECISION.md`.

## Where we stand (facts, not opinion)

- 9/9 deployed strategies negative under honest fills; 5 ruin the account. Fill model was never the problem — the entries are.
- The SPY put-credit-vertical family is **closed**: 2020–2024 is mined, 12 pre-registered mechanisms failed, stop rule fired, stand-down signed.
- The 2025–2026Q1 holdout is unmined and single-use.
- Governance requires any new search to differ in **underlier, structure, or signal source**, with written provenance not derived from the mined leaderboard.

## What the mined window is allowed to teach us (reject-only + friction facts)

- Honest per-entry unfillable rate is ~23–60 %; per-spread friction (commissions + spread cost) is a measured fact usable in any future cost model.
- Overlapping short-vol entries stack tail exposure (causal statement, supported by live broker record + literature).
- Delta-targeted strikes at 5-wide widths, 1.0× stops, and YAML-only "protections" are established loss-makers — no future prereg re-tests them.

## The slate

### Phase 0 — Measurement (week 1, no strategy risk, no holdout spend)

**EXP-P0A · Friction Budget Ledger.**
For each candidate structure × underlier (verticals, iron condors, calendars, diagonals × SPY/QQQ/XLF/XLI/GLD/SLV), compute the *minimum gross edge per trade* required to clear commissions + honest spread cost at realistic fill rates. Output: one table that every future prereg must cite. Kills unviable ideas before they cost a backtest.
*Provenance:* measured execution facts (explicitly permitted). *Data:* options_cache.db. *Cost:* $0.

**EXP-P0B · Tradier Fill-Quality Probes (live, forward data).**
1-lot probe orders on a fixed schedule (not strategy signals) to measure real fill rates, time-to-fill, and effective slippage vs the marketable model, at mid / mid−1¢ / marketable. Calibrates the fill engine with live ground truth; also tests the inside-NBBO thesis from the MM brief.
*Provenance:* forward live data. *Cost:* commissions on ~40–60 probe lots (~low hundreds of $). *Risk:* 1-lot max, closed same day.

### Phase 1 — New-mechanism searches (each gets its own prereg; run in parallel on cc1–cc5)

**EXP-P1A · Defined-risk premium on sector ETFs (new underlier + structure).**
Iron condors / put credit on XLF and XLI — the streams that carried 81 % of v8a's backtest Sharpe (EXP-3151) and the plausible dealer-flow-different venue per Dew-Becker. Test at weekly-or-slower cadence with rich-premium floors — justified causally (overlap-stacking + friction ledger), not by V1/V6 rank.
*Provenance:* v8a research pre-dating the mined search; Dew-Becker mechanism. *Data:* have it. *Cost:* $0.

**EXP-P1B · Calendar/diagonal spreads on GLD/SLV (new structure).**
Term-structure VRP instead of skew VRP. Long-dated leg caps tail risk structurally — addresses the "2022 problem" by construction rather than by gate.
*Provenance:* v8a calendar streams + term-structure literature. *Data:* have it. *Cost:* $0.

**EXP-P1C · Long-vol / convexity book (new structure — the other side).**
If short premium can't clear frictions at survivable size, test the opposite: cheap convexity (put backspreads, VIX call ladders) bought only when term structure inverts or vol-of-vol is depressed. A small standalone book, and a candidate structural hedge for any future short-premium book.
*Provenance:* VIX-ladder research (v8a stream 8) + literature. *Data:* have it. *Cost:* $0.

**EXP-P1D · Execution alpha — inside-NBBO liquidity provision (mechanism-agnostic).**
From the June MM brief: post inside the NBBO instead of paying spread. Backtest the uplift on P1A/P1B candidates; validate assumptions with P0B live probes. This is the one lever that improves *every* strategy's expectancy simultaneously.
*Provenance:* MM_EQUITY/OPTIONS_FEASIBILITY.md. *Data:* crude on hourly CBOE quotes; calibrated by P0B. *Cost:* $0.

### Phase 2 — New signal sources (need small data spend)

**EXP-P2A · Dealer GEX regime signal (new signal source).**
Real OI data (CBOE DataShop, ~$50/yr) to build the dealer-gamma signal the May 16 sprint couldn't test (IronVault OI is NULL; volume proxy rejected H2 inconclusively). Gate premium-selling to net-short-dealer-gamma regimes — the causal condition under which VRP exists per Dew-Becker.
*Provenance:* DEALER_GEX_LITERATURE.md (15+ papers). *Cost:* ~$50/yr. **Needs Carlos approval.**

**EXP-P2B · Event-premium harvesting (new signal source).**
FOMC/CPI/NFP pre-event premium richness on index options — sell (defined-risk) only into measured event-vol overpricing; flat otherwise. Trades ~30×/yr, minimal overlap by construction.
*Provenance:* event-vol literature + FOMC calendar data already in repo. *Data:* have it. *Cost:* $0.

## Gates (every experiment, no exceptions)

- Prereg committed before any run; criteria ≥ as strict as `EXPECTANCY_SEARCH_PREREG.md` (total > 0, expectancy > $0, MaxDD ≥ −20 %, worst year ≥ −15 %, ≥ 40 trades).
- Marketable fills only. Friction ledger (P0A) cited in every prereg.
- Config-to-code parity audit before any twin claim.
- 2020–2024 = in-sample dev only. Holdout spent once, on the single best pre-registered passer — Carlos signs the spend.
- New-mechanism confirmation in writing (Maximus or Carlos) before prereg commit.

## Sequencing & asks

1. **This week:** P0A + P0B (measurement, near-zero cost) — no approval needed beyond probe commissions. 
2. **Carlos decisions:** (a) approve slate, (b) approve ~$50 CBOE DataShop for P2A, (c) EXP-800 live authority pull + credential rotation (still standing since Jul 10).
3. On approval, each Phase 1 item becomes a formal prereg and runs on a dedicated cc session.
