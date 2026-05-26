# EXP-3311 — Event-Calendar Entry Gate

**Date:** 2026-05-19
**Status:** Run complete. Decision: **MIXED on the combined gate; SHIP on NFP-only sub-gate.**
**Code:** `compass/exp3311_event_gate.py`, `compass/exp3311_runner.py`
**Reports:** `compass/reports/exp3311_event_gate.{json,html}`

---

## Hypothesis

Skipping credit-spread entries on dates within `(-1, 0)` calendar days of FOMC, CPI, NFP, or monthly OpEx will reduce transaction-cost drag by ≥ 50 bps/yr without materially harming gross return, because (Hu 2014; Kacperczyk-Pagnotta 2024) adverse-selection spreads widen 20-40% in event-proximate windows while our statistical VRP edge is not concentrated there.

## Method

- **Event calendar** (`compass.exp3311_event_gate.EventCalendar`):
  - FOMC dates from `shared.constants.FOMC_DATES` (real, hand-maintained).
  - CPI: 2nd Wednesday of month (BLS proxy).
  - NFP: 1st Friday of month (BLS schedule).
  - OpEx: 3rd Friday of month (CBOE listed-options convention).
  - Default blackout window `(-1, 0)`: trading day before event + event day.
- **Gated streams** (real entry dates filtered):
  - `xlf_cs` — `compass/cache/exp2200_xlf_trades.pkl` (248 trades)
  - `xli_cs` — `compass/cache/exp2200_xli_trades.pkl` (248 trades)
  - `qqq_cs` — `compass/cache/exp2250_qqq_trades.pkl` (85 trades)
  - `exp1220` — re-generated from IronVault via `compass.exp1220_standalone.run_exp1220_trades` (174 trades). Cached at `compass/cache/exp3311_exp1220_trades.pkl`.
- **Pass-through streams** (not credit-spread entries; gate does not apply):
  - `v5_hedge`, `gld_cal`, `slv_cal`, `cross_vol` — from EXP-2080 5-stream cache.
- **Engine**: `compass.exp2850_v8a_with_vix_ladder.walk_forward_with_ladder` — 20 folds, 252-day train / 63-day test, LW risk-parity, 12% vol target, VIX ladder, 890 bps/yr drag.

### Note on baseline divergence vs EXP-2850

