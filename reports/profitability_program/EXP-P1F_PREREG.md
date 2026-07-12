# EXP-P1F — TLT Rate-Vol Premium — PRE-REGISTRATION (committed before any run)

**Date:** 2026-07-12 · **Author:** cc2 · **Program:** `research/PROFITABILITY_PROGRAM.md` §EXP-P1F (Carlos GO 2026-07-12)
**Integrity rule:** this document is committed to git BEFORE the first variant result is computed. Any change to variants or criteria after results exist voids the experiment.
**Friction ledger citation (program rule):** `research/FRICTION_LEDGER.md` (EXP-P0A) — plus the call-side extension below.

## Governance checklist (binding, per `reports/honest_fills_fleet/EXPECTANCY_SEARCH_GOVERNANCE_DECISION.md`)

1. **New-mechanism confirmation (in writing, before this commit):** Maximus, 2026-07-12, relayed with Carlos's GO: *"CONFIRMED — TLT is a genuinely new underlier (294k bars never backtested, distinct macro driver, zero derivation from the mined SPY leaderboard); this note satisfies the governance checklist item 1 for P1F."*
2. **Provenance:** the hypothesis descends from the bond variance-risk-premium literature (Choi–Mueller–Vedolin, *Bond Variance Risk Premiums*; surveyed in `research/lit_review_2024_2026.md`), not from any mined result. TLT has never been backtested in this repo. No variant below is derived from the 2020–2024 SPY leaderboard; mined-window information is used only in its permitted rejection-side/cost-model form (friction arithmetic; "overlapping short-vol positions stack tail exposure" as a causal, strategy-independent principle).
3. **Prereg before run:** no P1F backtest has been executed as of this commit. The only computations performed are DOA friction measurements (explicitly permitted pre-prereg: "friction arithmetic is fact, not fitted parameter").
4. **Holdout:** untouched. **No data past 2024-12-31 is read by any run under this prereg.** TLT marks end 2025-12-19 in cache; the runner caps `end_date=2024-12-31`.
5. **In-sample labeling:** 2020–2024 is an explicitly-labeled in-sample development window. A pass here is a development result, not validation.

## Hypothesis

Defined-risk premium selling on TLT (put and call credit verticals; strangle-of-verticals) has positive expectancy net of measured friction, because Treasury-vol carries a persistent variance risk premium whose macro driver (rate volatility) is distinct from the equity-vol book that failed the honest-fills gate. The 2022 rates bear (TLT −31%) is in-window and serves as the built-in stress test.

## DOA check (performed BEFORE this prereg, as required — measurement only)

The P0A ledger measured TLT **put** verticals only: 6 of 8 classes DOA; survivors `dte30_wide3_2pctOTM` ($69 median, 25.5% min-edge) and `dte15_wide3_2pctOTM` ($63.5, 27.7%). Since this prereg covers **both directions**, the call side was measured with the identical methodology (`experiments/honest-fills-fleet/p1f_doa_check.py`, weekly Friday grid 2020-01-03→2024-12-27, parity-inferred spot, closes; DOA = median premium < 2× friction = $35.20/vertical):

| TLT class | n | median premium | min-edge % | verdict |
|---|---|---|---|---|
| call dte30 wide3 2%OTM | 66 | $49.5 | 35.6% | **clears** (thin ⚠️) |
| call dte15 wide3 2%OTM | 60 | $34.5 | 51.0% | **DOA** (by $0.70) |
| call dte30/15 narrow & 5%OTM (4 classes) | 50–60 | $7–25 | 70–251% | **DOA** |
| put cross-checks (dte30/15 wide3 2%OTM) | 66/60 | $67.5 / $61.5 | 26.1% / 28.6% | clears — matches ledger ✓ |

**Scoping consequence (pre-stated):** variants are restricted to the DOA-clearing classes — 2%-OTM wide verticals: put side at 30 and 15 DTE, call side at **30 DTE only**. A 15-DTE call variant is not written. Strangle-of-verticals uses 30-DTE both sides (combined median ≈ $117 vs 4-leg 2× threshold $70.4 — clears at ~30% min-edge).

**Ledger caveat acknowledged:** the P0A ledger recommends TLT preregs "only if P0B shows real TLT spreads no worse than modeled." P0B probes have not run (4-week calendar). Carlos's GO explicitly sequences P1F now; therefore **any pass under this prereg is graded PROVISIONAL — fill-uncertain pending P0B TLT spread calibration** (non-SPY friction numbers are lower bounds per the ledger). This grading is fixed now and cannot be relaxed by good-looking results.

## The 6 variants (final — no additions after this commit)

