# Dealer GEX Mechanism and VRP Dynamics — Sector ETF vs SPX

**Date:** 2026-05-15
**Scope:** focused review of the dealer-GEX mechanism in the VRP-decline literature, with explicit application to v8a's XLF/XLI streams vs exp1220/qqq_cs.
**Goal:** validate (or falsify) the thesis that XLF/XLI edge survives the dealer-GEX regime change that killed SPX VRP.
**Companion files:** for the broader 20-paper systematic review see `research/LIT_REVIEW_MAY2026.md`; for paper-level deep reads see `compass/reports/paper_analysis_dew_becker_giglio.md` and `paper_analysis_odonovan_yu.md`. **This document focuses *only* on the GEX-mechanism question.**

---

## 1. The dealer GEX mechanism — what the literature says

### 1.1 The core model (Dew-Becker & Giglio 2025; building on He-Kelly-Manela 2017)

Variance risk premium = compensation dealers demand for warehousing variance risk. Mathematically:

> *VRP ≈ −λ · σ²_dealer-net-gamma-exposure*

where λ is the market-makers' risk-aversion parameter and dealer-net-GEX is the residual position MMs hold after customer flow. **When dealers are structurally short gamma** (negative net GEX), they must hedge with directional underlying trades — buying high, selling low — which is costly. They demand compensation = a positive VRP for the buyer of insurance, equivalently negative expected returns on long-vol positions. **When dealers are flat or long gamma** (zero/positive net GEX), they require no premium, and the wedge between implied and realised vol collapses.

### 1.2 The post-2008 flip

Four converging forces moved dealer net GEX from structurally short → flat or positive on SPX:

| Force | Effect on dealer net GEX |
|-------|--------------------------|
| Dodd-Frank, Basel III restrict bank derivative inventory | Dealers reduced *long* delta-1 risk; smaller balance sheets to warehouse short-gamma positions |
| Rise of vol-selling ETPs (XIV, SVXY, covered-call ETFs) | Institutional vol sellers absorb short-gamma exposure that dealers used to hold |
| Growth of put-buying for systematic tail hedging | Customer flow on puts moved from "always one-sided buying" to "more two-sided" |
| 0DTE explosion 2021+ | Customer 0DTE flow is balanced (P2 Vasquez et al. 2025); net adds ~0 to dealer GEX |

Net effect by 2009: dealer SPX net GEX ≈ 0; by 2020: clearly positive on 0DTEs (Dim-Eraker-Vilkov), aggregate near-zero (Regan-Xie 2025).

### 1.3 Empirical signatures of the flip

DBG's "synthetic-minus-traded option" decomposition is the cleanest test. Synthetic options always pay zero alpha by construction (dynamic delta replication). Traded options used to pay −1 to −2% per month (large negative alpha = positive premium to dealer). **Post-2009, traded option alpha collapsed to ≈ synthetic option alpha = 0.** The wedge that *is* the VRP closed.

Independent corroboration:
- Heston & Todorov (2024) 20-asset cross-section: SPX VRP not significantly different from zero 2006-2020.
- Dim, Eraker, Vilkov (2023): MM net gamma on 0DTEs positive, negatively correlated with future intraday vol — direct signature of dealers being long-gamma stabilisers.
- Terstegge (2025): residual VRP concentrated overnight when hedging constraints bind hardest.

---

## 2. Why the mechanism might NOT apply to XLF/XLI

The DBG mechanism is universe-specific. Four channel-level reasons sector ETFs may retain a meaningfully negative dealer net GEX (and therefore meaningfully positive VRP to harvest by selling premium):

### 2.1 Channel A — End-user composition differs
SPX option end-users are dominated by:
- Institutional vol sellers (pension overwriting, vol-target funds)
- Systematic short-vol ETPs
- Tail-hedge buyers

These flows are largely balanced and have scaled with dealer balance sheets.

XLF/XLI option end-users are dominated by:
- Sector-rotation hedge funds (one-sided, regime-dependent demand)
- Factor strategy hedging (long-financials hedges, sector-pair trades)
- Retail directional speculation
- Relatively *no* large dedicated vol-selling ETP

If sector-ETF flow is more *one-sided* (sector-rotation typically generates concentrated put-buying around macroeconomic data releases), dealers are pushed into structural short-gamma in those names without an offsetting natural supply of vol-selling. **The DBG flip is structurally harder to occur in sector ETFs.**