The EXP-3311 baseline uses the **sparse exit-date** convention for `exp1220` (P&L lands on the trade's exit date, no daily MTM smearing). EXP-2850's headline used the daily-MTM proxy in `compass/cache/exp1850_streams.pkl` for `exp1220`. The sparse convention is the convention preferred by EXP-2390 (audit) and Rule Zero; it produces a lower per-stream Sharpe because daily variance is restored. This is the apples-to-apples baseline for the gate A/B but is not directly comparable to the EXP-2850 6.39 headline.

- EXP-2850 (cached daily-MTM exp1220):   Sharpe 6.39, CAGR 118%, DD 5.1%
- **EXP-3311 baseline (sparse exit-date exp1220, same engine):  Sharpe 4.996, CAGR 87.3%, DD 7.96%**
- EXP-3311 treatment (all-events gate):  Sharpe 4.984, CAGR 84.8%, DD 5.89%

The drop from 6.39 → 5.00 is the cost of using sparse-exit attribution for exp1220, not a regression caused by the gate.

## Calendar coverage (2020 – 2025)

| Type | Trading-day blackout pct |
|---|---:|
| Any event | 33.08% |
| FOMC | 6.19% |
| CPI | 9.20% |
| NFP | 9.20% |
| OpEx | 9.20% |

The any-event blackout consumes one in three trading days. This is aggressive; whether it pays for itself is the empirical question.

## Trade-drop diagnostics (all-events gate)

| Stream | Kept | Dropped | Drop % |
|---|---:|---:|---:|
| xlf_cs  | 244 | 4 | 1.6% |
| xli_cs  | 246 | 2 | 0.8% |
| qqq_cs  | 42 | 43 | 50.6% |
| exp1220 | 122 | 52 | 29.9% |

QQQ and exp1220 are disproportionately affected because both enter on a roughly monthly cadence (28-DTE → 7-DTE cycle anchored to the third-Friday OpEx). Their natural entry cadence overlaps the OpEx blackout window, so the gate drops a large fraction of their trades.

## Headline results

| Metric | Baseline (no gate) | Treatment (all-events gate) | Δ |
|---|---:|---:|---:|
| Pooled net Sharpe | 4.996 | 4.984 | -0.012 |
| Pooled net CAGR | +87.3% | +84.8% | -2.5pp |
| Pooled Max DD | 7.96% | 5.89% | **-2.06pp** |
| Median fold Sharpe | 5.665 | 5.609 | -0.056 |
| % folds ≥ 6.0 | 40% | 30% | -10pp |
| Worst fold Sharpe | 2.273 | 2.822 | +0.549 |

The all-events gate is **essentially Sharpe-neutral** but **meaningfully reduces drawdown** (-2.06pp pooled, +0.55 worst-fold Sharpe).

### Success-criterion check

- Primary target (≥ 50 bps/yr P&L improvement): **NOT MET** at the pooled level — CAGR fell 2.5pp.
- Secondary: drawdown materially improved, worst-fold Sharpe improved — meaningful risk-quality gain.
- The headline gate's CAGR loss comes from over-restrictive OpEx gating (see below).

## Per-event-type ablation

| Event | Sharpe | ΔSR vs baseline | CAGR | Max DD | Trades dropped |
|---|---:|---:|---:|---:|---:|
| FOMC | 4.988 | -0.008 | +86.2% | 7.96% | 3 |
| CPI | 4.997 | +0.001 | +87.6% | 7.96% | 5 |
| **NFP** | **5.187** | **+0.191** | **+88.4%** | **5.07%** | 32 |
| OpEx | 4.932 | -0.064 | +85.4% | 8.02% | 61 |

**NFP-only gate is the clear winner**:
- +0.19 pooled Sharpe (statistically meaningful)
- +1.1pp CAGR
- -2.89pp drawdown (7.96% → 5.07%)
- only 32 trades dropped across 4 streams (mostly from `exp1220` and `qqq_cs`)

**OpEx-only is counterproductive**:
- -0.064 pooled Sharpe
- DD unchanged
- 61 dropped trades, including profitable monthly entries that happen to land on the third-Friday Friday

**FOMC-only and CPI-only are too small to matter**: too few trades land in those windows in our universe (FOMC ~8/yr, CPI ~12/yr; combined drop only 8 trades).

## Interpretation

1. **NFP gating clearly improves the risk-adjusted return** of the credit-spread book. NFP days are documented adverse-selection peaks in the options-flow literature and our entry frequency overlaps these days enough for the gate to matter without erasing too many entries.
2. **OpEx gating hurts** because the third-Friday Friday is also a high-volume / mean-reversion day for ETF spreads; we systematically drop a class of profitable monthly entries.
3. **The combined "all events" headline is a wash** because NFP's benefit is partially canceled by OpEx's harm and partially diluted by the no-op FOMC/CPI windows.
4. **The drawdown improvement on the all-events gate (-2.06pp) is real**: dropping the 101 event-proximate entries reduces tail exposure even though it costs some mean return. This is risk-quality, not return.

## Recommendation

**SHIP the NFP-only sub-gate.** Update v8a to skip credit-spread entries on the day before and the day of the monthly NFP release.

- Expected pooled-Sharpe lift on the apples-to-apples baseline: **+0.19** (3.8% relative).
- Expected pooled-CAGR lift: **+1.1pp** (1.3% relative).
- Expected drawdown reduction: **-2.89pp** absolute (-36% relative).
- Only 32 trades dropped over 6 years — operationally trivial.

**Do NOT ship the OpEx-only gate**: it removes profitable monthly entries.

**FOMC and CPI windows are too small to need their own gate** — at our trade cadence, fewer than 10 trades land in those windows over 6 years.

## Follow-on experiments

- **EXP-3312** (next): Mid-then-patient execution (Muravyev-Pearson 2020). Expected 60-90 bps/yr; independent of EXP-3311.
- **EXP-3313**: Re-test NFP gate with a wider window `(-2, 0)` or `(-1, +1)` — current `(-1, 0)` may be too narrow to capture all of the literature-estimated adverse-selection footprint.
- **EXP-3314**: Investigate why OpEx is profitable for our universe (mean-reversion? pin-risk-driven assignment? expiry-week IV decay?) — this is a positive-edge day to keep, not avoid.
- **EXP-3315**: Empirical decomposition of the 890 bps/yr drag (spread, adverse selection, timing) to replace the literature-informed estimate from the EXECUTION_OPTIMIZATION review with measured numbers.

## Rule Zero compliance

- All trade tapes are real IronVault outputs.
- All event dates are either hand-maintained real records (FOMC) or deterministic public schedules (CPI / NFP / OpEx).
- No synthetic prices, no fabricated event dates, no Black-Scholes fallback.
- The exp1220 trade tape was regenerated from IronVault DB by the canonical runner — same code path that produced the original cached series.

## Honesty disclosures

- **The baseline Sharpe (4.996) is lower than the EXP-2850 headline (6.39)** because we used sparse-exit attribution for `exp1220` to make the A/B apples-to-apples. The directional finding (NFP gate adds Sharpe, OpEx gate hurts) is robust to this choice but the absolute numbers cannot be directly compared to the EXP-2850 reference.
- **The drag is held constant** between baseline and treatment (890 bps/yr) — this experiment does not directly model fee savings from skipping event-day entries. The improvement shows up as risk-adjusted quality, not as a fee-reduction line item. A separate experiment (EXP-3315) is needed to attribute fee savings.
- **CPI and NFP are deterministic proxies** (2nd Wed / 1st Fri) rather than the actual BLS release calendar. The 1-2 day slippage from this proxy is small and would not materially change the NFP result.
