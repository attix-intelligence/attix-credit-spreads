# Literature Review 2025-2026 — Extending and Contradicting Dew-Becker & Giglio

**Date:** 2026-05-10
**Centring paper:** Dew-Becker & Giglio (2025), "The Decline of the Variance Risk Premium: Evidence from Traded and Synthetic Options" (Chicago Fed WP 2025-17 / SSRN 5525882).
**Question:** Which 2025-2026 papers *extend* DBG's mechanism, which *contradict* its findings, and what does this imply for v8a?
**Companion docs:** `compass/reports/paper_analysis_dew_becker_giglio.md`, `paper_analysis_odonovan_yu.md`, `pdf_analysis_dew_becker_odonovan.md`, `literature_review_2024_2026.md`, `exp3200_literature_review_extended.md`, `exp3300_literature_review_may2026.md`. **This document is the consolidated DBG-centric synthesis** — it does not re-cover material in those files except to cross-reference.

---

## 1. The DBG claim, in one paragraph

SPX long-put alpha is statistically indistinguishable from zero post-March 2009. The mechanism is a flip in dealer net gamma exposure (GEX) — pre-2008 dealers were structurally short gamma and demanded a premium to warehouse it; post-2008 reforms and the rise of vol-selling vehicles flipped the dealer balance sheet to ~zero or positive net GEX. Synthetic options (dynamic delta-replication portfolios) are the benchmark — DBG show synthetic options *never* earned negative alpha, whereas traded options used to earn large negative alpha and now earn zero. The wedge between traded and synthetic options *is* the VRP, and that wedge has collapsed.

---

## 2. Papers that EXTEND DBG (consistent with mechanism)

### 2.1 Heston & Todorov — VRP Across 20 Asset Classes (SSRN 4373509, AEA 2024)
**Core finding:** Across 20 futures-option markets, *almost all* assets earn negative VRP (i.e., short-vol earns positive expected return). **BUT:** "in the period 2006-2020, the realized S&P 500 variance risk premium was not significantly different from zero."

**Why this extends DBG:** Independent confirmation of DBG's SPX null on a different universe and methodology. Heston-Todorov use a different VRP construction (model-free tradable replication) and reach the same SPX conclusion. Together with DBG, this is a *two-paper, two-methodology* consensus that SPX VRP is gone.

**Cross-asset implication:** The collapse is SPX-specific, not universal. Other asset classes (commodities, FX, Treasuries) still earn negative VRP. This is the empirical anchor for the claim that v8a's sector-ETF and commodity-ETF streams may operate in the un-collapsed part of the cross-section.

### 2.2 Papagelis & Dotsis — VRP Trading vs Non-Trading Periods (J. Futures Markets 2025)
**Core finding:** VRP is significantly negative *overnight*, approximately zero *intraday*, in US/Europe/Asia indices.

**Why this extends DBG:** Compatible with DBG's cumulative-zero-since-2009 finding *if* the residual VRP is concentrated in overnight (gap-risk) windows. DBG's monthly buy-and-hold (3rd Friday to 3rd Friday) integrates over both periods and finds zero on average. Papagelis-Dotsis explain *where* in the holding period any residual premium might still hide — it's the gap, not the day.

**Implication:** Short-vol strategies that hold *through the overnight close* may capture more residual VRP than strategies that close intraday.

### 2.3 Vasquez, Amaya, Pearson, Garcia-Ares — 0DTE Market Impact (SSRN 5113405, 2025)
**Core finding:** Despite 0DTE being ~59% of SPX volume in 2025, net market-maker gamma hedging is ~0.2% of SPX daily liquidity because customer 0DTE flows are nearly balanced (buyers ≈ sellers).

**Why this extends DBG:** The DBG mechanism rests on dealer net-GEX *level*. Vasquez et al. show that the 0DTE volume explosion has NOT shifted dealer net GEX meaningfully (because flows are balanced). So the post-2008 GEX flip that DBG documents has *not been undone* by the 0DTE phenomenon. The DBG mechanism is intact through 2025.

### 2.4 Cao, Jacobs, Ke — Derivative Spreads on SPX Options (AEA 2024)
**Core finding:** Documents bid-ask spread structure on SPX options; reinforces the 20.3%-of-half-spread effective-cost benchmark used in O'Donovan-Yu.

**Why this extends DBG:** Spreads on the SPX option universe have not collapsed alongside VRP — meaning the *cost* of harvesting a (now-zero) premium has stayed constant. This makes net-of-cost SPX-options strategies materially worse than gross-of-cost suggests, sharpening DBG's negative conclusion for the SPX universe specifically.

---

## 3. Papers that CONTRADICT or QUALIFY DBG

