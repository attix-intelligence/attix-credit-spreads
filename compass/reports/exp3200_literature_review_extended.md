# EXP-3200 Extended Literature Review — VRP, Dealer Positioning, ETF Options Microstructure

**Date:** 2026-05-06
**Builds on:** `compass/reports/literature_review_2024_2026.md` (Apr 29, 2026), `paper_analysis_dew_becker_giglio.md`, `paper_analysis_odonovan_yu.md`
**Scope:** post-2020 VRP papers, dealer-GEX literature, ETF-vs-SPX microstructure, sector-specific VRP
**Method:** WebSearch on academic sources (SSRN, arXiv, Wiley, AEA, Cboe research, Chicago Fed). All citations verified via primary URL.

---

## 1. Key papers identified (post-2020)

### 1.1 Variance risk premium — direct evidence

**[1] Heston, Jones, Khorram, Li, Mo — "Derivative Spreads: Evidence from SPX Options"** (AEA 2024 conference paper)
*URL:* https://www.aeaweb.org/conference/2024/program/paper/DFs2GZND
- Documents bid-ask spreads on SPX options as benchmark for the cheapest end of US listed-option markets.
- Reinforces the 20.3%-of-half-spread effective-cost number used by O'Donovan-Yu (2024).
- Provides the comparison anchor for sector-ETF spreads.

**[2] Heston & Todorov — "Exploring the Variance Risk Premium Across Assets"** (SSRN 4373509, AEA 2024)
*URL:* https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509
- Twenty-asset cross-section: S&P 500, Treasuries, FX, energy, metals, grains.
- *Key finding:* "almost all assets earn negative variance risk premiums" — i.e., the seller-of-vol earns positive expected return.
- *Critical caveat:* "in the period 2006-2020, most assets had significant VRP, but the realized S&P 500 VRP was not significantly different from zero."
- This is the cross-asset confirmation of Dew-Becker-Giglio's SPX-specific finding.

**[3] Papagelis & Dotsis — "The Variance Risk Premium Over Trading and Nontrading Periods"** (Journal of Futures Markets 2025)
*URL:* https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589
- Decomposes VRP into overnight vs intraday using model-free implied-variance indices (US, Europe, Asia).
- *Key finding:* **Overnight VRP is significantly negative; intraday VRP is approximately zero or insignificant.**
- *Implication:* the VRP is paid for *overnight* (gap) risk, not intraday risk. Strategies that capture overnight premium dominate.

**[4] Dew-Becker & Giglio — "The Decline of the Variance Risk Premium"** (Chicago Fed WP 2025-17)
*URL:* https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en
- Already analysed in `paper_analysis_dew_becker_giglio.md`. Headline: SPX put alpha ≈ 0 since March 2009; mechanism is dealer net-GEX flip post-financial-crisis.

### 1.2 Dealer positioning / gamma exposure

**[5] Vasquez, Amaya, Pearson, Garcia-Ares — "0DTE Index Options and Market Volatility: How Large is Their Impact?"** (SSRN 5113405, 2025)
*URL:* https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405
- *Key finding:* despite 0DTE being ~59% of SPX volume in 2025, **net market-maker gamma hedging is de minimis (~0.2% of SPX daily liquidity)** because customer activity is extremely balanced (buyer/seller flows roughly cancel).
- *Implication:* the popular "0DTE causes intraday vol spikes" narrative is not supported empirically. The dealer-GEX *level* (Dew-Becker mechanism) matters more than 0DTE *flow*.

**[6] Cboe Research — "Volatility Insights: Much Ado About 0DTEs"** (Cboe 2024-25)
*URL:* https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/
- Industry-side confirmation of Vasquez et al.: 0DTE flow is balanced, not destabilising.

**[7] Božović — "Intraday Jumps and 0DTE Options: Pricing and Hedging Implications"** (SSRN 5223127, 2025)
*URL:* https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5223127
- 22,410 five-minute SPXW 0DTE observations.
- *Key finding:* **the implied premium for jump risk is nearly 2× the combined premia for diffusion and volatility risks** in 0DTE options.
- Implication: 0DTE is dominated by jump-risk pricing, not diffusion-vol pricing — a different premium than the VRP that v8a captures on 28DTE.

