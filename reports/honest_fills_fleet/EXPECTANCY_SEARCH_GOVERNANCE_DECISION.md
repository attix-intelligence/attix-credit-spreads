# Expectancy Search — Governance Decision: STAND DOWN (option b)

**Date:** 2026-07-10 · **Author:** cc1 · **Trigger:** governance check from Maximus against the `e02b90a` stop rule
**Binding on:** any future expectancy search touching this strategy family, this data, or the 2025+ holdout.
**Sign-off:** APPROVED by Maximus, 2026-07-10 — stand-down confirmed; the binding checklist below is program policy.
**No backtest was run in reaching or documenting this decision.**

## The decision

**Option (b): stand down.** A "weekly cadence + credit floor" pre-registration is NOT written and will not be. The next search, if any, must be built from genuinely new mechanisms — different underliers, different option structures, or different signal sources — under a fresh pre-registration. The 2020–2024 window is permanently classified as **mined / in-sample** for the SPY put-credit-spread family; the 2025–2026Q1 holdout remains unmined and may be spent **once**, only on hypotheses that do not descend from the mined window's leaderboard.

## Why option (a) is not defensible

I attempted the strongest honest case for (a) and it fails on its own terms:

1. **V1 and V6 are not "new mechanisms."** They are two of the twelve variants of the search that just failed, identified as promising *because* of their rank on the mined window. The stop rule ("fresh pre-registration with new mechanisms, not parameter jitter on these") names this case almost literally.
2. **The combination hypothesis was formed by looking at results.** "V1+V6" exists as an idea only because the leaderboard was seen. That is the definition of selection. The pre-registration's own multiple-comparisons section predicted ~0.6 spurious near-passers across 12 variants; V1's +$0.42/trade on 127 trades is indistinguishable from exactly that.
3. **Holdout-only validation would compound the error, not cure it.** The holdout is ~5 quarters of one regime; at weekly cadence it holds roughly 25–35 trades — no power to distinguish a real edge from noise. Spending the program's only unmined data on the *weakest admissible hypothesis class* (a selection-derived combo) is the worst possible use of it, and it is single-use: once looked at, it is gone for every better future hypothesis.
4. **Process precedent matters more than this variant.** The honest-fills program's entire value is that its gates fire even when inconvenient (EXP-1220's retirement proved that). Granting a leaderboard-derived exception on day one of the stop rule would convert every future "stop" into an opening bid.

## Correction of my own record

My summary accompanying `e02b90a` described "weekly cadence + rich-premium selectivity as the base" of a future pre-registration. That framing was inconsistent with the results file's own warning ("explicitly not a promotion of V1/V6, whose numbers are already selection-tainted") and is **retracted**. The governance check is upheld in full.

## What mined-window information MAY still be used for (one-way door)

Mined results may be used to **reject** designs, never to **select** them:

- Negative findings stand as constraints: delta-targeted strikes at 5-wide widths, 1.0× stops, and all tested protection layers are established loss-makers/insufficient in this family; no future prereg needs to re-test them, and none may cite the mined window as *positive* evidence for anything.
- Friction arithmetic (commissions, slippage per spread, fill rates under marketable limits) consists of measured facts about execution, not fitted strategy parameters, and may inform the *cost model* of any future prereg.
- General design principles may be stated only in causal, strategy-independent form (e.g., "overlapping short-vol positions stack tail exposure") and must find support outside the mined window (literature, other markets, live broker record) before appearing in a prereg's rationale.

## Requirements for any future pre-registration (binding checklist)

1. **New mechanism test:** every variant must differ from the failed search in at least one of — underlier set (not SPY-only), option structure (not vertical put credit spreads), or signal source (external/causal, not derived from 2020–2024 SPY spread results). A reviewer (Maximus or Carlos) confirms this in writing before the prereg is committed.
2. **Provenance statement:** each variant's rationale must cite its origin (literature, live broker evidence, cross-market data) and affirmatively state it was not derived from the mined window's leaderboard.
3. **Prereg committed before any run**, as before; criteria at least as strict as `EXPECTANCY_SEARCH_PREREG.md`.
4. **Holdout budget:** the 2025+ holdout may be consumed once, by that prereg's passers only. If it is spent without a pass, out-of-sample validation for this program requires *forward* data (new paper months), not any historical window.
5. **The 2020–2024 window may appear only as an explicitly-labeled in-sample development set** in any future work, never as validation.

## Status

- No new prereg exists. No backtests were run on any window for V1/V6-derived variants.
- Program state is unchanged from `EXPECTANCY_SEARCH_RESULTS.md`: zero launch candidates; EXP-800 halt-and-drain recommendation standing; config-to-code parity audit standing; "no launch in 2026" acceptable.