### 3.1 Bitcoin VRP — arXiv 2410.15195 (Oct 2024)
**Core finding:** BTC variance risk premium is *positive and large* during low-vol regimes (2024 base case), flips/compresses in stress (Mar 2020, May 2022). Jump premium dominates VRP at short DTEs.

**Why this contradicts DBG:** Crypto options are the *one asset class* surveyed in 2024-2026 literature with documented robust positive VRP post-2020. The DBG mechanism (US dealer balance-sheet reform → GEX flip) does not apply to Deribit, where market structure, end-user composition, and regulatory environment differ.

**Qualification, not refutation:** This *bounds* DBG to the dealer-intermediated US-listed-options universe rather than refuting the mechanism. v8a-implication: crypto is a candidate new universe but with operational (data, regulatory, infrastructure) costs.

### 3.2 Sector-Specific VRP — *literature gap*
**Honest gap report:** No 2024-2026 academic paper specifically tests VRP on XLF, XLI, or other US sector ETFs.

**Why this matters for the DBG claim:** DBG's universe is SPX index options ONLY. The paper *cannot* contradict — but also cannot confirm — that the VRP collapse extends to sector ETFs. This is the *most important open question* for v8a's research roadmap because four of our eight streams trade sector-ETF options.

### 3.3 Goyal & Saretto (2024) — Long-short option strategies post-cost
Cited indirectly via O'Donovan-Yu (2024). Goyal-Saretto find significant returns *after* transaction costs for long-short portfolios formed on illiquidity, suggesting that *some* characteristic-sorted option strategies still pay net of cost — qualifying DBG's "all-strategies-zero" headline by reminding us that DBG tested *long*-options only (not long-short, not short-vol).

**Why this qualifies DBG:** DBG's universe is *buying* options (long puts, long calls) at ATM-to-10%-OTM. v8a *sells* premium. Mechanically, every unit of zero alpha to a put-buyer is zero alpha to the put-seller — but the *risk profile* and the *implementation costs* differ. The seller side has not been independently shown to be zero net-alpha in the DBG sample.

---

## 4. Papers on credit-spread-style strategies (the v8a structure)

