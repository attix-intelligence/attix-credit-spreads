# EXP-P1E — Skew-Harvest Butterflies (SPY/QQQ) — PRE-REGISTRATION (committed before any run)

**Date:** 2026-07-13 · **Author:** cc2 · **Program:** `research/PROFITABILITY_PROGRAM.md` §EXP-P1E (Carlos Wave-2 GO, 2026-07-13, which explicitly directed the ledger-mandated geometry rework)
**Integrity rule:** committed BEFORE the first variant result; post-hoc changes void the experiment.
**Harness:** `backtest/multileg.py` (shared, `f411fa9`); holdout seal active in the runner.
**Friction ledger citation:** `research/FRICTION_LEDGER.md` — BWB "as speced" prices at a net debit everywhere; prereg must rework geometry or reclassify as debit-convexity with a $35.20/RT 4-leg friction budget and **no credit framing**.

## Geometry DOA measurement (performed BEFORE this prereg — measurement only)

`experiments/wave2/p1e_geometry_doa.py` (P0A methodology: weekly Fridays 2020–24, parity spot, close marks) tested the ledger reference plus four reworked wider/deeper geometries on SPY and QQQ at 15/30 DTE: **all 20 classes price at a median net DEBIT** (−$21 to −$136; at most 34% of sample weeks ever price at a credit). Conclusion, pre-stated: **credit BWBs do not exist on these chains in this window.** This prereg therefore takes the program doc's named alternative: **reclassify as a debit-convexity structure.** No pass claim below is a "credit" claim; expectancy must clear the debit plus $35.20/RT friction on payoff multiples.

## Governance checklist

1. **New mechanism — structure:** butterflies (1/−2/1 put flies, tail-flat or tail-positive) — the payoff sign in the crash tail differs in kind from every closed/tested family (verticals lose max in the tail; these lose only the debit, or profit). Named in the program doc; Carlos's Wave-2 GO is the written confirmation.
2. **Provenance:** index put-skew overpricing literature (`research/lit_review_2024_2026.md`); the mined window contributes only the rejection fact that short-tail verticals fail. The structure sells the rich body strike (~95% moneyness, the steep part of the skew) and owns the wings.
3. **Windows:** 2020-01-02 → 2024-12-31 in-sample dev; holdout sealed. **Marketable fills only.**

## Structure and lifecycle (all variants)

- **Put butterfly:** LONG 1 put at ~98% of spot (nearest listed), SHORT 2 puts at ~95%, LONG 1 put at the variant's lower wing. Spot = underlying close (Polygon loader). Expiry nearest the variant DTE (window ±40%).
- **Geometries (the variant axis):** `flat` lower wing 92% (equidistant — tail-flat: crash loses only the debit); `crash` lower wing 93.5% (inner broken wing — crash tail PAYS +1.5% width beyond the wing); `cheap` lower wing 90% (ledger reference, tail −2% width — included strictly as geometry attribution/control).
- **Entries:** Mondays; max 3 concurrent; skip if an open position shares the expiry.
- **Exits (fixed):** profit target +100% of debit; stop −50% of debit; close at ≤ 5 DTE.
- **Sizing:** modeled max loss per 1x = debit (`flat`/`crash`) or debit + (width-difference × 100) (`cheap`); contracts = floor($2,500 / modeled), min 1, cap 25.

## The 6 variants (final; single-mechanism)

| # | Variant | Definition |
|---|---|---|
| X1 | SPY-flat-30 | flat geometry, SPY, 30 DTE |
| X2 | SPY-crash-30 | crash geometry, SPY, 30 DTE |
| X3 | SPY-cheap-30 | cheap geometry, SPY, 30 DTE (attribution control) |
| X4 | QQQ-flat-30 | flat, QQQ, 30 DTE |
| X5 | QQQ-crash-30 | crash, QQQ, 30 DTE |
| X6 | SPY-crash-15 | crash, SPY, 15 DTE (DTE attribution) |

## Acceptance criteria (fixed now)

**Pass (per variant):** total return > 0; expectancy > $0 net; MaxDD ≥ −20%; worst year ≥ −15%; ≥ 40 closed trades; fallback ≤ 20%.
**P1E-specific (program doc):** (a) 2020-03 and calendar-2022 sub-window P&L reported separately; **a passer that lost money in BOTH stress windows fails on mechanism** even if the total passes (the structure's entire claim is tail behavior); (b) **fill-rate kill** (adapted to the daily-limit harness): marketable fills < 40% of entry attempts → "untradeable at our venue/model," structure closed regardless of P&L.
**Correlation (Wave-2 rule):** any passer reports monthly (primary) and daily Pearson correlation vs A4-as-passed; "independent stream" requires < +0.5.
**Multiple comparisons:** 6 variants, heavily correlated in pairs → ~2–3 effective observations; ~0.3 spurious passers expected.

## Kill criteria (pre-stated)

- All six negative → butterfly family closed; no geometry search beyond the three pre-registered.
- Median realized debit friction share > 35% (friction ÷ debit, realized trades) → "friction-dead as traded."

## Procedure

1. This prereg commits (with the DOA script + its JSON summary numbers quoted above). 2. Runner `experiments/wave2/run_p1e.py` runs X1–X6 marketable-only, holdout guard active. 3. JSONs → `experiments/wave2/results/` (gitignored). 4. Report → `reports/profitability_program/EXP-P1E.md` with machine-readable JSON (per-variant trades, total_return, cagr, win_rate, sharpe, max_dd, worst_year, expectancy_per_trade, fallback share, fill_rate, stress-window P&Ls, friction_share_of_debit, corr_vs_A4 for passers). 5. No holdout touch.
