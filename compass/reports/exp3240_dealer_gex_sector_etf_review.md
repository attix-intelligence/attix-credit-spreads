# EXP-3240 — Dealer GEX Literature Review: Sector ETF Focus

**Date:** 2026-05-15
**Hypothesis:** XLF/XLI dealer flow differs from SPX → VRP persists in sectors
**Method:** Targeted academic search (Google Scholar, SSRN, arXiv) for sector-ETF-specific dealer GEX or VRP work
**Companion files:** `research/GEX_VRP_DYNAMICS_MAY2026.md` (mechanism deep-dive), `research/LIT_REVIEW_MAY2026.md` (20-paper systematic review)

---

## Headline result — the sector-ETF gap is confirmed

**No 2020-2026 academic paper directly tests VRP or dealer GEX on XLF, XLI, or other US sector ETFs.**

This is the 6th lit-review pass that has reached this conclusion. Four new SSRN/Wiley searches were run this session with different terminologies ("XLF OR XLI options dealer", "sector ETF options open interest MM inventory", "ETF options market microstructure liquidity sector financials industrials", "variance risk premium sector equity ETF persistence"). None surfaced sector-ETF-specific VRP/GEX work.

**Research-budget recommendation:** stop searching the literature for this answer. The gap is real, not a search failure. The next dollar of research effort should go to EXP-3201 (empirical sector-ETF GEX reconstruction), not to a 7th lit-review.

---

## New papers surfaced this session (3 adjacent, not direct)

### N1. Moussawi, Xu, Zhou — "A Market Maker of Two Markets: The Role of Options in ETF Arbitrage"
- SSRN 4395938
- ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4395938))
- **Finding:** large MMs liquidity-provide in *both* ETF and options markets simultaneously; on SPY/SPX they perform intraday arbitrage using multi-leg complex options to capture mispricing (annualised **35.79%** in addition to bid-ask).
- **Relevance:** documents that the *same dealers* trade SPY-options and SPX-options against each other to neutralise inventory. This is a *spillover-risk* paper for the v8a thesis: if dealers on sector ETFs hedge with SPX, their *net* GEX on sector ETFs may not be what local sector-ETF OI suggests. **Direct relevance to Channel-A risk in `GEX_VRP_DYNAMICS_MAY2026.md` §3.1.**
- **Universe:** SPY/SPX only. Does NOT cover sector ETFs.

### N2. Barbon, Beckmeyer, Buraschi, Moerke — "Liquidity Provision to Leveraged ETFs and Equity Options Rebalancing Flows"
- SSRN 3925725
- ([URL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3925725))
- **Finding:** end-of-day rebalancing flows from leveraged ETFs and options gamma generate predictable order-flow imbalances; documents the size of MM inventory absorption around the close.
- **Relevance:** sets a methodological template for measuring inventory-imbalance dynamics from public data — directly applicable to EXP-3201 GEX-reconstruction methodology.

