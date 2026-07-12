# EXP-P1A-CAPACITY PRE-REGISTRATION — sizing/capacity study on A4 (QQQ 5 %-OTM verticals)

**Date:** 2026-07-12 · **Author:** cc1 · **Authorization:** Carlos-approved sizing study (relayed by Maximus, 2026-07-12). Committed BEFORE any run.
**Base variant:** A4 exactly as passed (`EXP-P1A_PREREG.md` @ `c2356b7`, addendum results @ `7cd3f83`): QQQ put vertical, 12-wide, 5 % OTM, DTE 21–45 target 30, PT 50 % / SL 2.0×, manage_dte ≤ 5, VIX ≤ 35, credit floor ≥ $35.20, marketable fills, no direction engine.

## Standing constraints (stated first, non-negotiable)

- **Window: 2020-01-02 → 2024-12-31 ONLY** (in-sample dev). The holdout stays sealed; the new `assert_holdout_seal` guard in the shared harness makes any read past 2024-12-31 a hard failure without Carlos's recorded signature.
- **This study informs sizing decisions only.** It CANNOT upgrade A4's evidence status: A4 remains a single in-sample prereg passer awaiting the Carlos-signed holdout spend, P0B fill calibration, and the G2–G4 pipeline. No cell result creates a new "passer."
- Honest fills throughout: marketable only; **fill starvation is a result, not a nuisance** — if pushing size means entries don't fill, that IS the capacity answer.

## The sweep (32 cells, fixed now)

| Axis | Values | Note |
|---|---|---|
| Max concurrent positions | 3, 5, 8, 12 | position cap |
| Per-trade risk (flat, non-compounding, of $100k) | 5 %, 8 %, 10 %, 15 % | `max_contracts` raised to 30 so risk% is the binding variable (10 would artificially cap 15 %) |
| Entry cadence | weekly (Mon), 2×/week (Mon+Thu) | cadence gate is a harness shim, same pattern as the signed A4 run |

Fixed across all cells: `max_positions_per_expiration = 2` (anti-concentration constant — deliberately retained; concentrating 12 positions on one expiry would manufacture the old fleet's disease, and measuring capacity *with* the guard is the honest question). Everything else identical to A4-as-passed.

**Structural expectation stated in advance** (so the result can't be spun): with ~2–4-week holding periods, weekly cadence supports ≈ 3–4 concurrent positions at steady state and 2×/week ≈ 6–8 — so the 8/12-position cells may bind on *entry cadence and expiry diversity, not the cap*. If so, the honest ceiling is set by cadence × hold-time × fill-rate, and the report must say that rather than extrapolate.

## Metrics per cell (all reported)

Portfolio-level **CAGR** (5-yr, from equity curve), **MaxDD**, **worst calendar year**, trades, win rate, expectancy/trade, unfilled marketable attempts, `naive_fallbacks`, floor rejects, **max concurrent positions actually reached**, and **peak aggregate open max-loss as % of capital** (Σ over open positions of (width − credit) × 100 × contracts ÷ $100k) — the overlapping-tail metric that killed the old fleet (it ran 70–130 %).

## Flag rules (fixed now)

- **Fill-starvation flag:** a cell whose trade count is < 80 % of the same-cadence, same-positions 5 %-risk cell (larger orders failing marketable fills), or whose max-concurrent never reaches its position cap at 2×/week with ≥ 5 slots.
- **Tail-stacking flag:** peak aggregate open max-loss > 30 % of capital.
- **Degradation flag:** worst year < −10 % or MaxDD < −20 % (the A4 gates, applied per cell).

## Honest ceiling definition (fixed now)

The reported ceiling is the **highest-CAGR cell carrying no flags**. Cells above the ceiling are reported with their flags — visible but disqualified. If flag-free cells plateau (more size/cadence adds no CAGR), the plateau is the capacity answer; no extrapolation beyond tested cells.

## Runner & runtime

`experiments/honest-fills-fleet/capacity.py` (parametrized wrapper over the A4 configuration; cadence shim = weekday-set gate; guard `assert_holdout_seal` enforced). 32 runs × ~2–5 min, 6-way parallel ≈ 30–45 min. Results: `results/cap_p{P}_r{R}_{cad}.json`; deliverable `reports/profitability_program/EXP-P1A-CAPACITY.md`.