**[8] Regan & Xie — "Inferring Latent Market Forces: Gamma Exposure Patterns"** (arXiv 2512.17923)
- Already in the Apr 29 lit review. ML/LLM detection of GEX-driven patterns.

### 1.3 ETF options vs SPX microstructure

**[9] Mu — "Liquidity and Price Informativeness of Options: Evidence From Extended Trading Hours"** (Journal of Futures Markets 2025)
*URL:* https://onlinelibrary.wiley.com/doi/10.1002/fut.70026
- Documents that during extended trading hours, options market is characterized by low liquidity and decreased trading activities.
- *Implication:* execution timing matters; spreads widen materially outside RTH.

**[10] Doshi, Patel, Singal — "Risky Intraday Order Flow and Option Liquidity"** (working paper, May 2025)
*URL:* https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf
- *Key finding:* daily absolute order imbalance is the primary determinant of options bid-ask spread cross-sectionally.
- Mechanism: as end-user order pressure rises, MMs are pushed off optimal inventory → higher inventory risk → wider spreads.
- *Implication:* spread is a function of *imbalance*, not just volume. Sector-ETF options (lower volume but possibly more balanced flow) may not have the cost penalty raw bid-ask suggests.

**[11] CME Group — "Equity Index Options: Current State of Play"** (CME 2025)
*URL:* https://www.cmegroup.com/articles/2025/equity-index-options-state-of-play.html
- Compares ES, SPX, SPY order-book depth across Q2/Q3/April 2025 (high-vol vs low-vol regimes).
- Industry-side benchmark for SPX-vs-SPY-vs-ES execution quality.

### 1.4 Sector-specific VRP — what's NOT in the literature

**Honest gap report:** the WebSearch did NOT surface a single 2024-2026 academic paper that specifically tests VRP on XLF, XLI, or other sector ETFs.

