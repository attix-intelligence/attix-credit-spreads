# EXP-P1A-CAPACITY — Sizing/capacity study on A4: the honest ceiling

**Date:** 2026-07-12 · **Author:** cc1 · **Prereg:** `EXP-P1A-CAPACITY_PREREG.md` @ `b2b77df` (committed before any run; criteria and flag rules unchanged)
**Base:** A4 exactly as passed (QQQ 12-wide 5 %-OTM put verticals, PT 50/SL 2×, marketable fills) · **Window: 2020-01-02 → 2024-12-31 only** — the holdout stayed sealed (the new `assert_holdout_seal` guard was active in every run).
**Status framing (per prereg): sizing information only. Nothing here upgrades A4's evidence status.**

## The honest ceiling

**Per the pre-registered rule** (highest-CAGR flag-free cell): **weekly cadence, 15 %/trade, 3-position cap → CAGR +5.94 %, MaxDD −8.6 %, worst year −5.4 %, peak book max-loss 29.3 % of capital.** That last number sits 0.7 pp under the 30 % tail-stacking line — technically clean, uncomfortably close. **The recommendation with margin is one step down: weekly, 10 %/trade → CAGR +3.96 %, MaxDD −6.2 %, worst year −4.0 %, peak book 19.8 %.**

In dollars: on $100k, honest single-underlier A4 supports roughly **$4–6k/yr at survivable risk** (non-compounding sizing, matching the A4-as-passed convention — compounding would lift this somewhat but was not tested). More capacity does **not** come from trading more often or allowing more positions — both were tested and refuted below. It comes only from more independent underliers/structures, i.e., from the rest of the program.

## The three structural findings (worth more than the ceiling number)

1. **Cadence is a pure risk-adder: 2×/week doubles tail exposure for zero return.** At every risk level, Mon+Thu entries raised trade count 53 → 114–119 and peak book max-loss ≈ 2× (9.3 → 18.5 % at 5 % risk; 29.3 → 58.6 % at 15 %) while CAGR stayed flat or *fell* (e.g. 5.94 → 5.89 % at 15 %). Per-trade expectancy halved ($195 → $96 at 5 %). The Thursday entries harvest the same premium pool while stacking overlapping tails — a controlled, pre-registered re-demonstration of exactly the disease that killed the old fleet, caught at the study stage instead of the account stage.
2. **Position caps above ~4 are dead weight.** Max concurrency actually reached: 2 (weekly), 4 (2×/week) — so the 5/8/12-position cells are byte-identical within each (risk, cadence) pair. Capacity is set by cadence × holding time (PT-50 exits run ~1–2 weeks) × the per-expiration anti-concentration cap, not by the position limit. Raising position caps to "scale up" would change nothing except the illusion of capacity.
3. **Risk-% scales linearly — in both directions.** Return, expectancy, MaxDD, and peak book all scale ≈ proportionally with per-trade risk (5 → 15 %: CAGR 1.94 → 5.94 %, MaxDD −3.1 → −8.6 %). No convexity benefit, no cliff below 15 % — sizing buys exactly what it pays for in tail. The binding choice is therefore a risk-appetite decision, and the tail-stacking flag line (30 % book max-loss) is what caps it.

## Full grid (weekly | 2×-week per cell; flags per prereg)

| Risk % | Positions 3 | 5 | 8 | 12 |
|---|---|---|---|---|
| **5 %** | **1.94** / 1.93 | 1.94 / 1.93 | 1.94 / 1.93 | 1.94 / 1.93 |
| **8 %** | 3.18 / 3.16⚑ | 3.18 / 3.16⚑ | 3.18 / 3.16⚑ | 3.18 / 3.16⚑ |
| **10 %** | 3.96 / 3.92⚑ | 3.96 / 3.92⚑ | 3.96 / 3.92⚑ | 3.96 / 3.92⚑ |
| **15 %** | **5.94** / 5.89⚑ | 5.94 / 5.89⚑ | 5.94 / 5.89⚑ | 5.94 / 5.89⚑ |

*(cell = CAGR %; ⚑ = tail-stacking flag, peak book max-loss > 30 % — all 2×-week cells at ≥ 8 % risk: 30.7 / 38.3 / 58.6 %. No cell hit the degradation flag (all MaxDD ≥ −17.8 %, all worst-years ≥ −7.6 %). No fill-starvation flag fired — trade counts stable across risk levels. Weekly columns identical across position caps because concurrency peaks at 2; 2×-week peaks at 4.)*

Reference detail (weekly, 3-pos): 5 % → exp $195/trade; 8 % → $329; 10 % → $416; 15 % → $649. 53 trades, 90.6 % WR, fallbacks 0 in every weekly cell. Raw per-cell JSON: `experiments/honest-fills-fleet/results/cap_p*_r*_{mon,monthu}.json`.

## Limitations (read before citing the ceiling)

- **The fill model is size-blind.** A 13-lot marketable order (15 % risk) fills in the model exactly like a 2-lot. This study measures *portfolio-geometry* capacity (overlap, tails, cadence), not *market-depth* capacity. Real size behavior at 10–15 lots on QQQ 5 %-OTM puts is precisely what P0B live probes must measure before any live sizing decision cites these numbers.
- Non-compounding flat sizing off $100k throughout (A4-as-passed convention); CAGR at larger accounts scales linearly only while size-blindness holds (see above).
- In-sample 2020–2024; A4's evidence status is unchanged: one in-sample prereg pass, holdout sealed pending Carlos's signature, G2–G4 pipeline still ahead.

## Machine-readable summary

```json
{"experiment": "EXP-P1A-CAPACITY", "prereg_commit": "b2b77df", "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable", "holdout_touched": false,
 "ceiling_per_prereg_rule": {"cell": "weekly_15pct_3pos", "cagr": 5.94, "max_dd": -8.55, "worst_year": -5.36, "peak_book_ml_pct": 29.3, "note": "0.7pp under the tail flag line"},
 "recommended_with_margin": {"cell": "weekly_10pct_3pos", "cagr": 3.96, "max_dd": -6.23, "worst_year": -3.98, "peak_book_ml_pct": 19.8},
 "structural_findings": ["2x_week_cadence_doubles_tail_for_zero_cagr", "position_caps_above_4_never_bind_concurrency_2_weekly_4_twiceweekly", "risk_pct_scales_linearly_no_convexity"],
 "flags": {"tail_stacking_gt30pct": ["monthu_r8 (30.7)", "monthu_r10 (38.3)", "monthu_r15 (58.6)"], "degradation": [], "fill_starvation": []},
 "grid_cagr_weekly": {"r5": 1.94, "r8": 3.18, "r10": 3.96, "r15": 5.94},
 "grid_cagr_2xweek": {"r5": 1.93, "r8": 3.16, "r10": 3.92, "r15": 5.89},
 "dollar_ceiling_100k": "$4-6k/yr at survivable risk, single underlier, non-compounding",
 "limitation": "fill model is size-blind; market-depth capacity requires P0B live probes",
 "evidence_status": "unchanged — sizing information only"}
```
