# Dealer GEX Literature Deep-Dive (EXP-3270)

**Date:** 2026-05-16
**Scope:** SSRN + arXiv survey of dealer gamma exposure, VRP, and SPX options literature, 2020–2026.
**Companion docs:** `research/GEX_VRP_DYNAMICS_MAY2026.md` (mechanism deep dive for XLF/XLI), `research/LIT_REVIEW_MAY2026.md` (broader 20-paper survey).
**Purpose:** Provide a focused literature map and propose 3 falsifiable hypotheses testable in our v8a / exp1220 stack.

---

## 1. Why this matters for v8a

The v8a XLF/XLI streams sell premium and depend on a positive *local* VRP surviving the post-2009 SPX VRP collapse documented in Dew-Becker-Giglio (2025) and Heston-Todorov (2024). The dealer-GEX channel is the dominant proposed *mechanism* for that collapse. If we can characterize the mechanism rigorously enough to (a) measure when it binds on sector ETFs and (b) detect regime shifts in real time, we have an alpha signal AND a kill-switch.

---

## 2. Canonical paper map

### 2.1 Foundational theory (pre-2020 anchors)

| Paper | Contribution | Why it still matters |
|-------|-------------|----------------------|
| Gârleanu, Pedersen, Poteshman (RFS 2009) "Demand-Based Option Pricing" | Formal model: option demand pressure × variance of *unhedgeable* component drives prices away from no-arbitrage benchmark. End-user demand identified from dealer position data. | Provides the structural microfoundation everyone now cites for "dealer hedging matters." Predicts cross-section: dealer compensation ∝ variance of residual after delta-hedge. |
| Ni, Pearson, Poteshman, White (RFS 2021) "Does Option Trading Have a Pervasive Impact on Underlying Stock Prices?" | Empirical: option MM hedge rebalancing affects underlying return volatility and tail probability via a *non-informational* channel. Pinning effects ~16.5 bps avg at expiry. | Demonstrates that the GEX → underlying-price feedback is measurable and *causal*. |
| Bollerslev & Todorov (J. Finance 2011, JFE 2015, JFE 2019) VRP papers | Decompose VRP into continuous + jump components; show jump-tail VRP is the persistent predictor of equity returns at 3–6 month horizons. | Tells us *which* slice of VRP we should be selling — the jump-tail premium, not the diffusive component. Validates short-dated put-credit premium-seller designs. |

### 2.2 Modern dealer GEX literature (2020–2026)

| Paper | Year | Setting | Key finding |
|-------|------|---------|-------------|
| Barbon & Buraschi "Gamma Fragility" (SSRN 3725454) | 2020 (updated 2022) | Single-stock options, US | Aggregate dealer gamma imbalance × underlying illiquidity → intraday momentum (negative GEX) / reversal (positive GEX). Effect strongest in least-liquid names. |
| Barbon, Beckmeyer, Buraschi, Moerke "Liquidity Provision to Leveraged ETFs and Equity Options Rebalancing Flows" (SSRN 3925725) | 2021 | Leveraged ETFs + options | EOD rebalancing flow is large enough to move underlying; dealer hedging is one of two main channels. Methodology: estimate dealer net position from open interest × OPRA prints + parity. |
| Gayda, Gruenthaler, Harren "Option Liquidity and Gamma Imbalances" (SSRN 4138512) | 2022 | SPX options | Dealer inventory risk shapes liquidity (bid-ask, depth) in SPX — empirically, gamma imbalance is a first-order determinant of option spreads, not just underlying volatility. |
| Dim, Eraker, Vilkov "0DTEs: Trading, Gamma Risk and Volatility Propagation" (SSRN 4692190) | 2023 | SPX 0DTEs | **Counter-intuitive**: high 0DTE open-interest gamma does NOT propagate volatility. Dealer MM net gamma on 0DTEs is positive (long-gamma stabilizer), negatively correlated with future intraday vol. |
| Vilkov "0DTE Trading Rules" (SSRN 4641356) | 2023 | SPX 0DTEs | Practitioner-ready strategy rules built on the same dealer-gamma signal. |
| CBOE / Adams, Dim, Eraker, Fontaine, Ornthanalai, Vilkov "Do S&P500 Options Increase Market Volatility? Evidence from 0DTEs" (SSRN 5641974, CBOE working paper) | 2024 | SPX/SPXW full trade-level | Reconstructs aggregate OMM net position trade-by-trade; estimates OMM gamma; finds no positive 0DTE → SPX-vol link. Methodology is the gold standard for academic GEX reconstruction. |
| Dew-Becker & Giglio "The Variance Risk Premium and Hedging Pressure" (working paper, 2025) | 2025 | SPX index options | Synthetic-vs-traded option decomposition: post-2009, traded-option alpha collapsed to synthetic alpha ≈ 0. Attributed to dealer net GEX flipping from short → ~flat under Dodd-Frank / Basel III / vol-selling ETP rise. |
| Heston & Todorov (J. Finance 2024) | 2024 | 20-asset cross-section | SPX VRP not statistically distinct from zero 2006-2020. Independent corroboration of DBG. |
| Terstegge (SSRN, 2025) | 2025 | SPX, intraday | Residual VRP concentrated *overnight* — when dealer hedging constraints bind hardest because they cannot reset deltas. |
| arXiv:2407.13908 "Construction and Hedging of Equity Index Options Portfolios" | 2024 | SPX index options | Practical dealer-side hedging framework; useful for benchmarking what a realistic dealer P&L looks like. |
| arXiv:2512.17923 "Inferring Latent Market Forces: LLM Detection of GEX Patterns" | 2025 | SPY 2024 full year | Reports 95.6% of 2024 trading days had aggregate SPY GEX < −$2B (mean −$19.87B). **Implication**: structurally short-gamma regime persisted in 2024 on SPY despite SPX VRP collapse — a potential disconnect worth investigating. |
| arXiv:2512.12420 "Deep Hedging with Reinforcement Learning" | 2025 | SPY options + SPY underlying | RL framework for dealer-side delta hedging under realistic costs/limits. Methodology, not finding. |
| Regan & Xie (working paper, 2025) | 2025 | SPX aggregate | Aggregate dealer GEX near zero by 2020 — consistent with DBG. |
| Chen et al. (J. Futures Markets, 2025) "Market Maker or Informed Trader: SSE 50 ETF" | 2025 | China SSE 50 ETF options | Positive VRP documented in a market without DBG-style dealer rebalancing — useful international comparison. |