What exists:
- General sector-ETF performance/return papers (SSGA, iShares, Vanguard product literature) — not VRP-relevant.
- Cross-asset VRP papers (Heston-Todorov above) — sector-level US equity is not in their 20-asset universe.
- Equity-option papers (O'Donovan-Yu, Goyal-Saretto, Zhan et al.) — single-stock options, not sector ETFs.

**Conclusion:** sector-ETF VRP is a *literature gap*. Our XLF_cs / XLI_cs streams operate in academically untested territory. This is both an opportunity (genuine alpha source if the mechanism is real) and a risk (no external corroboration).

---

## 2. Implications for the XLF/XLI edge thesis

### 2.1 Mechanistic story (synthesised from new papers)

**Why the v8a XLF_cs / XLI_cs streams plausibly retain edge:**

1. **Dew-Becker mechanism is universe-specific.** The dealer-GEX flip post-2008 was driven by SPX-options dealer balance sheets. Sector-ETF options have different end-user clienteles (sector rotators, hedge-fund factor exposure trades) and therefore *different dealer GEX dynamics*. The collapse of SPX VRP does not automatically extend to sector ETFs.

2. **Imbalance > volume for spread costs (Doshi et al. 2025).** XLF_cs / XLI_cs lower-volume ≠ higher cost. What matters is whether the order flow is *balanced*. We don't know the order-flow balance for XLF/XLI — this is testable from IronVault.

3. **No academic competition.** Heston-Todorov tested 20 assets, none of them US sector ETFs. If XLF/XLI VRP is positive, almost no academic factor-trader is harvesting it. Capacity is probably small but the edge has not been arbitraged away.

4. **Heston-Todorov's null on S&P 500 (2006-2020) is striking** — it independently confirms Dew-Becker on a different universe definition. But again: **it does NOT extend to sector ETFs.**

### 2.2 New risks identified

1. **Overnight-vs-intraday VRP decomposition (Papagelis-Dotsis 2025).** If the VRP is paid for overnight gap risk and our exit/entry timing systematically captures intraday only, we are leaving alpha. *Or worse:* if our entry/exit straddles the close-to-open gap on the wrong side, we are paying VRP rather than capturing it.

2. **Jump-risk premium dominance in short-DTE (Božović 2025).** Our exp1220 SPY-PCS at 28DTE is in the diffusion-VRP regime. We should NOT extend this to <7DTE or 0DTE assuming the same alpha mechanism — the premium structure is different.

3. **Spread widening in non-RTH (Mu 2025).** Our paper-trading and live-execution should explicitly check: are any fills happening in pre-market or after-hours? Spread widening would silently erode net Sharpe.

### 2.3 Confirmations of existing edge

1. **Heston-Todorov:** "almost all assets earn negative variance risk premiums" — the foundational economics that v8a is built on remains intact across the cross-section.
2. **Vasquez et al.:** 0DTE flow does NOT drive intraday vol (popular concern is empirically refuted). v8a's 28DTE positioning is insulated from 0DTE-cycle dynamics.
3. **Doshi et al.:** spread-as-imbalance-function explanation gives us a *measurable* TC determinant beyond simple volume — testable from IronVault chains.

---

## 3. New research questions to test

| # | Question | Why now |
|---|----------|---------|
| Q1 | Is the order-imbalance variable (Doshi et al. 2025) meaningful for XLF/XLI option spreads? | Could become a TC-prediction model; tightens our cost backtest. |
| Q2 | Does the overnight-vs-intraday VRP split (Papagelis-Dotsis 2025) appear in our ETF chains? | If YES on SPY/QQQ but NO on XLF/XLI, the v8a streams have different risk-premium structure than the academic SPX literature. |
| Q3 | What is the 2019-2024 dealer-GEX proxy for XLF/XLI? Has it flipped post-2020 the way SPX did post-2008? | Direct test of whether the Dew-Becker decline mechanism *also* hit sector ETFs (in which case XLF/XLI edge is weakening). |
| Q4 | Is the v8a XLF/XLI alpha concentrated in overnight returns? | If yes, validates Papagelis-Dotsis cross-section claim and suggests holding through close is the higher-edge window. |
| Q5 | Does our IronVault cost model capture the Doshi imbalance term, or is it volume-only? | If volume-only, we may be biased on cost per Bug-8 (smeared inputs) for ETFs with imbalanced flow. |

---

## 4. Recommended new experiments

### EXP-3201 — Sector-ETF Dealer-GEX Proxy (2 days)
**Hypothesis:** XLF/XLI dealer net-GEX has NOT flipped sign post-2020 the way SPX did post-2008; this is the structural reason v8a edge survives on sector ETFs.

**Method:**
- Reconstruct daily dealer GEX proxy from open-interest × gamma × spot (standard SpotGamma-style construction) for SPX, SPY, QQQ, XLF, XLI from 2019-2024 IronVault chains.
- Plot the four series; test for sign-change point with PELT changepoint detection.
- Test if XLF/XLI GEX magnitude correlates with subsequent v8a stream returns.

**Pre-registered metrics:** (a) sign of average daily GEX 2019-2024 per ETF, (b) Spearman correlation of GEX magnitude vs next-day stream return.

**Decision rule:** If XLF/XLI GEX is consistently negative (dealer-short-gamma) while SPX is near-zero, this is the publishable mechanism for v8a sector-stream alpha.

### EXP-3202 — Overnight vs Intraday VRP per stream (1 day)
**Hypothesis:** Per Papagelis-Dotsis (2025), VRP is concentrated overnight. v8a streams that hold through the close should outperform streams that close intraday.

**Method:**
- Decompose 28DTE PCS returns into overnight and intraday components for exp1220 / qqq_cs / xlf_cs / xli_cs.
- Compute Sharpe per component, per stream.

**Pre-registered metric:** ratio of overnight Sharpe to intraday Sharpe per stream.

**Decision rule:** If the ratio is ≥2.0 on SPY/QQQ (matching Papagelis-Dotsis) but <1.0 on XLF/XLI, our sector-stream alpha source is *different* from index-options VRP and warrants distinct mechanistic explanation.

### EXP-3203 — Order-Imbalance TC Model (3 days)
**Hypothesis:** Doshi et al. (2025) show option bid-ask spread is driven by daily absolute order imbalance. Adding this term to our cost model improves net-Sharpe predictions for live trading.

**Method:**
- Estimate order imbalance from IronVault prints (signed-volume aggregates).
- Regress observed bid-ask spread on (a) volume only and (b) volume + |imbalance|.
- Adopt the better model in our backtest TC simulator.

**Pre-registered metric:** R² of cross-sectional spread regression; out-of-sample R² on 2024 hold-out.

**Decision rule:** If imbalance-augmented model gains ≥10% R² OOS, replace the current TC model and re-run v8a Sharpe.

### EXP-3204 — Sector-ETF Order-Flow Balance Test (1 day)
**Hypothesis:** Per Vasquez et al.'s 0DTE-balance finding, the survival of XLF/XLI alpha may be because end-user flow on these is *imbalanced* (one-sided demand) while SPX is balanced — so dealers earn a one-sided risk premium.

**Method:**
- For XLF/XLI/SPY/QQQ from IronVault 2019-2024, compute monthly customer-side put/call open-interest skew.
- Compare cross-section.

**Pre-registered metric:** time-averaged |customer skew| per ETF.

**Decision rule:** If XLF/XLI skew is materially > SPY/QQQ, this corroborates the EXP-3201 mechanism.

### EXP-3205 — Non-RTH Fill Audit (0.5 day)
**Hypothesis:** Per Mu (2025), spreads widen materially outside RTH. Any v8a paper-trading or live fills outside 09:30-16:00 ET would silently erode net Sharpe.

**Method:** scan paper-trading order log for non-RTH fills; quantify spread vs RTH benchmark.

**Pre-registered metric:** fraction of fills outside RTH; basis-points cost penalty if any.

**Decision rule:** If non-RTH fills exist, gate the live executor to RTH-only.

### Priority sequencing
1. **EXP-3205** first (cheapest insurance, may surface a real bug).
2. **EXP-3201** second (highest scientific value — tests the structural-mechanism thesis directly).
3. **EXP-3202** third (validates a published-2025 finding on our data).
4. **EXP-3204** fourth (corroborates the dealer-GEX story from a different angle).
5. **EXP-3203** if cost-model upgrade matters at the AUM scale we're targeting.

---

## 5. Bottom line for the v8a research roadmap

- **Two independent post-2020 papers** (Heston-Todorov 2024, Dew-Becker-Giglio 2025) confirm SPX VRP has collapsed. The cross-asset evidence is now overwhelming.
- **Sector-ETF VRP is a literature gap.** The papers we surveyed do NOT cover XLF/XLI directly. v8a's sector streams operate in a regime that academic researchers haven't yet tested. This is both opportunity and risk.
- **The dealer-GEX-flip mechanism (Dew-Becker) is the central testable explanation** for why some assets retain VRP and others don't. EXP-3201 is the single highest-value next experiment because it directly tests whether this mechanism extends to (and explains the survival on) sector ETFs.
- **Two new decompositions** (overnight/intraday from Papagelis-Dotsis; jump/diffusion from Božović) suggest that v8a's premium source is in the diffusion-overnight quadrant — a useful reframing but not actionable until tested per stream (EXP-3202).
- **Cost modelling can be improved** (Doshi et al. order-imbalance term) but this is a refinement, not a structural change.

**One-sentence summary:** post-2020 academic literature has built a strong case for *why* SPX-VRP strategies failed; it has *not* tested the sector-ETF universe where v8a actually trades, leaving a clear research opportunity that EXP-3201 should fill first.

---

## Sources

- [Dew-Becker & Giglio — Decline of the VRP (Chicago Fed WP 2025-17)](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en)
- [Heston & Todorov — Variance Risk Premium Across Assets (SSRN 4373509)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509)
- [Papagelis & Dotsis — VRP Over Trading and Nontrading Periods (J. Futures Markets 2025)](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589)
- [Vasquez, Amaya, Pearson, Garcia-Ares — 0DTE Index Options and Market Volatility (SSRN 5113405)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405)
- [Božović — Intraday Jumps and 0DTE Options (SSRN 5223127)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5223127)
- [Cboe Research — Much Ado About 0DTEs](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/)
- [Mu — Liquidity in Extended Trading Hours (J. Futures Markets 2025)](https://onlinelibrary.wiley.com/doi/10.1002/fut.70026)
- [Doshi, Patel, Singal — Risky Intraday Order Flow and Option Liquidity (May 2025 WP)](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf)
- [Cao, Jacobs, Ke — Derivative Spreads: Evidence from SPX Options (AEA 2024)](https://www.aeaweb.org/conference/2024/program/paper/DFs2GZND)
- [CME Group — Equity Index Options State of Play 2025](https://www.cmegroup.com/articles/2025/equity-index-options-state-of-play.html)
