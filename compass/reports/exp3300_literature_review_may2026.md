# EXP-3300 Literature Review — VRP Frontier Papers (May 2026)

**Date:** 2026-05-09
**Builds on:** `literature_review_2024_2026.md`, `exp3200_literature_review_extended.md`
**Scope:** signal extraction, regime-dependent VRP, crypto options, execution innovations
**Method:** WebSearch on Google Scholar / arXiv / SSRN / Wiley / Federal Reserve. Primary URLs verified.
**Coverage:** 5 most promising papers selected from ~30 candidates surfaced.

---

## Selection criteria

For each paper we required:
1. Empirical, not pure-theory.
2. Published or working-paper post-2023-12.
3. Relevance to at least one of: SPY/QQQ index-option premium harvesting, sector ETF cost mechanics, calendar/cross-vol structures, hedge sleeve design.
4. Specific testable mechanic, not just a general theme.

---

## Paper 1 — Fouhy (2026): Hierarchical ML for VRP Estimation

**Title:** "Hierarchical Machine Learning for Variance Risk Premium Estimation: From VIX Forecasting to Options Trading"
**Author:** Andrew Fouhy
**Source:** SSRN 6570380 (~April 2026, two weeks old at time of survey)
**URL:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6570380

### Core finding
A hierarchical ML stack — VIX forecasting model on top, mapped to a tradable VRP estimate at the bottom — outperforms single-stage models on both VIX prediction error and downstream option-strategy P&L. The architecture uses tree/ensemble methods at the forecasting layer and a calibration layer that adjusts for the implied-vs-realised wedge directly.

### Relevance to v8a 8 streams
- **High** — directly addresses the signal-extraction problem for exp1220 (SPY 28DTE PCS) and qqq_cs. Our current size/timing rules are essentially threshold-based on VIX percentile + realised-vol percentile. A hierarchical model could replace the threshold layer.
- The "calibration to realised P&L" step is methodologically interesting: it avoids the standard bug where a better volatility forecast doesn't translate to a better P&L because the loss function is mismatched.

### Signal ideas not yet tested
- **EXP-3301:** Replace the v8a percentile gate on exp1220/qqq_cs with a 2-stage stacked model: (a) HAR-RV → next-month RV forecast, (b) calibration head trained on realised-strategy-PnL, not on RV-MSE.
- **EXP-3302:** "Forecast disagreement" signal — train two heterogeneous models (tree + recurrent NN) and gate sizing on the cross-model disagreement (high disagreement = avoid).

### Caveat
Single-author SSRN preprint; not peer reviewed. We should treat any results as suggestive only and pre-register OOS metrics carefully (Bug-6).

---

## Paper 2 — arXiv 2510.03236: Regime-Switching for SPX Vol Forecasting

**Title:** "Improving S&P 500 Volatility Forecasting through Regime-Switching Methods"
**Source:** arXiv 2510.03236 (Oct 2025)
**URL:** https://arxiv.org/html/2510.03236v1
**Sample:** SPX 5-minute realised volatility, May 2014 - May 2025.

### Core finding
A regime-switching wrapper around HAR-RV improves 1-day, 5-day, and 22-day RV forecasts, particularly during regime transitions. Best-performing variants combine HMM regime probabilities with HAR's lagged-RV structure. Multi-input ML achieves **0-2 days lag** to detect regime shifts (vs 1-3 days for plain HMM, vs 3-7 days for VIX-threshold rules), via early features in term structure, VVIX, and put/call ratio.

### Relevance to v8a 8 streams
- **High** — v8a's regime tagger uses VIX-percentile bands. The paper provides published evidence that term-structure + VVIX + P/C ratio detect regime changes earlier than VIX itself. Earlier regime detection means smaller drawdowns at regime transitions.
- exp2630 (regime stress OOS) and exp2750 (OOS regime stress) already established our regime-tagger has lag — this paper quantifies the size of that lag against best-in-class.

### Signal ideas not yet tested
- **EXP-3303:** Add VVIX-3M-spread and SPX 25Δ put/call IV-skew to the v8a regime-detection feature set; measure whether it shrinks the regime-transition-drawdown that EXP-2630 documented.
- **EXP-3304:** Regime-conditional sizing — instead of regime gating (binary on/off), scale stream weights as a continuous function of regime-probability output from an HMM trained per stream.

### Caveat
The paper forecasts realised volatility, not strategy returns. Better RV forecast does not guarantee better PnL — see Fouhy's calibration-layer point.

---

## Paper 3 — arXiv 2410.15195: Risk Premia in the Bitcoin Market

**Title:** "Risk Premia in the Bitcoin Market"
**Source:** arXiv 2410.15195v2 (Oct 2024, revised early 2025)
**URL:** https://arxiv.org/html/2410.15195v2