### N3. Chen (2025) — "Market Maker or Informed Trader: Option Trading and Underlying Returns on SSE 50 ETF"
- J. Futures Markets 2025
- ([URL](https://onlinelibrary.wiley.com/doi/10.1002/fut.70038?af=R))
- **Finding:** option call/put order imbalance is a usable MM-inventory proxy; predicts underlying returns with rapid reversals attributable to delta-hedging price pressure.
- **Relevance:** **methodological** — gives us an alternative GEX proxy (order-imbalance based) that can be reconstructed from IronVault data even when OI estimates are noisy. Complements the standard SpotGamma-style construction.
- **Universe caveat:** Chinese ETF, not US sector ETF.

---

## What we now know vs what we still need to find out

| Question | Status | Confidence | Source |
|----------|--------|-----------|--------|
| SPX dealer GEX flipped post-2008 | Confirmed | High | Dew-Becker-Giglio 2025; Dim-Eraker-Vilkov 2023; Vasquez et al. 2025; Regan-Xie 2025 |
| The flip mechanically explains SPX VRP collapse | Confirmed | High | DBG 2025 synthetic-vs-traded options |
| 0DTE growth has NOT undone the flip | Confirmed | High | Vasquez et al. 2025 |
| Dealers cross-hedge sector-ETF books against SPX | Documented (SPY↔SPX) | Medium | Moussawi-Xu-Zhou (N1) |
| Dealer GEX has flipped on US sector ETFs | **UNKNOWN** | n/a | No academic paper |
| XLF/XLI VRP persistence post-2020 | **UNKNOWN** academically; **POSITIVE** in our backtests | Medium (backtests only) | EXP-3150 (in-house only) |
| Sector-ETF order flow is more one-sided than SPX | Plausible mechanism | Low (no direct measurement) | Inferred from end-user composition argument |

The two highlighted gaps are the ones EXP-3201 needs to fill.

---

## Concrete implications for the v8a XLF/XLI thesis

### What is reinforced by this session's search
- **Moussawi et al. (N1)** documents that the same dealers trade SPY↔SPX → cross-hedging is a *real* concern (not just hypothetical). This sharpens the Channel-A risk in our prior dynamics document. **EXP-3201 must include an SPX cross-hedging check: if XLF GEX is locally negative but the dealer's aggregate book is flat after the SPX overlay, our thesis fails.**
- **Chen (N3)** gives us an order-imbalance-based GEX proxy that is more robust to OI-noise on low-volume sector ETFs. **Recommend adopting both methodologies in EXP-3201** — primary (OI × gamma) and secondary (order-imbalance proxy) — and triangulating.

### What is challenged
- The "channel-D literature gap" framing (`GEX_VRP_DYNAMICS_MAY2026.md` §2.4) needs a partial revision: while there is no direct sector-ETF GEX paper, **N1 shows the cross-asset MM-inventory framework that *could* be applied is already in the literature**. The gap is empirical, not theoretical — which makes our EXP-3201 work directly publishable.

### What is unchanged
- The three-pillar validation framework in `GEX_VRP_DYNAMICS_MAY2026.md` §4 still holds. EXP-3211 + EXP-3201 + EXP-3000 Phase A still discriminate between (1) mechanism-explained alpha, (2) O'Donovan-Yu residue, (3) backtest artifact.

---

## Recommended action set (updated)

### Stop doing
- Further lit-review passes on this topic. Six passes have established the gap; a seventh will not close it. Diminishing returns.

### Do next (in order)
1. **EXP-3211** — DBG cumulative-alpha check (1 day). Cheapest sanity test. Unchanged from prior reviews.
2. **EXP-3201** — Sector-ETF GEX reconstruction with **dual methodology** (2-3 days, was 2 days):
   - Primary: OI × gamma × spot² aggregation (Dim-Eraker-Vilkov / Cboe approach)
   - Secondary: order-imbalance proxy (Chen 2025 approach, more robust to low-OI noise)
   - **Add SPX cross-hedge check** (per Moussawi et al. N1) — verify the local sector-ETF GEX reading isn't being neutralised by the dealer's aggregate position.
3. **EXP-3000 Phase A** — IS gating calibration with dual-methodology GEX series (3-4 days).

### Methodological additions vs. prior spec
- The GEX construction in `LIT_REVIEW_MAY2026.md` §EXP-3000 should be updated to specify dual-methodology reconstruction.
- An SPX-cross-hedge stress test should be added: compute correlation between sector-ETF GEX and SPX GEX; if correlation > 0.7, sector-ETF GEX signal is contaminated by the cross-hedge.

---

## Bottom line

This session's searches contributed three useful adjacent papers (Moussawi et al., Barbon et al., Chen) but did NOT close the central gap (no direct sector-ETF VRP/GEX paper exists). The most material findings are methodological:

1. **Cross-hedging is real (N1)** — must be controlled for in EXP-3201.
2. **Order-imbalance is a viable alternative GEX proxy (N3)** — should be used alongside OI-based construction.

These are concrete spec updates for EXP-3201 / EXP-3000, not new directional results.

**Recommendation:** lock the literature review chapter on this topic. Begin EXP-3211 + EXP-3201 this week with the updated dual-methodology spec. The next dollar of research effort produces materially more value as empirical work than as a 7th lit review.

---

## Sources

### New this session
- [Moussawi, Xu, Zhou — A Market Maker of Two Markets (SSRN 4395938)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4395938)
- [Barbon, Beckmeyer, Buraschi, Moerke — Liquidity Provision to Leveraged ETFs and Equity Options Rebalancing (SSRN 3925725)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3925725)
- [Chen 2025 — MM vs Informed Trader on SSE 50 ETF (J. Futures Markets)](https://onlinelibrary.wiley.com/doi/10.1002/fut.70038?af=R)

### Carried forward from prior reviews
- [Dew-Becker & Giglio 2025](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf?sc_lang=en)
- [Vasquez et al. 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405)
- [Dim, Eraker, Vilkov 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190)
- [Regan & Xie 2025](https://arxiv.org/pdf/2512.17923)
- [Heston & Todorov 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4373509)
- [O'Donovan & Yu 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4806038)