The 2024-2026 academic literature on *credit-spread* multi-leg structures (vertical spreads, iron condors) is thin — most academic work uses single-leg or delta-hedged single-leg. Practical credit-spread backtests live in industry/blog literature (Option Alpha, Data Driven Options, alphacrunching) which have known methodological weaknesses (look-ahead, survivorship, unrealistic fills — the same flaws Duarte et al. 2023 and O'Donovan-Yu 2024 expose in single-leg academic work).

**Implication:** v8a's credit-spread streams are in a regime with weak academic comparators. This is both a publication opportunity and a risk (no peer-reviewed corroboration of mechanism).

---

## 5. Cross-paper synthesis — three convergent findings

| Finding | Papers | Strength of evidence |
|---------|--------|----------------------|
| SPX VRP is approximately zero post-2009/2020 | DBG 2025; Heston-Todorov 2024 | **Strong** — two methodologies, two universes |
| Mechanism is dealer net-GEX level, intact through 2025 | DBG 2025; Vasquez et al. 2025 | **Strong** — direct + via-negativa evidence |
| Residual VRP, where it survives, is overnight or in non-SPX universes | Papagelis-Dotsis 2025; arXiv 2410.15195 | **Moderate** — fewer corroborating papers |
| Sector-ETF VRP is unstudied | (gap) | **Untested** — opportunity AND risk |

---

## 6. Implications for v8a strategy

### 6.1 What is reinforced
- **exp1220 (SPY 28DTE PCS) and qqq_cs survival is mechanistically suspicious** under DBG. These two streams trade in DBG's universe, and DBG's null result applies. EXP-3150 already confirmed v8a edge survives post-2020 *empirically* — but the academic literature now provides strong reasons to expect this edge to be small or transient.
- **The v5_hedge sleeve is structurally validated.** O'Donovan-Yu's "0.9 units short SPX index option" mitigation prescription is approximately what v5_hedge does. This is the most-defended piece of v8a's design.

### 6.2 What is challenged
- The premium SPY/QQQ exp1220/qqq_cs streams generate may be a function of (a) early exit before the 57%-spread cliff, (b) selling rather than buying, or (c) the *dollar-vega* size and tail-protection structure rather than a pure VRP claim. Each is testable but currently not isolated in our backtests.
- **Sector-ETF stream survival lacks academic corroboration.** XLF/XLI streams are "post-2020-confirmed-empirically, mechanistically un-explained." We should not assume the DBG-style decline cannot also hit sector ETFs over the next 3-5 years.

### 6.3 What is opened
- **Crypto options** as a candidate universe (arXiv 2410.15195). High infrastructure cost, but the only documented surviving-VRP universe.
- **Overnight-vs-intraday VRP decomposition** as an attribution tool (Papagelis-Dotsis 2025).
- **Order-imbalance** as a TC-model variable (Doshi-Patel-Singal 2025, already covered in `exp3200_literature_review_extended.md`).

---

## 7. Actionable insights — the four high-value experiments

| # | EXP | Effort | Why now |
|---|-----|--------|---------|
| 1 | **EXP-3201** Sector-ETF dealer-GEX proxy reconstruction (XLF/XLI/SPY/QQQ, 2019-2024) | 2 days | Only direct test of whether the DBG mechanism extends to v8a's sector universe. |
| 2 | **EXP-3210** Synthetic-option benchmark per v8a stream (DBG methodology) | 4-5 days | DBG's method directly applied to our universe. If our gross alpha is on the synthetic-options side of the wedge, it survives by construction; if on the residual traded-options side, it is at risk. |
| 3 | **EXP-3202** Overnight vs intraday VRP attribution per v8a stream | 1 day | Cheap, directly testable, validates Papagelis-Dotsis on our data. |
| 4 | **EXP-3211** Test the DBG cumulative-alpha window on our streams | 1 day | Compute v8a stream cumulative gross alpha 2009-2024 in the DBG style. If our SPX-cousin streams (exp1220, qqq_cs) show DBG's flat cumulative line, our edge there is mainly post-cost-mitigation, not VRP. |

Pre-existing experiments from prior reviews (EXP-3000 dealer-GEX gate, EXP-3151 per-stream attribution post-2020, EXP-3155 look-ahead audit, EXP-3180 hold-to-maturity, EXP-3303 expanded regime-detector features) remain valid; they are documented in `paper_analysis_dew_becker_giglio.md`, `paper_analysis_odonovan_yu.md`, and `exp3300_literature_review_may2026.md` respectively.

### Suggested sequencing
1. **EXP-3211** first (1 day, cheapest, tells us *whether* our SPX-cousin streams already show DBG-style decay).
2. **EXP-3201** second (2 days, *the* mechanism test for sector-ETFs).
3. **EXP-3202** third (1 day, attribution).
4. **EXP-3210** only if 3211 + 3201 raise red flags (4-5 days, the full DBG methodology applied to v8a).

---

## 8. Bottom line

**On the question "Does post-2023 literature extend or contradict DBG?"**
- *Extends:* Heston-Todorov, Papagelis-Dotsis, Vasquez et al., Cao-Jacobs-Ke (4 papers, all consistent with DBG mechanism).
- *Qualifies:* arXiv 2410.15195 (crypto — DBG mechanism is universe-bounded, not universal); Goyal-Saretto 2024 (long-short post-cost partial survival).
- *Does not yet test:* sector-ETF universe (where four v8a streams operate).

**On the question "What does this imply for v8a?"**
The literature reinforces the mechanism by which the *index-options* portion of v8a's universe should have weak edge. Empirical post-2020 survival (EXP-3150) is consistent with v8a having found mitigation/structural advantages (cheap-universe ETF, sell-side, vertical-structure self-hedge, v5_hedge sleeve) rather than a pure VRP claim. The single highest-value next experiment is **EXP-3211** (DBG-style cumulative-alpha check on v8a streams) — 1 day of work, directly maps the DBG result onto our universe.

---

## Sources

- [Dew-Becker & Giglio — Decline of the VRP (Chicago Fed WP 2025-17)](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en)
- [Dew-Becker & Giglio — SSRN 5525882](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5525882)
- [Dew-Becker & Giglio (2023) — Recent Developments in Financial Risk and the Real Economy (SSRN 4638212)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4638212)
- [Heston & Todorov — VRP Across Assets (SSRN 4373509)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509)
- [Papagelis & Dotsis — VRP Over Trading and Nontrading Periods (J. Futures Markets 2025)](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589)
- [Vasquez et al. — 0DTE Index Options and Market Volatility (SSRN 5113405)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405)
- [Cao, Jacobs, Ke — Derivative Spreads: SPX Options (AEA 2024)](https://www.aeaweb.org/conference/2024/program/paper/DFs2GZND)
- [Risk Premia in the Bitcoin Market (arXiv 2410.15195)](https://arxiv.org/html/2410.15195v2)
- [O'Donovan & Yu — Transaction Costs and Cost Mitigation (SSRN 4806038)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
- [He, Kelly, Manela — Intermediary Asset Pricing: Many Asset Classes](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2721783)
- [Doshi, Patel, Singal — Risky Intraday Order Flow and Option Liquidity (May 2025 WP)](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf)