Shared base (all variants): TLT, defined-risk verticals, strikes 2% OTM, **fixed $4 spread width** (≈3% of the 2020–24 midpoint spot ~$120; the engine takes fixed dollar widths — documented approximation to the ledger's %-of-spot class), weekly **Monday-only entries** (overlap control — causal: stacked short-vol overlap is the fleet's documented failure mode), **flat 5% risk per trade non-compounding** off $100k, max 15 contracts / 5 concurrent positions / 2 per expiration, **PT 50% of credit, SL 2.0× credit, no early-DTE exit** (engine-native, matches champion-family `manage_dte: 0`), `min_credit_pct` 12 (per-trade DOA floor: ≥ $0.36 ≥ 2× friction $0.352 at $4 width), `momentum_filter_pct` none, `vix_max_entry` disabled (VIX is an equity-vol measure; wrong driver for TLT — no rate-vol series exists in cache), fill_model **marketable only**.

| # | Variant | Definition | Mechanism / provenance (single each) |
|---|---|---|---|
| V1 | put-30 | Put credit vertical, DTE target 30 (21–45), always-on (trend gate bypassed) | Pure bond-VRP harvest, downside tail — the literature's central claim |
| V2 | call-30 | Call credit vertical, DTE 30, always-on | Same VRP, upside tail — 2022 (rates up, TLT down) should pay here; attribution for which tail carries the premium |
| V3 | strangle-30 | V1 + V2 sides entered together (two verticals, both directions, same day) | Direction-neutral VRP harvest; the program sketch's "strangle-of-verticals" |
| V4 | put-15 | Put credit vertical, DTE target 15 (12–25), always-on | Faster theta cycle on the other DOA-clearing put class |
| V5 | trend-30 | DTE 30, both sides, **engine-native trend conditioning** (200d MA, prior-day close: puts only above, calls only below) | Don't sell into the falling side — causal, literature-generic (not mined); the only conditioned variant |
| V6 | put-30-rich | V1 + `min_credit_pct` 22 (credit ≥ ~$0.88 at $4 width ≈ the P0A median premium share) | Rich-premium floor from the measured P0A distribution — friction share halves when premium is rich |

Always-on variants (V1–V4, V6) bypass the engine's non-combo MA trend gate via a harness shim that neutralizes `_compute_trend_ma` per finder call (put finder → −inf, call finder → +inf); V5 uses the engine gate natively at MA 200 (the most standard, zero-degrees-of-freedom trend length). The shim pattern is the same precedented mechanism as the fleet harness's `monday_only` gate. Combo-regime mode is deliberately NOT used: the ComboRegimeDetector consumes equity VIX/VIX3M, the wrong macro driver for TLT.

## Acceptance criteria (fixed now — program-wide gates PLUS the 2022 clause)

**Pass requires ALL of (per variant, 2020-01-02 → 2024-12-31, marketable fills):**
1. Total return > 0%
2. Expectancy per trade > $0 net of modeled friction (P0A: $17.60/RT per vertical; V3 pays 2× as two verticals)
3. Max drawdown ≥ −20%
4. **Worst calendar year ≥ −15%, explicitly including 2022** (the rates bear, TLT −31% — the honest stress test; program doc P1F clause)
5. ≥ 40 closed trades
6. `fill_model_naive_fallbacks` ≤ 20% of entries — else the run is graded **fill-uncertain** and cannot pass, only inform (program gate; TLT has daily bars only, so marketable fills use static day-limit semantics — the fallback share must be reported prominently)
7. Any pass is additionally graded **PROVISIONAL pending P0B** (pre-stated above)

**Kill criteria (pre-stated):** both directions negative over the window → family closed, no parameter escalation. Fallback share > 20% on all variants → "data insufficient for honest fills on TLT," not a strategy verdict.

## Multiple-comparisons honesty

Six variants, one-sided selection at ~5% per-variant false-positive rate → ~0.3 expected spurious passers. Any single passer is therefore weak evidence by construction; it earns only the next program step (P0B calibration + forward paper months), never capital. If several correlated variants pass together (e.g., V1/V4/V6 sharing the put side), they count as ~one observation, not three.

## Procedure

1. This prereg commits first (with the DOA script). 2. Runner `experiments/honest-fills-fleet/run_p1f.py` (new; engine path identical to the fleet harness) executes V1–V6, **marketable only**, `end_date=2024-12-31` hard cap. 3. Result JSONs land in `experiments/honest-fills-fleet/results/p1f_*.json` (gitignored per repo convention). 4. The scored report commits as `reports/profitability_program/EXP-P1F.md` with a machine-readable JSON block including per-variant `{trades, total_return, cagr, win_rate, sharpe, max_dd, pct_unfillable, naive_fallback_share, worst_year, expectancy_per_trade}`. 5. No holdout run under any outcome; holdout spend is Carlos's separate, single-use decision at program level.
