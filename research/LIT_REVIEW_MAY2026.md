# Systematic Literature Review — VRP, Dealer GEX, Execution Alpha (May 2026)

**Date:** 2026-05-11
**Author:** CC3 / Maximus research agent
**Coverage:** 20 papers, 2017-2026 (with 18 from 2020+ and 14 from 2024+)
**Companion files:** consolidates prior synthesis from `compass/reports/literature_review_2024_2026.md`, `paper_analysis_dew_becker_giglio.md`, `paper_analysis_odonovan_yu.md`, `pdf_analysis_dew_becker_odonovan.md`, `exp3200_literature_review_extended.md`, `exp3300_literature_review_may2026.md`, `compass/literature_review_2025_2026.md`. **This document is the single authoritative systematic review** organised around the four requested research themes and produces a concrete spec for EXP-3000 (dealer-GEX gating).

---

## Theme 1 — Dealer GEX and the post-2010 VRP decline

The DBG mechanism is that dealer net gamma exposure flipped from structurally short (pre-2008) to ~zero or positive (post-2008) due to (a) banking-system reforms restricting dealer derivative inventories, (b) the rise of vol-selling ETPs (XIV, SVXY, covered-call ETFs), and (c) end-investor flow becoming more two-sided. The flip removed the structural reason dealers demanded a large premium to warehouse variance risk; SPX VRP collapsed as a consequence.

### P1. Dew-Becker & Giglio (2025) — "The Decline of the Variance Risk Premium"
- Chicago Fed WP 2025-17 / SSRN 5525882 ([URL](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en))
- **Finding:** SPX long-put cumulative return is zero from March 2009 to December 2022.
- **Method:** synthetic options (dynamic delta-replication) as benchmark; long traded options as test asset; difference = VRP.
- **Mechanism:** dealer net-GEX flip — the central post-2010 explanation.

### P2. Vasquez, Amaya, Pearson, Garcia-Ares (2025) — "0DTE Index Options and Market Volatility"
- SSRN 5113405 ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405))
- **Finding:** despite 0DTE being ~59% of SPX volume, net market-maker gamma hedging is ~0.2% of SPX daily liquidity — customer flows are balanced.
- **Implication for DBG mechanism:** the GEX flip has *not* been undone by the 0DTE boom. DBG mechanism intact through 2025.

### P3. Dim, Eraker, Vilkov (Nov 2023) — "0DTEs: Trading, Gamma Risk and Volatility Propagation"
- SSRN 4692190 ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190))
- **Finding:** Market-maker net gamma on 0DTEs is on average **positive** and **negatively related to future intraday volatility** — i.e., dealers stabilise the index intraday (the long-gamma regime DBG postulates).
- **Direct corroboration** of DBG mechanism via independent dataset.

### P4. Cboe research (2023-24) — "Volatility Insights: 0DTE Market Impact"
- ([URL](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/))
- **Finding:** uses proprietary Cboe trade data 2020-2023 to reconstruct OMM net positions at 1-minute frequency; finds no destabilising 0DTE effect.
- Industry-side validation of P2 & P3.

### P5. Regan & Xie (Dec 2025) — "Latent Market Forces: LLM Detection of GEX Patterns"
- arXiv 2512.17923 ([URL](https://arxiv.org/pdf/2512.17923))
- **Finding:** 95.6% of 2024 trading days exhibited negative net GEX (mean -$19.87B). One-standard-deviation increase in gamma imbalance reduces absolute returns by ~20bp (≈20% of σ).
- **Tension with DBG:** P5 reports negative GEX in 2024, P3 reports positive on 0DTEs. Resolution: 0DTEs are positive-gamma; longer-dated SPX is negative-gamma; aggregate index GEX is the net of these layers. Useful for GEX construction in EXP-3000.

### P6. Ober (2024) — "Intermediary Inventory Risk and the Pricing Kernel"
- SSRN 5032337 ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5032337))
- **Finding:** when MMs are short index options, the pricing kernel is U-shaped in market returns — driven by hedging-constraint binding, not stochastic-vol risk per se.
- **Mechanism enrichment:** identifies *when* MMs charge the premium (when hedging constraints bind) vs *when* they don't (when constraints slack).