### 2.2 Channel B — Liquidity-tier-specific dealer balance sheet treatment
Post-2008 regulatory reforms hit dealer capacity to hold *the biggest* derivative inventories (SPX, where size constraints actually bind). Sector-ETF option inventories are small enough that the same regulations don't bind — dealers can still warehouse them, but at the limit of their risk appetite. This means a smaller "dealer capacity buffer" → faster premium demand response when imbalance hits → larger residual VRP.

### 2.3 Channel C — No vol-selling ETP supply
There is no equivalent of XIV/SVXY/SPX-covered-call ETF for XLF or XLI. The largest vol-selling vehicles overlapping with sectors (XYLD, JEPI) are still SPX/total-market based. **No institutional supply of vol-selling means dealers cannot offload their absorbed short-gamma the way they can on SPX.**

### 2.4 Channel D — The literature has not tested it
No 2024-2026 academic paper directly reconstructs dealer GEX for US sector ETFs. The closest is SSE 50 ETF (China — P10) where positive VRP is documented. This is *literature gap*, which means:
- (a) If the mechanism applies, no one is competing to arbitrage the premium → larger surviving VRP.
- (b) If the mechanism *doesn't* apply, no one has falsified it → we should not assume our edge is mechanically explained.

---

## 3. Why the mechanism MIGHT also kill XLF/XLI edge

Honest counter-arguments — failure modes for our XLF/XLI thesis:

### 3.1 Spillover from SPX hedging
Dealers running sector-ETF books often hedge basis risk against SPX index futures. If dealer GEX on the *aggregate book* is flat, individual sector-ETF GEX may *appear* short but the dealer is net hedged via SPX. End-investor doesn't see the higher-order hedge → premium is not extracted → VRP appears smaller than the local GEX would suggest.

### 3.2 Sector-rotation flows can flip
The "one-sided sector demand" argument (Channel A) assumes a stable institutional flow. If the flow flips (e.g., financials become a heavily-held sector by vol-targeting strategies), dealer GEX flips with it. We don't have time-series visibility into sector-ETF dealer GEX, so we can't see this risk forming.

### 3.3 0DTE on sector ETFs is now nontrivial
0DTE expirations exist on XLF/XLI since 2024. Even if absolute volume is small, the relative growth pattern suggests a 2025-2026 increase. P2/P3 mechanics may eventually replicate on sector ETFs.

### 3.4 Selection-bias risk on our empirical evidence
EXP-3150 showed v8a survives post-2020 in backtest. But EXP-3150 is a *2020-2024 in-sample window* with respect to the DBG-flip-on-sectors hypothesis. If the flip happens *now* (2025-2026 onwards), our backtest evidence wouldn't catch it. Live performance is the only true test.

---

## 4. Verdict — three pillars of evidence we need

To validate the "XLF/XLI edge survives" thesis, we need three pillars:

| Pillar | What it shows | Experiment |
|--------|---------------|------------|
| **A** Sector-ETF dealer GEX is materially more negative than SPX | The mechanism prerequisite — there is residual GEX in sectors | EXP-3201 (sector-ETF GEX reconstruction, 2d) |
| **B** Sector-ETF stream alpha is concentrated in negative-GEX days | The mechanism is empirically active on our streams | EXP-3000 Phase A (3-4d) |
| **C** Sector-ETF alpha decays in time-series when sector GEX trends toward zero | Forward-looking risk signal we can monitor | EXP-3201 + EXP-3000 follow-on rolling-window analysis |

**If A + B both hold:** the XLF/XLI edge is mechanistically explained by the DBG framework and we have a forward-looking monitor (Pillar C) for when the regime may flip.

**If A holds but B doesn't:** XLF/XLI alpha exists but is NOT GEX-mechanism-driven — some other source. Investigate alternative mechanisms (rotation flow, sector-event premium, etc.).

**If A doesn't hold:** sector ETF dealer GEX is near zero like SPX. Our XLF/XLI alpha must come from a different mechanism entirely (most likely O'Donovan-Yu mitigation residue) — and that residue may be smaller than backtests suggest.

---

## 5. Concrete implications for v8a