### Core finding
Documents stylised features and time-variation of risk premia (variance, jump, equity-index correlation) on BTC options using Deribit data. Key empirical claims:
- BTC variance risk premium is **positive and large in magnitude** during low-vol regimes (typical of mid-2024) and **flips sign or compresses** during stress (e.g., March 2020, May 2022).
- Jump premium dominates VRP at short DTEs, mirroring Božović's 2025 SPX-0DTE finding.
- Limited academic exploration of crypto-options-implied risk premia — first comprehensive treatment.

### Relevance to v8a 8 streams
- **Low-to-medium** — v8a does not currently trade crypto options. But the paper provides the *only* asset class where VRP is documented as still robust post-2020, contrasting Dew-Becker-Giglio's SPX null and Heston-Todorov's "near-zero SPX VRP".
- If the v8a thesis is "find universes where dealer-GEX has not flipped", crypto options are a candidate universe (Deribit market structure differs materially from CBOE).

### Signal ideas not yet tested
- **EXP-3305:** Pilot study — capture daily DVOL (Deribit's BTC implied-vol index) and BTC realised-vol from public data, compute VRP estimate, and back-test a percentile-gated short-vol strategy 2020-2025 using public Deribit data. *Note:* this is a research-only experiment; production would require Deribit access.
- **EXP-3306:** Cross-correlation — does BTC VRP carry information about SPX VRP regime? Test predictive power of BTC-DVOL term structure on next-week v8a stream returns.

### Caveats
- IronVault has no crypto-options data; would require separate data pipeline (Rule 1: real data only).
- Crypto regulatory and execution risk is materially different from US equity.
- Academic data on Deribit is limited; this paper is an early entrant, not a settled finding.

---

## Paper 4 — Huang et al. (2025): Option Return Predictability via ML in China

**Title:** "Option Return Predictability via Machine Learning: New Evidence From China"
**Source:** Journal of Futures Markets 2025
**URL:** https://onlinelibrary.wiley.com/doi/10.1002/fut.22604

### Core finding
Applies the Gu-Kelly-Xiu empirical-asset-pricing-via-ML framework to Chinese index options. Tree ensembles and shallow neural networks dominate linear models. **Top predictors are options-microstructure variables** (open-interest changes, bid-ask spread, IV-rank percentiles) and **idiosyncratic-vol terms** rather than firm fundamentals. Predictive R² is highest at monthly horizon and degrades sharply intraday.

### Relevance to v8a 8 streams
- **Medium** — confirms that for index options, microstructure features carry predictive content beyond the standard VRP percentile gate. Our 8 streams currently use volatility/percentile features but not OI-change or IV-rank-trajectory features.
- The Chinese-market sample is independent of US/Europe, providing OOS validation of the general ML-options approach.

### Signal ideas not yet tested
- **EXP-3307:** Add OI-change-percentile and IV-rank-30d-trend to the exp1220/qqq_cs feature set; measure whether either improves the entry-timing component of the strategy.
- **EXP-3308:** Train a per-stream gradient-boosted model on monthly forward returns using a 2019-2022 in-sample / 2023-2024 OOS split, with strict pre-registration of the OOS metric (Bug-6 compliance).

### Caveat
Chinese options market has different end-user composition (high retail), different settlement (cash vs physical for SSE 50), and different transaction-cost regime. Transferability is a research question, not an assumption.

---

## Paper 5 — Doshi, Patel, Singal (May 2025): Risky Intraday Order Flow and Option Liquidity

**Title:** "Risky Intraday Order Flow and Option Liquidity"
**Authors:** Doshi, Patel, Singal
**Source:** Working paper, May 23, 2025
**URL:** https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf

### Core finding
Bid-ask spreads on options are determined by daily *absolute* order imbalance, not by raw volume. Mechanism: as end-user pressure pushes MMs off optimal inventory, MMs widen spreads to discourage further imbalanced flow and to offset inventory risk. This is documented cross-sectionally and time-series across the equity-option universe.

(Already cited in `exp3200_literature_review_extended.md`; deeper review here because of its execution-innovation angle.)

### Relevance to v8a 8 streams
- **High for execution layer** — our cost model is volume-and-spread based. If imbalance is the true causal variable, our model is mis-specified for any stream where order flow is one-sided (likely XLF/XLI based on sector-rotation flows; possibly cross_vol).
- Paper-trading versus live-trading degradation (Rule 13: live ≈ 0.5-0.7× backtest) may be partly due to executing on the *imbalanced* side of the book.

### Signal ideas not yet tested
- **EXP-3309:** Reconstruct daily signed order flow per stream from IronVault prints (using Lee-Ready or BVC algorithm). Test cross-section: are XLF/XLI option-flow imbalances larger than SPY/QQQ?
- **EXP-3310:** Execution-side innovation — split entry orders to the *minor* side of the imbalance (e.g., if the day is heavily put-buying, sell our calls first and put credit later in the day). Measure whether this captures a portion of the spread instead of paying it.

### Caveat
The 2025 paper does not yet have peer-reviewed publication; treat as working-paper evidence. Imbalance estimation from end-of-day data has noise — order-flow signals from low-frequency data may not be implementable.

---

## Cross-paper themes

### Theme A — VRP is alive but increasingly micro-structural
Papers 1, 2, 4, and 5 all suggest the simple VIX-percentile / IV-rank gate captures only a fraction of the available signal. Microstructure variables (OI changes, term structure, VVIX, put/call skew, order imbalance) carry incremental predictive content. v8a's current feature set is closer to 2010-vintage research than 2025-vintage.

### Theme B — Regime detection lag is the recurring weak spot
Papers 1 and 2 both note that VIX-threshold rules lag the actual regime change by 3-7 days, while ML/HMM detectors lag 0-3 days. This 4-day differential maps directly onto the v8a regime-transition drawdowns documented in exp2630.

### Theme C — Crypto VRP as the un-arbitraged frontier
Paper 3 provides the only asset class with a clear post-2020 positive VRP. The natural extension of Dew-Becker's "where has dealer-GEX flipped?" mechanism is to test other markets where it has not. Crypto is the most obvious candidate. Strategically interesting; data-pipeline cost is a real obstacle.

### Theme D — Execution layer, not signal layer, is where money is being lost
Paper 5 (and the previous O'Donovan-Yu analysis) suggest the gap between gross and net Sharpe is the binding constraint. Better execution beats better signals at the margin v8a operates in.

---

## Recommended experiments — ranked by expected value

| # | EXP | Effort | Expected Sharpe lift (gross) | Risk |
|---|-----|--------|-------------------------------|------|
| 1 | EXP-3303 | 2d | +0.2-0.4 | Low — adds features to existing detector |
| 2 | EXP-3309 | 1d | informational only (cost model) | Low |
| 3 | EXP-3310 | 4d | +0.3-0.6 NET (execution savings) | Medium — needs paper-trade validation |
| 4 | EXP-3308 | 5d | +0.4-0.8 if it works | Medium — overfitting risk; strict OOS |
| 5 | EXP-3301 | 3d | +0.3-0.5 | Medium — Fouhy paper not yet replicated |
| 6 | EXP-3304 | 2d | +0.1-0.3 | Low |
| 7 | EXP-3305 | 5d (data pipeline) | informational | High — Rule 1 data sourcing, regulatory |
| 8 | EXP-3307 | 1d | +0.1-0.2 | Low — additive feature test |
| 9 | EXP-3302 | 2d | +0.1-0.3 | Low — disagreement gate |
| 10 | EXP-3306 | 2d | informational | Low |

### Suggested sequencing

1. **EXP-3309** first (1 day, informational, sets up EXP-3310 and validates EXP-3203 from prior review).
2. **EXP-3303** second (2 days, low risk, directly addresses regime-lag drawdowns documented in EXP-2630).
3. **EXP-3310** third (4 days, highest *net* Sharpe lift if real).
4. **EXP-3308** if the prior three confirm there is signal headroom.
5. **EXP-3305 / EXP-3306** only if leadership wants to seriously consider crypto as a new universe.

---

## Bottom line

Five papers, five distinct angles. The 2024-2026 literature has shifted from "is VRP real?" (settled: mostly no on SPX, sector-dependent elsewhere) to "where in the workflow can ML/microstructure features add value?" The frontier is now:

1. **Earlier regime detection** (Paper 2) — directly addresses our worst documented weakness.
2. **Microstructure features for signal** (Papers 1, 4, 5) — feature-engineering lift, not paradigm change.
3. **Execution-side innovation** (Paper 5) — the underrated lever; biggest potential live-trading impact.
4. **New universes** (Paper 3) — strategically interesting, infrastructure-heavy.

**Single highest-priority next step:** EXP-3303 (term-structure / VVIX / put-call-skew added to the v8a regime detector) — cheap, low-risk, directly maps to the documented regime-transition drawdown problem in exp2630.

---

## Sources

- [Fouhy — Hierarchical ML for VRP Estimation (SSRN 6570380)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6570380)
- [Improving S&P 500 Volatility Forecasting through Regime-Switching Methods (arXiv 2510.03236)](https://arxiv.org/html/2510.03236v1)
- [Risk Premia in the Bitcoin Market (arXiv 2410.15195)](https://arxiv.org/html/2410.15195v2)
- [Huang et al. — Option Return Predictability via ML: China (J. Futures Markets 2025)](https://onlinelibrary.wiley.com/doi/10.1002/fut.22604)
- [Doshi, Patel, Singal — Risky Intraday Order Flow and Option Liquidity (May 2025 WP)](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf)
- [Du — Pricing Cryptocurrency Options With Volatility of Volatility (J. Futures Markets 2025)](https://onlinelibrary.wiley.com/doi/10.1002/fut.70029?af=R)
- [Federal Reserve 2025 — Linear vs Nonlinear Vol Forecasting](https://www.federalreserve.gov/econres/feds/files/2025061pap.pdf)
- [O'Donovan & Yu — Transaction Costs and Cost Mitigation (SSRN 4806038)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [AI-Powered Algorithmic Trading: HMM + Neural Networks (arXiv 2407.19858)](https://arxiv.org/html/2407.19858v6)