### P7. Terstegge (2025) — "Intermediary Option Pricing"
- FMA 2025 Derivatives Conf ([URL](https://www.fma.org/assets/docs/Derivatives2025/Terstegge.pdf))
- **Finding:** "The premium materialises precisely when hedging constraints bind (overnight) and where dealers' short exposure is concentrated (puts)." S&P 500 put options earn an average **overnight** return of −2.49% (large premium-extracting move) vs **intraday** of just 0.39%.
- **Bridges P3/P5 to P8 below:** explains *which window* in the trading day the residual VRP appears.

### P8. He, Kelly, Manela (2017) — "Intermediary Asset Pricing: Many Asset Classes"
- ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2721783))
- **Finding:** primary-dealer equity capital ratio prices the cross-section of equity, bond, derivatives, FX, commodities returns.
- **Why included:** foundational framework for DBG. The dealer-balance-sheet mechanism that DBG operationalises for VRP is the He-Kelly-Manela machinery applied to one asset class.

---

## Theme 2 — Sector ETF vs SPX — does VRP behave differently?

### P9. Heston & Todorov (2024) — "Exploring the Variance Risk Premium Across Assets"
- SSRN 4373509 / AEA 2024 ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509))
- **Finding:** 20-asset cross-section. "Almost all assets earn negative VRP." But **SPX VRP is not significantly different from zero 2006-2020.**
- **Implication:** the DBG decline is SPX-specific, not pervasive across asset classes. Cross-asset confirmation of DBG on SPX, while documenting persistent VRP in commodities, FX, Treasuries.
- **Gap:** US equity sector ETFs (XLF/XLI/etc.) are NOT in the 20-asset universe.