### 5.1 What this means for sizing decisions
Until Pillars A and B are confirmed:
- Hold XLF/XLI stream sizes at **current** allocation (not the larger allocations EXP-2200/EXP-2250 considered for v6/v7).
- Do NOT scale XLF/XLI before EXP-3000 Phase A completes.
- Maintain v5_hedge sleeve at full O'Donovan-Yu prescribed weight (separately justified by P13/P15 in the systematic review).

### 5.2 What this means for paper-trading metrics
Add to paper-trading dashboard:
- Daily sector-ETF GEX proxy (XLF, XLI), normalised.
- Stream-return × GEX-bucket scatter (per-trade attribution).
- Rolling 60-day correlation of stream-return with GEX-bucket — early-warning indicator if mechanism is decaying.

### 5.3 What this means for production risk gates
- If XLF/XLI dealer GEX trends positive for **>30 consecutive trading days**, mechanically reduce sizing on xlf_cs/xli_cs by 50% pending review.
- This is a forward-looking circuit breaker that the DBG literature directly motivates. **It does not exist in current v8a — recommend adding.**

### 5.4 What this means for institutional fundraising narrative
The story for investors can now be clean: "*v8a's alpha is concentrated in universes where dealer net gamma remains structurally negative — sector ETFs that have not been arbitraged by the institutional vol-selling complex that killed SPX VRP. We continuously monitor dealer GEX across our universe and gate exposure when the underlying mechanism weakens.*"

This is publishable, defensible, and academically grounded — but only if Pillars A and B confirm. Without confirmation, the narrative is conjecture.

---

## 6. Recommended action set

### Immediate (this week)
1. **EXP-3211** — DBG cumulative-alpha check on v8a streams (1 day).
   Confirms whether exp1220/qqq_cs already show the DBG-flat-cumulative-line.
2. **EXP-3201** — Sector-ETF GEX reconstruction 2019-2024 (2 days).
   Direct test of Pillar A.

### Next sprint
3. **EXP-3000 Phase A** — IS gating calibration (3-4 days).
   Direct test of Pillar B with full sweep spec from `research/LIT_REVIEW_MAY2026.md`.
4. **Paper-trade dashboard update** — add GEX panels per Section 5.2.

### Decision gate after EXP-3211 + EXP-3201
If Pillar A confirms (sector ETFs negative GEX, materially more so than SPX): proceed to EXP-3000 Phase A.
If Pillar A fails: pivot research budget to alternative mechanism hypotheses (sector-rotation premium, dispersion premium, sector-event premium).

---

## 7. Bottom line

The dealer-GEX mechanism explains *why* SPX VRP collapsed and *why* a non-SPX universe might retain it. The mechanism is consistent with multiple independent post-2020 papers. **The mechanism has not been empirically tested on US sector ETFs.** v8a's XLF/XLI edge is therefore either:

1. A mechanistically-defensible alpha living in dealer-short-gamma territory the DBG flip has not reached (best case, defensible to investors), or
2. A statistical residual from O'Donovan-Yu-style cost-mitigation advantages, smaller and more fragile than backtests suggest (worst case, fragile to live degradation), or
3. A backtest artifact (paranoid case, requires falsification).

**EXP-3211 + EXP-3201 + EXP-3000 Phase A together discriminate between cases (1), (2), and (3).** Total budget: ~7 days. Information value: existential for the XLF/XLI streams. This is the single highest-priority research investment for the v8a roadmap.

---

## Sources

Cross-referenced to paper numbers in `research/LIT_REVIEW_MAY2026.md`:
- [P1 — Dew-Becker & Giglio 2025](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en)
- [P2 — Vasquez, Amaya, Pearson, Garcia-Ares 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405)
- [P3 — Dim, Eraker, Vilkov 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190)
- [P5 — Regan & Xie 2025](https://arxiv.org/pdf/2512.17923)
- [P6 — Ober 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5032337)
- [P7 — Terstegge 2025 FMA Derivatives](https://www.fma.org/assets/docs/Derivatives2025/Terstegge.pdf)
- [P8 — He, Kelly, Manela 2017](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2721783)
- [P9 — Heston & Todorov 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509)
- [P10 — SSE 50 ETF VRP 2024](https://www.sciencedirect.com/science/article/abs/pii/S1062940824001311)
- [P12 — Papagelis & Dotsis 2025](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589)
- [P13 — O'Donovan & Yu 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
