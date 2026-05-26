# Robustness Validation — PilotAI v8a

**Experiment:** EXP-3260
**Compiled:** 2026-05-15
**Status:** LP-ready
**Sources:** EXP-3200 (Monte Carlo, 10K paths × 5 scenarios) · EXP-3230 (rolling walk-forward, 60 folds, 1-month step)
**Data window:** 2020-01-01 → 2025-12-31 (1,566 trading days)
**Strategy under test:** v8a_add_qqq (8 streams, risk-parity, target vol 0.18, net drag 890.3 bps)

---

## Executive summary

The v8a strategy has been validated along **two independent axes of robustness** — historical out-of-sample stability and forward-looking distributional stress — and we report the results honestly, including where the production claims do not hold.

| Result | Value | Source |
| --- | --- | --- |
| Rolling walk-forward folds with **positive net Sharpe** | **60/60 (100%)** | EXP-3230 |
| Rolling walk-forward folds with net Sharpe ≥ 4.0 | 58/60 (96.7%) | EXP-3230 |
| Rolling walk-forward folds with test max DD < 12% | **60/60 (100%)** | EXP-3230 |
| Pooled net Sharpe across 60 folds | 6.64 | EXP-3230 |
| Median fold net Sharpe | 6.80 | EXP-3230 |
| Worst-fold net Sharpe (60 folds) | **3.88** (2025-02-25 → 2025-05-22) | EXP-3230 |
| Worst-fold test max DD (60 folds) | **11.98%** (2022-01-05 → 2022-04-01) | EXP-3230 |
| MC P(DD > 12%) in baseline regime, no circuit | 2.83% | EXP-3200 |
| MC P(DD > 12%) in vol-explosion regime, no circuit | **100.00%** | EXP-3200 |
| MC P(DD > 12%) in grinding-DD regime, no circuit | 97.69% | EXP-3200 |
| Production 12% DD claim holds across all stress regimes | **No** | EXP-3200 verdict |

**Headline takeaway.** The strategy is highly stable under historical out-of-sample resampling — no losing fold, no fold breaching the production DD claim, no fold below Sharpe 3.88 across 60 month-stepped tests covering 5 calendar years. However, **two distributional stress regimes — grinding-drift and vol-explosion — breach the 12% DD claim on the great majority of simulated paths.** These are tail regimes by construction, and our 3% trailing-DD circuit breaker materially reduces but does not eliminate the breach probability. LPs should understand both halves of this picture.

---

## 1 · Methodology

### 1.1 EXP-3230 — Rolling walk-forward (historical OOS)

Goal: measure out-of-sample stability of the v8a strategy under a much finer resampling than the standard quarterly walk-forward (EXP-2280, EXP-2730).

| Parameter | Value |
| --- | --- |
| Strategy | v8a_add_qqq (8 streams: exp1220, v5_hedge, gld_cal, slv_cal, cross_vol, xlf_cs, xli_cs, qqq_cs) |
| Train window | 252 trading days (rolling) |
| Test window | 63 trading days (≈3 months) |
| **Step size** | **21 trading days (≈1 month)** |
| Covariance estimator | Ledoit-Wolf shrinkage |
| Weighting | Risk-parity, scaled to target vol 0.18, cap 20× |
| Net drag | 890.3 bps/yr (EXP-2570 Alpaca commfree + ExecOpt) |
| Number of folds | **60** |
| Flag thresholds | weight-drift L1 > 0.20 · corr-Frobenius break > 1.0 · train-test Sharpe gap > 2.0 |

Each fold fits Ledoit-Wolf covariance and risk-parity weights on the train slice, then evaluates the unchanged weights on the next-3-month test slice. The 1-month step produces overlapping test windows but disjoint *step-points*, giving 60 independent re-fittings. All metrics reported below are net of drag.

### 1.2 EXP-3200 — Monte Carlo stress (forward-looking)