### P10. SSE 50 ETF Options Paper (2024) — "Volatility Risk Premium: Good Vol and Bad Vol"
- ScienceDirect ([URL](https://www.sciencedirect.com/science/article/abs/pii/S1062940824001311))
- **Finding:** Chinese SSE 50 ETF options exhibit positive VRP that decomposes into "good" and "bad" components with different risk pricing.
- **Implication:** ETF-options VRP is *not zero* on a non-US ETF universe — supports the hypothesis that the DBG collapse is universe-specific.

### P11. Bitcoin VRP — Risk Premia in the Bitcoin Market (Oct 2024)
- arXiv 2410.15195 ([URL](https://arxiv.org/html/2410.15195v2))
- **Finding:** BTC variance risk premium is positive and large in low-vol regimes; flips/compresses in stress. Jump premium dominates short DTE.
- **Implication:** crypto is the only documented post-2020 universe with a robust positive VRP.

### P12. Papagelis & Dotsis (2025) — "VRP Over Trading and Nontrading Periods"
- J. Futures Markets ([URL](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589))
- **Finding:** VRP is significantly negative overnight, ~zero intraday, in US/Europe/Asia indices.
- **Bridge:** Together with P7 (Terstegge), the residual SPX VRP is concentrated in the overnight window — strategies that don't hold through the close miss it.

### Sector-ETF VRP gap
No 2024-2026 academic paper directly tests XLF/XLI/XLE/etc. VRP. The closest is the SSE 50 result (P10), which is a sector-adjacent (large-cap ETF) test in a different jurisdiction. **This is the central research gap for v8a.**

---

## Theme 3 — Execution alpha and transaction costs (O'Donovan framework)

### P13. O'Donovan & Yu (2024) — "Transaction Costs and Cost Mitigation in Option Investment Strategies"
- SSRN 4806038 ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038))
- **Finding:** 17/24 long-short delta-hedged equity-option strategies are gross-significant; **0/24 net of TC**. Three mitigation techniques: low-cost universe filter, hold-to-maturity, long-only + 0.9× short-SPX-index-option (recovers 7/24 strategies with 36-114bp/month returns).
- **Entry-exit spread cliff:** 24% quoted spread at entry, 57% at exit.

### P14. Heston, Jones, Khorram, Li, Mo (2023) — "Anomalies in Delta-Hedged Option Returns"
- Cited extensively in P13. Effective-spread benchmark: 20.3% of quoted half-spread.

### P15. Duarte, Jones, Mo, Wang (2023) — "Look-Ahead Bias in Option Return Studies"
- **Finding:** common filters use exit-date information; biases gross returns upward and TC measurements downward — *interactive* effect.
- **Why included:** explains why pre-2023 literature overstates net returns; sets the methodological bar for any new backtest.

### P16. Muravyev & Pearson (2020) — "Options Trading Costs are Lower than You Think"
- **Finding:** sophisticated traders pay only ~20.3% of the quoted half-spread by timing their executions to MM quote movements.
- **Why included:** the foundation for P13/P14's effective-spread assumption; basis for execution-alpha claims.

### P17. Christoffersen, Goyenko, Jacobs, Karoui (2018) — "Illiquidity Premia in the Equity Options Market"
- **Finding:** options illiquidity (ILLIQ measure) is priced cross-sectionally.
- **Why included:** one of the 24 predictors in O'Donovan-Yu's universe; foundational for the option-microstructure factor literature.

### P18. Doshi, Patel, Singal (May 2025) — "Risky Intraday Order Flow and Option Liquidity"
- ([URL](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf))
- **Finding:** option bid-ask spread is driven by *absolute order imbalance*, not raw volume; delta-hedging adjustments throughout the day reflect liquidity providers' costs, especially when gamma is elevated near expiration.
- **Implication for v8a:** our volume-based TC model may be mis-specified for streams with one-sided flow (XLF/XLI plausibly).

### P19. Mu (2025) — "Liquidity and Price Informativeness in Extended Trading Hours"
- J. Futures Markets ([URL](https://onlinelibrary.wiley.com/doi/10.1002/fut.70026))
- **Finding:** non-RTH option markets exhibit materially lower liquidity, wider spreads. Implication: execution timing matters.

### P20. Cao, Jacobs, Ke (2024) — "Derivative Spreads: Evidence from SPX Options"
- AEA 2024 ([URL](https://www.aeaweb.org/conference/2024/program/paper/DFs2GZND))
- **Finding:** Documents SPX-options spread structure as benchmark for the cheapest end of listed-option markets — reinforces 20.3% benchmark.

---

## Theme 4 — Post-2020 VRP persistence evidence

### Summary of converging evidence
- **SPX:** P1 (DBG), P9 (Heston-Todorov), P12 (Papagelis-Dotsis intraday null). **VRP near zero on a cumulative basis post-2009.**
- **Overnight SPX:** P7 (Terstegge -2.49% night put return), P12. **Residual VRP is real but isolated to the overnight window.**
- **0DTE SPX:** P3, P4, P5. **MM net gamma is balanced/positive — no large residual premium to be extracted intraday.**
- **Cross-asset (non-US-equity-index):** P9 documents persistent negative VRP in commodities/FX/Treasuries.
- **Chinese SSE 50 ETF:** P10. Positive VRP, decomposable.
- **Crypto:** P11. Positive VRP, regime-dependent.
- **US sector ETFs (XLF/XLI/etc.):** *no academic paper directly tests* — the literature gap for v8a.

---

## Implications for v8a — what is reinforced, challenged, opened

### Reinforced
- **v5_hedge sleeve design** = the O'Donovan-Yu "0.9 units short SPX index option" prescription. Most-defended piece of v8a.
- **ETF (cheap-universe) selection** = the O'Donovan-Yu low-cost-universe mitigation. 6 of 8 streams already trade ETF options.
- **Selling premium rather than buying** = aligns with the long-only-top-decile prescription where O'Donovan-Yu recover net-of-cost significance.

### Challenged
- **exp1220 (SPY 28DTE PCS) and qqq_cs alpha mechanism** — these trade in DBG's universe; their post-2020 survival (EXP-3150) is empirically real but mechanistically un-explained by the literature.
- **Early exit at 50% profit** hits O'Donovan-Yu's 57%-exit-spread cliff — leaves money on the table.
- **Sector-ETF stream survival** (xlf_cs/xli_cs) has no academic corroboration — opportunity but also risk.

### Opened
- **Overnight-vs-intraday attribution** (P7, P12) — testable from IronVault timestamps.
- **Order-imbalance TC model** (P18) — refinement to our cost simulator.
- **Crypto universe** (P11) — strategically interesting, infrastructure-heavy.

---

## EXP-3000 — Dealer GEX Gating Specification

### Motivation
DBG mechanism is dealer net GEX. Vasquez et al. and Regan-Xie show dealer GEX is measurable from open-interest data. If v8a stream alpha is concentrated in *negative-GEX regimes* (dealer-short-gamma, structurally premium-paying), gating on GEX level should materially improve net Sharpe by avoiding zero-edge regimes.

### GEX construction (per-underlying, daily)

For underlying U ∈ {SPY, QQQ, XLF, XLI, GLD, SLV}, on day t:

1. Pull end-of-day option chain from IronVault: for each contract, get OI, gamma (computed from Black-Scholes with realised IV), strike, DTE.
2. Aggregate **dealer-perspective net gamma** assuming standard market-maker positioning model:
   - Calls: dealers are short (customers buy calls → MM sells) → MM gamma per contract = −γ × 100 × OI × spot²/100
   - Puts: dealers are long (customers sell puts via covered calls and overwrite ETFs, or buy puts as hedges with offsetting institutional vol-selling) → application of standard SpotGamma-style asymmetric assumption: MM gamma per contract = +γ × 100 × OI × spot²/100
   - **Caveat:** this is the convention used in published research (Dim-Eraker-Vilkov, Cboe). Real positioning is more nuanced. Use it as a proxy.
3. Sum across all contracts: GEX_U(t) = Σ MM-gamma.
4. Normalise: GEX_pct_U(t) = GEX_U(t) / GEX_U_60d_rolling_std — captures regime relative to recent positioning.

### Threshold rules (initial spec — to be calibrated in EXP-3001 sweep)

Conservative default values, OOS-calibrated 2019-2022 then OOS 2023-2024:

| Regime | GEX_pct | Stream action |
|--------|---------|----------------|
| Strong-negative-GEX (dealer-short-gamma, max-premium) | ≤ −1.5 | **1.5× base size** (lean into the regime) |
| Negative-GEX | −1.5 < GEX_pct ≤ −0.5 | **1.0× base size** (baseline) |
| Neutral | −0.5 < GEX_pct < 0.5 | **0.7× base size** (caution — DBG-consistent zero alpha regime) |
| Positive-GEX | 0.5 ≤ GEX_pct < 1.5 | **0.4× base size** (dealer-long-gamma, premium compressed) |
| Strong-positive-GEX | GEX_pct ≥ 1.5 | **0.0× base size** (no new positions) |

### Stream-level application

Stream-by-stream gating decision tree:

| Stream | Use GEX_underlying? | Use GEX_SPX as proxy? | Notes |
|--------|---------------------|------------------------|-------|
| exp1220 (SPY 28DTE PCS) | GEX_SPY | Yes, cross-validate | Primary test case |
| qqq_cs | GEX_QQQ | Yes, cross-validate | Primary test case |
| xlf_cs | GEX_XLF | Cross-validate with SPX | XLF chain may have insufficient OI for stable GEX; if so, fall back to SPX |
| xli_cs | GEX_XLI | Cross-validate with SPX | Same caveat as xlf_cs |
| gld_cal | GEX_GLD | No — commodities differ | Calendar P&L mechanism is term-structure, not pure VRP; gating may not transfer |
| slv_cal | GEX_SLV | No | Same |
| cross_vol | GEX_SPX (composite) | Composite SPY×QQQ GEX | Out-of-scope for first pass |
| v5_hedge | **Inverse gating** — *increase* when GEX_SPY positive | This is the put-protection sleeve | When dealers are long-gamma (premium compressed), hedge is cheap → buy more |

### Backtest plan

1. **Phase A (calibration, 2019-2022 IS):**
   - Reconstruct daily GEX series for all six underlyings from IronVault.
   - Sweep threshold parameters (size multipliers, percentile cutoffs) on the four "primary test case" streams.
   - Pre-register the OOS test plan.

2. **Phase B (OOS validation, 2023-2024):**
   - Apply locked thresholds; measure net Sharpe lift vs no-gating baseline.
   - Decision rule for adoption:
     - Net Sharpe lift ≥ 0.3 on the OOS slice
     - Max drawdown not deeper than 1.1× baseline
     - Capacity (AUM-scaled) unchanged or improved
     - All four streams individually pass (no portfolio-level masking of stream-level failure)

3. **Phase C (paper trading, 2026-Q2/Q3):**
   - Live-replay the gating on real chain data; measure backtest-to-live degradation (Rule 13).
   - Adopt to production only if degradation ≤ 30% of backtest Sharpe lift.

### Risks and failure modes for EXP-3000

| Risk | Mitigation |
|------|-----------|
| Dealer-positioning convention is wrong (call/put long/short asymmetry doesn't match reality) | Cross-validate against SpotGamma free indicator; compute under multiple asymmetry conventions. |
| GEX for low-OI sector ETFs (XLF/XLI) is noisy and unstable | Apply rolling 10-day smoothing; fall back to SPX-GEX proxy if normalised stream stability below threshold. |
| Threshold over-fitting | Use only 4-bin discretisation (not continuous); fix percentile breakpoints not levels; hold-out 2024 entirely as final OOS. |
| Look-ahead bias in GEX construction (Duarte et al. 2023 problem) | Use lagged 1-day OI (T-1) for GEX computation on day T. |
| Gating destroys diversification | Track stream-correlation matrix pre-vs-post-gating; require correlation matrix Frobenius norm change ≤ 15%. |

### Pre-registered metrics for EXP-3000

1. Net Sharpe per stream (gross net of 20.3%-half-spread cost) for 2023-2024 OOS slice.
2. Maximum drawdown per stream and aggregate.
3. AUM-capacity (slippage-scaled) at $50M, $100M, $250M target levels.
4. Per-stream regime allocation: fraction of days at each GEX bin.
5. Stream-correlation Frobenius-norm change.

### Acceptance criteria for EXP-3000 → EXP-3001 sweep
- At least 2 of 4 primary streams pass the Phase B decision rule.
- Aggregate net Sharpe lift ≥ 0.2 on OOS.
- No stream individually degrades by ≥0.15 Sharpe.

---

## Actionable next steps — prioritised

| Rank | Experiment | Effort | Why |
|------|-----------|--------|-----|
| 1 | **EXP-3211** DBG cumulative-alpha check on v8a streams | 1d | Cheapest sanity test: does our SPX-cousin stream cumulative line look like DBG's flat post-2009? |
| 2 | **EXP-3000 Phase A** GEX reconstruction + IS sweep | 3-4d | The flagship test of the DBG mechanism on v8a. Specification above. |
| 3 | **EXP-3201** Sector-ETF GEX proxy reconstruction (subset of EXP-3000) | 2d | Tests whether sector ETFs are in negative-GEX regime (which would explain xlf_cs/xli_cs survival). |
| 4 | **EXP-3202** Overnight vs intraday attribution | 1d | Validates P7/P12 on v8a data; informs whether to extend holding through close. |
| 5 | **EXP-3180** Hold-to-expiration variant of exp1220 | 1d | Tests O'Donovan-Yu's most-effective simple mitigation directly on our main stream. |
| 6 | **EXP-3209** Order-imbalance TC model update | 3d | Per Doshi-Patel-Singal — tightens cost model for live deployment. |

---

## Bottom line

The 2020-2026 literature has built a robust consensus:

1. **SPX VRP has structurally collapsed post-2009** (P1, P9, P12 — three methodologies, three universes converge).
2. **The mechanism is dealer net GEX, and the mechanism is intact through 2025** (P2, P3, P4, P5, P6, P7).
3. **Residual VRP, where it survives, lives in (a) the overnight window, (b) non-SPX universes, or (c) under specific cost-mitigation playbooks** (P7, P9, P10, P11, P13).
4. **Execution alpha is the binding constraint** for any premium-harvesting strategy at the v8a margin (P13, P14, P15, P16, P18).

For v8a: the literature predicts our SPX/QQQ index-option streams should have weak alpha and our sector-ETF/commodity-ETF streams should have stronger alpha **if** their dealer GEX has not flipped the way SPX did. **EXP-3000 (this spec) is the direct test.**

---

## Sources

Listed by paper number for cross-reference.

- [P1 — Dew-Becker & Giglio 2025](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en)
- [P2 — Vasquez, Amaya, Pearson, Garcia-Ares 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405)
- [P3 — Dim, Eraker, Vilkov 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190)
- [P4 — Cboe Research](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/)
- [P5 — Regan & Xie 2025 (arXiv)](https://arxiv.org/pdf/2512.17923)
- [P6 — Ober 2024 SSRN 5032337](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5032337)
- [P7 — Terstegge 2025 FMA Derivatives](https://www.fma.org/assets/docs/Derivatives2025/Terstegge.pdf)
- [P8 — He, Kelly, Manela 2017](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2721783)
- [P9 — Heston & Todorov 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509)
- [P10 — SSE 50 ETF VRP 2024](https://www.sciencedirect.com/science/article/abs/pii/S1062940824001311)
- [P11 — Bitcoin Risk Premia (arXiv 2410.15195)](https://arxiv.org/html/2410.15195v2)
- [P12 — Papagelis & Dotsis 2025 JFM](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589)
- [P13 — O'Donovan & Yu 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [P14 — Heston, Jones, Khorram, Li, Mo 2023 (cited via P13)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [P15 — Duarte, Jones, Mo, Wang 2023 (cited via P13)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [P16 — Muravyev & Pearson 2020 (cited via P13)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [P17 — Christoffersen, Goyenko, Jacobs, Karoui 2018 (cited via P13)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [P18 — Doshi, Patel, Singal 2025](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf)
- [P19 — Mu 2025 JFM](https://onlinelibrary.wiley.com/doi/10.1002/fut.70026)
- [P20 — Cao, Jacobs, Ke 2024 AEA](https://www.aeaweb.org/conference/2024/program/paper/DFs2GZND)