### 2.3 Citadel / industry-side commentary

| Source | Take |
|--------|------|
| Citadel Securities "Flows and Fundamentals" (2024) | Dealer-flow microstructure dominates intraday; fundamentals dominate at horizons > a few days. Indirect confirmation that the GEX channel is real but short-lived. |

---

## 3. Quantitative datasets

### 3.1 SqueezeMetrics (commercial, daily, free historical sample available)
- **Products**: GEX (dealer gamma exposure, SPX), DIX (dark-pool buy/sell ratio).
- **Methodology** (per their white paper): infer dealer position by assuming customer flow is opposite of MM flow; aggregate OI × strike × sign(call/put). Sign convention: MMs assumed short calls / long puts to retail (debatable — see §5).
- **Endpoints**: `squeezemetrics.com/monitor/dix` (daily CSV).
- **Caveats**: Methodology is proprietary; published sign convention has been challenged (notably by Dim-Eraker-Vilkov who reconstruct MM net positions trade-by-trade and find net *long* gamma on 0DTEs, opposite to SqueezeMetrics' baseline assumption).

### 3.2 SpotGamma (commercial, intraday)
- **Products**: Gamma flip levels, vanna/charm zones, hedging impact estimators.
- **Methodology**: position inference from OPRA + heuristic call/put sign assignment, calibrated to dealer survey data (per their public docs).
- **Caveats**: Same identification problem — sign of dealer net position is *not directly observable*; must be inferred. Their levels are reverse-engineered, not measured.

### 3.3 Academic-grade reconstructions (gold standard, not buyable)
- **CBOE OMM dataset** (Adams, Dim et al. 2024) — full trade-level OMM accounts for SPX/SPXW; only available to authors / CBOE-affiliated researchers.
- **OptionMetrics IvyDB + OPRA tape**: enables independent reconstruction; this is the closest a non-CBOE researcher can get. Cost: ~$tens of thousands/year for institutional license.

### 3.4 What we can realistically build
- **Tier 1 (free)**: CBOE OI snapshots + closing IV (CBOE DataShop sample) → daily GEX proxy using GPP-style sign assumption. Coarse but usable.
- **Tier 2 ($$$)**: OPRA L1 trades + IvyDB → reconstruct customer-vs-MM flow using Lee-Ready-style trade-classification adapted to options.
- **Tier 3 ($$$$)**: Direct CBOE/OPRA L2 + Algoseek match — academic gold standard.

---

## 4. Methodology synthesis — how the best papers actually measure dealer GEX

1. **Sign-aware trade classification** (Adams-Dim 2024, Gayda et al. 2022): classify every option print as customer-buy or customer-sell using NBBO context (akin to equity Lee-Ready). MM net position = − (cumulative customer net).
2. **Open-interest baseline + flow updates** (Barbon-Buraschi 2020): start each day with prior MM net OI, add intraday delta from classified prints, mark-to-market gamma using BSM with smile-fitted IV.
3. **Gamma aggregation**: ∑ over strikes K of (MM_net_position_K × Γ_K × spot² × 0.01) → "dollar gamma per 1% move." Units matter — SqueezeMetrics quotes "$GEX", DBG uses dimensionless gamma in $/% move; these differ by spot² scaling.
4. **Decomposition into channels**: short-dated vs long-dated; 0DTE vs non-0DTE; index vs single-stock — because each maps to different hedging constraints (Terstegge 2025 shows overnight is special).

---

## 5. Critical open questions in the literature

1. **Sign-of-customer-flow identification**. SqueezeMetrics assumes one sign convention; Dim-Eraker-Vilkov measure the opposite for 0DTEs. Which retail-vs-institutional split is correct *depends on the product and the period*. No universal answer.
2. **SPY-vs-SPX disconnect**. arXiv:2512.17923 reports persistent short-gamma on SPY 2024; DBG/Heston-Todorov report near-zero VRP on SPX. If both are correct, the SPY ETF options market and the SPX index options market may have *different* dealer GEX regimes despite tracking the same underlying. Mechanism: different end-user mixes (SPY = retail-heavy, SPX = institutional-heavy). **This is the most actionable gap for us.**
3. **Sector ETFs are unstudied**. No 2020-2026 paper rigorously reconstructs dealer GEX for XLF, XLI, XLE, etc. Direct relevance to v8a.
4. **Causality vs correlation in GEX → realized vol**. Almost all the "GEX predicts vol" results are correlational. Barbon-Buraschi (2020) is the cleanest causal design (using illiquidity interaction as an instrument-flavored test); few have replicated.

---

## 6. Three testable hypotheses for v8a / exp1220

Each hypothesis is (i) anchored to a specific paper, (ii) actionable with data we can plausibly source, and (iii) falsifiable with a pre-registered statistical test.

### H1 — "SPY-SPX GEX disconnect implies retail-heavy products retain a tradeable short-gamma VRP"
**Anchor**: arXiv:2512.17923 (SPY 95.6% negative-GEX 2024) vs Dew-Becker-Giglio 2025 (SPX VRP ≈ 0 post-2009).
**Claim**: Conditional on the same underlying basket (SPX vs SPY), products with a higher retail share in customer flow exhibit a more negative dealer net GEX and a measurably positive VRP.
**Test**: Compute IV–RV spread for SPY 30-DTE ATM vs SPX 30-DTE ATM, daily 2020–2026. Regress (IV − RV) on a proxy for retail share (e.g., SPY share-of-notional vs SPX) controlling for VIX. Pre-registered prediction: β_retail-share > 0, t > 2.
**Decision rule**: If H1 confirmed → consider migrating part of v8a premium-selling from SPX-tracking baskets to retail-heavy ETF analogues (SPY, sector ETFs with retail dominance).

### H2 — "Sector-ETF dealer GEX is materially more negative than SPX, and predicts forward 5-day realized vol"
**Anchor**: Barbon-Buraschi 2020 (illiquidity × gamma → momentum); §2.2 literature gap on sector ETFs.
**Claim**: Daily proxy GEX (built from CBOE OI snapshots + GPP-style sign rule) on XLF/XLI/XLE has a more-negative time-series mean than SPX over 2022–2026, AND its negative tail (most-short-gamma days) predicts above-average 5-day realized vol on the sector ETF.
**Test**: (a) two-sample t-test on daily GEX means XLF − SPX < 0; (b) panel regression RV_{t,t+5} = α + β · 1{GEX_t < 10th-pctile} + γ · VIX_t + ε on sector ETFs.
**Decision rule**: If both legs confirmed → v8a should *avoid* selling premium on low-GEX days (downside vol underpriced) and *upsize* on high-GEX days. Direct gating logic for the live system.

### H3 — "Overnight-only short put-credit spreads on SPX retain VRP that intraday strategies cannot harvest"
**Anchor**: Terstegge 2025 (overnight is where residual SPX VRP lives because dealer hedging constraints bind hardest).
**Claim**: A pre-registered SPX put-credit-spread strategy entered at 15:55 ET and exited at 09:35 ET next morning produces a Sharpe ≥ 0.7 net of transaction costs over 2023–2026, while an equivalent intraday-only variant (entered 10:00, exited 15:50 same day) does not.
**Test**: Backtest both legs on IronVault SPX 0–1 DTE put-credit-spread data; compare Sharpe via Ledoit-Wolf bootstrap; pre-registered SR_overnight − SR_intraday > 0.3.
**Decision rule**: If confirmed → exp1220 SPX leg should be reconfigured to overnight-only entry; if rejected → DBG's null result extends to overnight, and we should de-emphasize SPX premium-selling entirely (keep XLF/XLI focus).

---

## 7. Recommended next steps

1. **Data sourcing**: Pull CBOE OI history (free DataShop sample) for SPX, SPY, XLF, XLI, XLE; build GPP-style daily GEX series. (Build effort: ~1 day; cost: $0.)
2. **Optional Tier-2 spend**: Quote OptionMetrics IvyDB for trade-classified data if H1/H2 produce ambiguous results with OI-only proxy.
3. **Pre-register** H1/H2/H3 hypotheses with explicit cutoffs *before* running tests, to avoid the same selection-bias risk flagged in `GEX_VRP_DYNAMICS_MAY2026.md` §3.4.
4. **Single-paper deep reads**: Adams-Dim 2024 (CBOE) for methodology; Dew-Becker-Giglio 2025 for the synthetic-traded decomposition; Terstegge 2025 for the overnight channel — these three are the highest-leverage reads.

---

## Sources

- [0DTEs: Trading, Gamma Risk and Volatility Propagation — Dim, Eraker, Vilkov (SSRN 4692190)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190)
- [Option Liquidity and Gamma Imbalances — Gayda, Gruenthaler, Harren (SSRN 4138512)](https://papers.ssrn.com/sol3/Delivery.cfm/4138512.pdf?abstractid=4138512)
- [Do S&P500 Options Increase Market Volatility? Evidence from 0DTEs — Adams, Dim, Eraker, Fontaine, Ornthanalai, Vilkov (SSRN 5641974)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5641974)
- [0DTE Index Options and Market Volatility (CBOE working paper)](https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf)
- [Gamma Fragility — Barbon, Buraschi (SSRN 3725454)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454)
- [Liquidity Provision to Leveraged ETFs — Barbon, Beckmeyer, Buraschi, Moerke (SSRN 3925725)](https://ssrn.com/abstract=3925725)
- [Demand-Based Option Pricing — Gârleanu, Pedersen, Poteshman (RFS 2009)](https://academic.oup.com/rfs/article-abstract/22/10/4259/1590158)
- [Does Option Trading Have a Pervasive Impact on Underlying Stock Prices? — Ni, Pearson, Poteshman, White (SSRN 2867461)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2867461)
- [Stock Price Clustering on Option Expiration Dates — Ni, Pearson, Poteshman (SSRN 519044)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=519044)
- [Tail Risk Premia and Return Predictability — Bollerslev, Todorov](https://www.kellogg.northwestern.edu/faculty/todorov/htm/papers/tvt_pred.pdf)
- [Variance Risk Premium Dynamics: The Role of Jumps — Bollerslev, Todorov](https://www.kellogg.northwestern.edu/faculty/todorov/htm/papers/vrpd.pdf)
- [Expected Stock Returns and Variance Risk Premia — Bollerslev (RFS 2009)](https://public.econ.duke.edu/~boller/Published_Papers/rfs_09.pdf)
- [Inferring Latent Market Forces: LLM Detection of GEX Patterns (arXiv:2512.17923)](https://arxiv.org/html/2512.17923v2)
- [Construction and Hedging of Equity Index Options Portfolios (arXiv:2407.13908)](https://arxiv.org/html/2407.13908v1)
- [Deep Hedging with Reinforcement Learning (arXiv:2512.12420)](https://arxiv.org/abs/2512.12420)
- [SqueezeMetrics — DIX/GEX monitor](https://squeezemetrics.com/monitor/dix)
- [SqueezeMetrics GEX white paper](https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf)
- [SpotGamma — Gamma Exposure (GEX)](https://spotgamma.com/gamma-exposure-gex/)
- [Flows and Fundamentals — Citadel Securities](https://www.citadelsecurities.com/news-and-insights/flows-and-fundamentals/)
- [0DTE Trading Rules — Vilkov (SSRN 4641356)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356)
- [Market Maker or Informed Trader: SSE 50 ETF — Chen et al. (J. Futures Markets 2025)](https://onlinelibrary.wiley.com/doi/abs/10.1002/fut.70038)