Goal: stress-test the v8a strategy under distributional regimes that are *worse* than anything observed in the 2020-2025 calibration window.

| Parameter | Value |
| --- | --- |
| Calibration window | 2020-01-01 → 2024-12-31 (real v8a cube) |
| Number of paths per scenario | **10,000** |
| Path length | 252 trading days (1 trading year) |
| Generator | Multivariate normal calibrated to per-stream μ, σ, and SPY-β |
| Production DD claim | 12.0% |
| Trailing-DD circuit breaker | 3% over a 20-day rolling window, "flatten" action |
| Net drag | 890.3 bps/yr |
| Scenarios | 5 (see below) |

**Distributional caveat.** EXP-3200 uses an MVN distributional assumption — no Student-t, no jump-diffusion. Tail co-movement *during* a shock (correlation explosions in the same path) is only partially captured (through `credit_freeze`'s mix=0.5 toward all-ones correlation). True tails may be thicker than what is reported here.

### 1.3 Five stress scenarios

| Scenario | Construction | Real-world analogue |
| --- | --- | --- |
| `baseline` | Calibrated MVN, no shock | Control |
| `flash_crash` | Single −10% SPY day inserted at random *t*, β-propagated | 2010 flash crash / 2020-03-12 |
| `credit_freeze` | Correlation matrix shrunk toward all-ones (mix = 0.5) | 2008 GFC / 2020-03 |
| `grinding_dd` | μ shifted by −20%/yr; σ unchanged | 2022 secular bear |
| `vol_explosion` | Σ × 16 (variance × 16, i.e., σ × 4 — VIX 20 → 80) | March 2020 / Volmageddon |

---

## 2 · Results — EXP-3230 rolling walk-forward

### 2.1 Pooled performance

| Metric | Gross | **Net** |
| --- | ---: | ---: |
| Days (pooled across folds) | 1,302 | 1,302 |
| CAGR | 288.24% | **255.33%** |
| Sharpe | 7.10 | **6.64** |
| Max drawdown | 9.58% | **9.86%** |
| Annual volatility | 19.42% | 19.42% |
| Calmar | 30.09 | **25.91** |

Pooled net Sharpe of **6.64** is consistent with EXP-2730's quarterly walk-forward (rolling 6.16, expanding 6.78) — the finer 1-month resampling neither reveals overfitting nor concentrates risk.

### 2.2 Fold-level distribution (60 folds, NET)

| Metric | Min | p10 | Median | Mean | p90 | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Test Sharpe (net) | 3.88 | 4.63 | **6.80** | 6.99 | 9.75 | 10.67 |
| Test Sharpe (gross) | 4.16 | 5.08 | 7.27 | 7.50 | 10.38 | 11.31 |
| Train Sharpe (gross) | 3.30 | 6.20 | 7.21 | 7.23 | 8.47 | 9.07 |
| Test max DD (%) | 0.999 | 1.12 | **2.58** | 3.43 | 7.14 | **11.78** |
| Test CAGR (%) | 81.59 | 150.75 | 287.18 | 314.75 | 452.27 | 1,277.81 |
| Train-test Sharpe gap | −4.62 | −3.04 | **−0.74** | −0.27 | 3.30 | 4.08 |

**Train-test gap.** The median gap is **negative (−0.74)** — i.e., the test slice tends to *outperform* the train slice. This is the opposite of what overfitting would produce. The mean is also negative (−0.27).

### 2.3 Fold-count thresholds

| Threshold (NET) | Folds passing | % |
| --- | ---: | ---: |
| Test Sharpe ≥ 3.0 | 60 / 60 | **100.0%** |
| Test Sharpe ≥ 4.0 | 58 / 60 | 96.7% |
| Test Sharpe ≥ 5.0 | 49 / 60 | 81.7% |
| Test Sharpe ≥ 6.0 | 40 / 60 | 66.7% |
| Test Sharpe ≥ 7.0 | 29 / 60 | 48.3% |
| Test max DD < 12.0% | 60 / 60 | **100.0%** |
| Test max DD < 8.0% | 54 / 60 | 90.0% |
| Test max DD < 5.0% | 48 / 60 | 80.0% |

### 2.4 Stability diagnostics

| Diagnostic | Median | p90 | Max | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Weight drift L1 (vs prior fold) | 0.04 | 0.11 | 1.81 | Weights are very stable month-on-month. The single 1.81 outlier sits inside one of the flagged windows. |
| Correlation Frobenius break (vs prior fold) | 0.20 | 0.39 | 0.48 | All below the 1.0 flag threshold — no correlation regime collapse OOS. |
| Average pairwise corr (train) | 0.018 | 0.031 | 0.040 | Streams are near-orthogonal across all training windows — the diversification thesis holds throughout 2020-2025. |

### 2.5 Year-by-year performance

Net Sharpe of the 3-month test slice, grouped by the calendar year that contains the test-start date:

| Test year | n folds | Min | Median | Max |
| --- | ---: | ---: | ---: | ---: |
| 2020 | 1 | 8.22 | 8.22 | 8.22 |
| 2021 | 12 | 6.31 | 7.64 | 10.53 |
| **2022** (Fed tightening, bear) | 13 | **4.46** | **5.79** | 8.58 |
| 2023 | 12 | 4.24 | 5.84 | 8.15 |
| 2024 | 13 | 4.22 | 7.89 | 10.43 |
| **2025** (most recent) | 9 | **3.88** | 9.68 | 10.67 |

The two weakest years are **2022** (median 5.79 — driven by the rate-shock bear) and **2025 lower tail** (worst fold 3.88, also the global worst). Both still clear the Sharpe-3.0 floor and the 12% DD ceiling. Median Sharpe is highest in **2025 (9.68)** despite that being the year with our single weakest fold — i.e., dispersion is mostly upside.

### 2.6 Worst-case folds

| Type | Fold | Test window | Net Sharpe | Test max DD | Notes |
| --- | ---: | --- | ---: | ---: | --- |
| **Lowest net Sharpe** | 52 | 2025-02-25 → 2025-05-22 | **3.88** | 10.37% | Tariff-shock chop window; still positive Sharpe and DD inside claim. |
| **Highest test DD** | 13 | 2022-01-05 → 2022-04-01 | 5.18 | **11.98%** | Q1-2022 rate shock; **single fold that approaches the 12% claim but does not breach it**. |
| **Best net Sharpe** | 58 | 2025-08-20 → 2025-11-14 | 10.67 | 1.10% | Post-2025-summer recovery; cited only for distributional context. |

### 2.7 Flagged folds (diagnostic only)

32 of 60 folds tripped at least one of the three flag thresholds. Concentration of flags:

| Period | Flags | Period | Flags |
| --- | ---: | --- | ---: |
| 2020Q4 | 1 | 2023Q4 | 3 |
| 2021Q1 | 2 | 2024Q1 | 2 |
| 2021Q3 | 2 | 2024Q2 | 1 |
| 2021Q4 | 1 | 2024Q3 | 1 |
| 2022Q1 | **3** | 2024Q4 | **3** |
| 2022Q2 | 2 | 2025Q1 | **3** |
| 2022Q3 | 1 | 2025Q2 | **3** |
| 2023Q1 | 1 | 2025Q3 | **3** |

Flags are diagnostic — they identify folds where weights drifted, correlations re-shaped, or train and test Sharpe diverged sharply — they are **not failure markers**. The 2025 cluster reflects the most recent re-fitting period and is expected; the 2022Q1-Q2 cluster correctly identifies the Fed rate-shock regime change. **None of the flags produced a sub-Sharpe-3 fold or a DD breach**.

---

## 3 · Results — EXP-3200 Monte Carlo stress

### 3.1 Net-of-drag max drawdown by scenario (10,000 paths, 252 days, no circuit breaker)

| Scenario | Mean DD | p50 | p95 | p99 | Worst | **P(DD > 12%)** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 7.52% | 7.09% | 11.90% | 15.04% | 24.71% | **2.83%** |
| flash_crash | 7.55% | 7.12% | 11.91% | 14.82% | 23.60% | **2.78%** |
| credit_freeze | 8.77% | 8.28% | 13.95% | 17.49% | 27.17% | **7.63%** |
| grinding_dd | **32.68%** | 32.68% | 48.35% | 53.76% | 66.94% | **97.69%** |
| vol_explosion | **47.12%** | 45.58% | 70.69% | 79.38% | **93.80%** | **100.00%** |

### 3.2 Effect of the 3% trailing-DD circuit breaker

| Scenario | P(DD > 12%) no CB | P(DD > 12%) **with CB** | Δ |
| --- | ---: | ---: | ---: |
| baseline | 2.83% | **1.33%** | −1.50 pp |
| flash_crash | 2.78% | **1.39%** | −1.39 pp |
| credit_freeze | 7.63% | **3.78%** | −3.85 pp |
| grinding_dd | 97.69% | **77.06%** | −20.63 pp |
| vol_explosion | 100.00% | **96.13%** | −3.87 pp |

The circuit breaker **roughly halves the breach rate in benign and moderate-stress regimes**. In extreme regimes it materially reduces but cannot eliminate breach, because by the time the 20-day trailing DD signal fires, a vol-explosion path has already accumulated double-digit drawdown.

### 3.3 Net-of-drag Sharpe under stress (10,000 paths, no circuit)

| Scenario | Mean Sharpe | p05 | p50 | p95 | Min |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 4.25 | 2.57 | 4.23 | 5.95 | 0.17 |
| flash_crash | 4.20 | 2.53 | 4.18 | 5.91 | −0.48 |
| credit_freeze | 3.85 | 2.17 | 3.83 | 5.53 | 0.06 |
| grinding_dd | **−1.72** | −3.37 | −1.71 | −0.09 | −6.17 |
| vol_explosion | 1.07 | −0.58 | 1.08 | 2.73 | −3.28 |

`grinding_dd` is the regime where the strategy loses money on average (Sharpe ≈ −1.7) — by construction, we shifted μ by −20%/yr. The strategy survives a vol explosion with a mean Sharpe of ~1 but a wide distribution.

### 3.4 Verdict from EXP-3200

```
production_dd_claim_pct       : 12.0
claim_holds_all_scenarios     : false
worst_scenario                : vol_explosion
max_p99_dd_pct (no CB)        : 78.14   (vol_explosion)
```

---

## 4 · Survival analysis

We define **"survival"** as: ending the 252-day window with cumulative return > −25% (i.e., not lethal to the firm). We compute this from the EXP-3200 simulated path distributions.

### 4.1 Net total-return percentiles by scenario (no circuit breaker)

| Scenario | p01 | p05 | Median | p95 | P(ending < −25%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | +37.5% | +56.4% | +110.7% | +182.6% | 0.0% |
| flash_crash | +38.1% | +55.4% | +108.7% | +181.6% | 0.0% |
| credit_freeze | +32.8% | +51.0% | +108.7% | +190.3% | 0.0% |
| grinding_dd | −51.8% | −46.1% | **−27.6%** | −3.1% | **~67%** |
| vol_explosion | −69.4% | −49.1% | +67.8% | +443.2% | **~22%** |

### 4.2 Survival under different DD-loss thresholds (no CB)

| Loss threshold | baseline | flash_crash | credit_freeze | grinding_dd | vol_explosion |
| --- | ---: | ---: | ---: | ---: | ---: |
| Survive ending > −10% | **100.0%** | ~99% | ~99% | ~22% | ~75% |
| Survive ending > −25% | **100.0%** | **100.0%** | **100.0%** | ~33% | ~78% |
| Survive ending > −50% | **100.0%** | **100.0%** | **100.0%** | ~99% | ~95% |

(Survival rates above −10% and −25% in grinding_dd and vol_explosion are interpolated from the percentile grid in EXP-3200; they are approximate.)

### 4.3 Recovery times (median days to recover the worst trough, no CB)

| Scenario | Median recovery (days) | p95 |
| --- | ---: | ---: |
| baseline | 15 | 252 (no recovery within year) |
| flash_crash | 15 | 252 |
| credit_freeze | 17 | 252 |
| grinding_dd | 252 (no recovery within year) | 252 |
| vol_explosion | 252 | 252 |

In benign and moderate-stress regimes the median path recovers from its worst trough in **~2-3 weeks**. In tail regimes recovery does not happen within the simulated year, by construction.

### 4.4 Combined view — historical OOS vs distributional stress

The 60 historical OOS folds in EXP-3230 produced **zero** sub-Sharpe-3 outcomes, **zero** DD breaches over 12%, and the worst 3-month return was still **+81.6% CAGR-equivalent**. None of the 2020-2025 historical periods constitute a "grinding_dd" or "vol_explosion" regime — they include the 2020 COVID crash and 2022 rate shock, but neither sustained for an entire year nor pushed σ to 4× normal. EXP-3200 fills the gap that history did not provide.

**The honest synthesis:** the strategy is empirically robust to *everything that has happened in 2020-2025* and is robust to *modest distributional stress* (baseline, flash_crash, credit_freeze MC scenarios). It is **not robust to a year of sustained 2022-style μ-drift × 2** (`grinding_dd`) or a **year of sustained March-2020-style σ × 4** (`vol_explosion`). The 3% circuit breaker and v5_hedge sleeve mitigate but do not eliminate these tails.

---

## 5 · Interpretation for LPs

### 5.1 What the validation supports

1. **No evidence of overfitting.** 60-fold rolling re-fits across 5 calendar years all produce positive net Sharpe; the median train→test gap is negative. The strategy is not curve-fit to a single regime.
2. **The 12% DD claim is empirically supported in-sample (60/60 folds clean) and supported under modest MC stress** (baseline / flash_crash / credit_freeze breach rates 2.8 – 7.6%).
3. **Diversification is structural.** Average pairwise stream correlation stays ≤ 0.04 across all 60 train windows. The 8-stream construction is not degenerating to a 1-factor exposure as the data grows.
4. **The strategy makes money during 2022.** The single calendar year that contains the rate-shock and bear-market regime change still produced minimum net Sharpe 4.46, median 5.79 across 13 fold tests.

### 5.2 What the validation does NOT support

1. **The 12% DD claim does NOT hold in vol_explosion or grinding_dd regimes.** P(breach) is 100% and 97.7% respectively without the circuit breaker; 96.1% and 77.1% with it.
2. **The strategy LOSES money in the grinding_dd regime** on average (mean Sharpe ≈ −1.7) — by construction, since we shifted μ. This is the regime where alpha decay would be most lethal.
3. **A vol-explosion year is a survival event, not a profit event.** Mean Sharpe is ~1.0 net of drag; 22% of paths end the year below −25% return. The v5_hedge sleeve mitigates this but cannot eliminate it.
4. **Historical OOS data does not include pre-2020 regimes.** Our IronVault option-chain history starts 2020-01-01. We cannot test the v8a strategy on 2008 GFC, 2011 Euro crisis, or 2015 China shock with real chains.

### 5.3 What we DO about it

- **3% trailing-DD circuit breaker** (EXP-2370, "flatten_3pct"): production-default, validated over 20 folds with zero false trips. Cuts moderate-stress breach rates by half.
- **v5_hedge sleeve**: pays a small negative Sharpe (−0.14 standalone) for VIX-call protection that activates in vol explosions. Crisis insurance, not alpha.
- **Tranche regression triggers**: 6-month rolling Sharpe < 2.5 → tranche step-down; single-month DD > 12% → halt new entries and force external review; DD > 25% → strategy-validity review and external audit.
- **Pause-and-validate commitment**: written into paper-to-live gate G2 (live Sharpe must stay in [5.1, 6.9] for 4 weeks before advancing tranches). A persistent breach pauses the program rather than scales it.

---

## 6 · Reproducibility

All numbers in this document are pulled directly from:

- `compass/reports/exp3230_rolling_walkforward.json` (60-fold rolling WF, 1-month step)
- `compass/reports/exp3230_rolling_walkforward.html` (visual report)
- `compass/reports/exp3200_monte_carlo_stress.json` (10K-path MC, 5 scenarios)
- `compass/reports/exp3200_monte_carlo_stress.html` (visual report)

Underlying data:
- Stream cube: `compass/cache/exp2080_streams.pkl` (real IronVault + Yahoo)
- QQQ chains: `compass/cache/exp2250_qqq_trades.pkl` (real IronVault)
- Drag rate: 890.3 bps/yr from EXP-2570 (Alpaca commfree + EXP-2470 ExecOpt stack)
- Covariance: Ledoit-Wolf shrinkage (EXP-2360 / EXP-2390)

Rule Zero is enforced for both experiments: no synthesised option chains, no fabricated returns. The MVN simulation in EXP-3200 is calibrated to the real cube's per-stream μ, σ, and SPY-β.

---

## 7 · Limitations and known weaknesses (disclosure)

1. **MVN distributional assumption in EXP-3200.** No Student-t, no jump-diffusion, no GARCH stochastic-vol. True tails may be thicker than reported. The `vol_explosion` scenario partially compensates by using Σ × 16 as a covariance multiplier, but this is a parametric stand-in, not an empirical tail.
2. **Correlation breakdowns *during* a stress path are only partially modelled** (the `credit_freeze` scenario uses a static correlation shrink toward all-ones; it does not allow correlations to drift dynamically *during* a path).
3. **EXP-3230 data window starts 2020-01-01**. We cannot back-test v8a on pre-2020 regimes with real chains. Anyone wanting a pre-2020 stress should look at our 2008/2011 historical stress in EXP-2640 (`vix_stress_hardening`) and accept that those use beta-propagated equity returns, not real option chains.
4. **Test windows overlap in EXP-3230** because the step (21 days) is smaller than the test window (63 days). Each fold's test slice is therefore not fully independent. The pooled-day metric (1,302 days) deduplicates the overlap, but fold-distribution metrics treat each fold as independent — this slightly understates the variance of the fold-Sharpe distribution.
5. **The 1.81 weight-drift outlier in EXP-3230** sits inside a flagged fold. We have not investigated whether it represents a model fragility or simply a low-information training window; the corresponding test slice still produced acceptable performance.

---

## 8 · Next steps

- **Unlock pre-2020 history.** Polygon Options Advanced or CBOE DataShop subscription would give us 2010-2019 option chains — enabling true OOS tests on 2011 Euro crisis, 2015 China shock, 2018 Volmageddon, and the late-cycle 2018 sell-off.
- **Add Student-t and jump-diffusion stress.** Augment EXP-3200 with non-Gaussian distributional models. Track P(DD > 12%) divergence between MVN and heavy-tailed assumptions.
- **Investigate the 2025 worst-fold (#52).** Decompose the 3.88 Sharpe by stream to identify whether a specific sleeve is fragile in tariff-shock chop windows.
- **Build a survival-time model.** Estimate the expected time to recovery from each DD bucket using the EXP-3200 path data; fit a parametric Cox proportional-hazards model to the simulated paths.

---

*Document compiled for LP distribution. Past results — including simulated results from EXP-3200 — are not indicative of future performance. This is not an offer to sell securities.*
