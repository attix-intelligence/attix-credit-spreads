# Execution Optimization Research — Multi-Leg Options Spreads

**Scope.** Optimal execution for multi-leg listed-options strategies (vertical
credit spreads, calendar spreads, condors). Framed for the pilotai-credit-spreads
project (v8a streams: `xlf_cs`, `xli_cs`, `qqq_cs`, calendars on `gld_cal`,
`slv_cal`, plus the `exp1220` / `cross_vol` / `v5_hedge` overlay set).
EXP-2570 has already established a pooled cost drag of **890.3 bps/yr**;
this document explains the components of that drag and how to reduce them.

**TL;DR.**
1. Use **complex-order-book (COB) net-debit/credit** rather than legging — the
   single largest practical lever (saves 30-60% of effective spread on
   typical credit spreads).
2. Trading-cost drag on options is **not** "half the quoted spread" — Muravyev
   & Pearson (2020) show effective costs are < 40% of the conventional measure
   when execution is timed against fair value.
3. **Time-of-day** matters more than for equities. Concentrate entries
   between 10:00-15:30 ET; avoid the open and the last 15 minutes (especially
   for SPX 0DTE where intraday OFV is now the dominant cost driver).
4. **Almgren-Chriss does not transfer directly** to options, but its decomposition
   (permanent + temporary impact) is the right scaffold; use it on the
   *underlying-equivalent* delta book, not the option contract notional.
5. **Vendor SOR + complex routing** matters: SEC Rule 611 (Order Protection Rule
   under Reg NMS) does NOT apply to options the same way. Best-ex obligations
   exist but venue choice is materially up to the broker — pick brokers
   accordingly.

---

## 1. TCA Frameworks for Options Markets

### 1.1 Why equity TCA breaks
Standard equity TCA (Perold 1988 implementation shortfall, VWAP/TWAP slippage)
relies on (a) a continuous, highly liquid lit book and (b) reference benchmarks
that are unambiguous (NBBO arrival, VWAP). Options markets violate both:

- **NBBO is wide and stale.** OPRA-disseminated NBBO on individual options
  series is often 5-15% wide (in % of mid) and refreshes orders of magnitude
  more slowly than the underlying. Effective spreads are systematically tighter
  than quoted spreads (Muravyev & Pearson 2020).
- **Reference benchmarks are ill-defined.** "Arrival mid" depends on which
  series; for a multi-leg package the package mid is path-dependent on which
  exchange's COB you sample.
- **No consolidated tape for complex orders.** OPRA disseminates simple-leg
  NBBO; **C-LOB (complex order book) quotes are NOT in the SIP** [(Cboe Complex Book Process)](https://cdn.cboe.com/resources/membership/US-Options-Complex-Book-Process.pdf).
  This means the "true" liquidity for spread packages is invisible to most TCA
  systems unless they ingest direct exchange feeds.

### 1.2 Useful options-TCA decomposition

For a credit-spread fill, decompose realised cost into:

```
Total cost = (mid_arrival - fill_price)                       [shortfall vs arrival mid]
           = quoted_half_spread (A)                           [pure quote width cost]
           + adverse_selection (B)                            [info-mediated drift]
           + opportunity_cost (C)                             [unfilled / partial / delay]
           − price_improvement (D)                            [fill inside NBBO via PI auction]
           + fee_drag (E)                                     [exchange + clearing + reg]
```

Component sizes (rough industry numbers, not Muravyev specifically — verify
on your own fills):

| Component | Typical % of total drag (credit spreads, $1-5 wide, 30-45 DTE) |
|---|---|
| (A) quoted half-spread | 50-70% |
| (B) adverse selection | 5-15% |
| (C) opportunity cost | 10-25% (varies a lot with limit aggressiveness) |
| (D) price improvement (negative drag) | -10 to -30% |
| (E) fees | 5-10% |

For pilotai-credit-spreads, EXP-2570's 890.3 bps total annual drag is
consistent with (A)+(B)+(E)−(D) at typical credit-spread parameters and
weekly turnover.

### 1.3 Recommended pre/post-trade TCA stack

- **Pre-trade**: snapshot complex-book mid + NBBO of each leg at decision
  time; record both. Compute "package fair value" from each leg's micro-mid
  (bid + ask)/2 weighted by size + an inventory-adjusted Muravyev-style
  fair-value adjustment.
- **At-fill**: log venue, leg fills (if legged), package print, time-to-fill,
  and concurrent NBBO of each leg.
- **Post-trade**: compute (a) shortfall vs decision-time package mid,
  (b) shortfall vs arrival NBBO mid, (c) effective half-spread, (d) what-if
  legged fills (using each leg's NBBO at fill time). The (d) counterfactual
  is the cleanest measurement of "complex-order saving".

---

## 2. Slippage Modeling — Simultaneous vs Sequential Multi-Leg Execution

### 2.1 The legging-risk problem

If you leg a credit spread (sell put A, then buy put B), between fills the
underlying can move and the second leg's price moves with it. For a 30-DTE
short put / long-further-OTM put on SPY, leg-1 to leg-2 latency of ~500ms
during normal vol carries an expected slippage of ~2-4¢ per spread on
the second leg from underlying drift alone (delta * underlying-tick volatility).
During event windows it can easily be 10-20¢.

### 2.2 Why complex orders win

A complex order is a **single atomic instruction priced as a net package**.
Cboe and other exchanges define them as orders involving "the concurrent
execution of two or more different series in the same underlying ... for
the purpose of executing a particular investment strategy"
[(Cboe Rule Filings)](https://www.cboe.com/us/options/regulation/rule_filings/).
Complex orders execute either:
- **Against the COB** — passive resting limit at a net price
- **Against the leg market via auction** — the exchange's complex-order
  matching algorithm steps each leg through that exchange's simple book
  AT-OR-INSIDE the synthetic NBBO, only printing if both legs fill at the
  net price. **Legging risk is eliminated by exchange guarantee.**
- **In a price-improvement auction** (e.g. Cboe AIM, NYSE Arca PIM) — the
  whole package goes into a flash auction, often filling inside the synthetic
  NBBO.

### 2.3 Quantitative slippage models for legging vs complex

Let:
- `S_i` = quoted half-spread of leg i
- `ρ` = correlation of the two legs' microstructure noise (≈ 0.8-0.95 for
  same-underlying same-expiry verticals)
- `Δt` = inter-leg delay (sequential)
- `σ_u` = underlying volatility
- `δ_i` = delta of leg i

**Sequential (legging) expected cost:**
```
E[C_seq] = S_1 + S_2 + |δ_1 - δ_2| · σ_u · √Δt   + adverse selection
```

**Simultaneous (complex order):**
```
E[C_complex] = S_pkg ≤ S_1 + S_2  (package width is typically 60-80% of summed leg widths because ρ < 1)
```

**Empirical anchor (industry, not options-specific):** Talos reports basis-trade
multi-leg-vs-manual slippage of **1.3-5.2 bps vs 17-54 bps** in crypto futures —
roughly an **order-of-magnitude reduction** when atomic leg execution is
guaranteed [(Talos)](https://www.talos.com/insights/how-talos-multi-leg-algos-slash-execution-slippage-for-basis-trades).
Listed-options ratios are smaller (factor of 2-4×) because exchange COBs are
slower and quote less aggressively than continuous makers.

### 2.4 Pricing the limit (where to peg the complex order)

For a credit spread (you're a net seller of premium):

```
limit = mid_pkg − k · S_pkg
```

where `mid_pkg = (mid_leg1) − (mid_leg2)` and `k ∈ [0, 0.5]` controls
aggressiveness:
- `k = 0` → at mid; expected fill rate < 50%, expected cost ≈ 0 spread
- `k = 0.25` → typical balance; expected fill rate 70-85%, cost ≈ ¼ spread
- `k = 0.5` → at far-quote; ~95% fill, full half-spread

The right `k` depends on **opportunity cost of not filling** vs
**spread saved**. For a credit-spread strategy with weekly entries and
known target premium, missing a fill is cheap (next week is fine), so
`k ≈ 0.10-0.20` is appropriate. For closing trades or hedges where timing
matters, `k ≈ 0.35-0.50`.

### 2.5 Walk-the-book ladder

A practical algorithm for getting filled without paying the full spread:

```
t=0:   place at mid - 0.10·S_pkg     (5 sec)
t=5:   improve to mid - 0.20·S_pkg   (5 sec)
t=10:  improve to mid - 0.30·S_pkg   (10 sec)
t=20:  improve to mid - 0.45·S_pkg   (15 sec)
t=35:  cross to far quote (mid - 0.50·S_pkg) and accept
```

This captures price improvement when the market is willing while bounding
opportunity cost. Expected effective half-spread savings: **35-55%** vs
crossing at t=0.

---

## 3. Smart Order Routing for Options

### 3.1 Venue landscape (US, 2025-2026)
17 options exchanges currently operate in the US (Cboe family: C1, C2, BZX, EDGX;
NYSE: Arca, American; Nasdaq family: PHLX, ISE, GEMX, MRX, BX, NOM; MIAX:
MIAX, Pearl, Emerald, Sapphire; BOX). Each has a **simple book** and a
**complex book**, but COB liquidity concentration varies — for SPX,
**Cboe C1 is dominant**; for ETF spreads (SPY, QQQ, IWM) liquidity is split
across Cboe family and Nasdaq family.

### 3.2 Best-execution rules for options
- **SEC Rule 605/606** disclosures apply to options brokers (statistics on
  execution quality).
- **No NMS Rule 611 trade-through prohibition for options** in the equities
  sense; instead, options exchanges enforce trade-through via their own rules
  via the **OPRA-disseminated NBBO**.
- **PFOF is widespread in options.** Brokers including Robinhood, tastytrade,
  Schwab, E*TRADE accept PFOF from options market makers (Citadel, Susquehanna,
  Wolverine, Citadel, Optiver) [(Wikipedia: PFOF)](https://en.wikipedia.org/wiki/Payment_for_order_flow).
  Effect on retail option fills is mixed: documented price improvement on
  marketable orders but worse passive fills.

### 3.3 SOR design considerations for spreads

| Decision | Recommendation | Rationale |
|---|---|---|
| Route to single COB or sweep multiple? | **Route to single COB** (best-quoted) | C-LOB quotes are NOT in SIP; sweeping requires direct feeds |
| Use AIM/PIM auctions? | **Yes, for marketable packages** | Routine 1-3¢/spread of price improvement |
| Dark pools? | **Not applicable** | No options dark pools of meaningful size |
| Leg if no COB liquidity? | **Only with strict guards** | Cap legging-risk via cross-leg exposure check before second send |
| Broker selection | **Cboe-direct-access broker for SPX** | C1 has 70%+ of SPX complex flow |

### 3.4 Post-2024 changes worth tracking
- **Future-Option orders** (single complex orders with options + futures legs)
  have been approved on Cboe — useful for hedging spread positions atomically
  with futures [(SEC Federal Register)](https://www.federalregister.gov/documents/2025/01/13/2025-00412/self-regulatory-organizations-cboe-exchange-inc-order-instituting-proceedings-to-determine-whether).
- Cboe **Retail Broker** complex-book data feed pricing (April 2026 filing) —
  reduces COB-data cost for retail-flow brokers, improving their SOR quality
  [(SEC Federal Register, Apr 2026)](https://www.federalregister.gov/documents/2026/04/15/2026-07258/self-regulatory-organizations-cboe-exchange-inc-notice-of-filing-and-immediate-effectiveness-of-a).

---

## 4. Market Microstructure of Options Order Books

### 4.1 Quoted vs effective spread
Muravyev & Pearson (2020) "Options Trading Costs Are Lower Than You Think"
[(SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2580548) is the
key reference. Headline:

> Effective spreads for traders who time executions are **less than 40%** of
> conventional half-spread or effective-spread estimates, because option price
> changes are predictable at high frequency and trades concentrate when the
> option's fair value is close to bid (for buys) or ask (for sells).

**Implication for pilotai-credit-spreads.** EXP-2570's 890.3 bps drag is
likely *over-estimated* if it uses quoted half-spread. A fair-value-adjusted
re-measurement of the same trades could plausibly recover **300-400 bps/yr**
of "drag" that's actually achievable price improvement — worth a follow-up
audit (proposed: EXP-3240).

### 4.2 Market-maker behaviour
Muravyev (2016) "Order Flow and Expected Option Returns"
[(Journal of Finance)](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12380):
inventory risk faced by options MMs has a first-order effect on prices. When
MMs are inventory-long puts, they shade quotes lower (better for sellers,
worse for buyers).

Muravyev (2025) "Options Market Makers"
[(FMA Working Paper)](https://www.fma.org/assets/docs/Derivatives2025/Muravyev.pdf):
- MMs aim to capture roughly **half** of the bid-ask spread on each trade,
  but realised capture varies with vol, volume, and spread width.
- A meaningful fraction of MMs do NOT delta-hedge intraday. This is critical:
  at the moment they are short gamma and short delta, your sell-to-open
  credit spread can fill better than mid because the MM is willing to pay
  for inventory relief.

### 4.3 Complex-Order-Book mechanics
[(Cboe Complex Book Process)](https://cdn.cboe.com/resources/membership/US-Options-Complex-Book-Process.pdf)
- Multiple matching modes: **leg-into-leg-market** (LM), **AIM**, **complex-only-cross** (CC).
- Pricing: must be at-or-better than the **derived synthetic NBBO** (best
  price achievable by independent leg fills).
- **C-LOB quotes are NOT consolidated** through OPRA SIP. Public traders
  see only the simple-leg books; the actual best package quote may be
  meaningfully tighter than what you'd reconstruct. This is also why
  TCA against "synthetic NBBO mid" systematically *under*-credits complex
  fills with their true price improvement.
- Most C-LOB quoting is by **proprietary trading firms / customer flow**,
  not designated MMs (who maintain only the simple-leg quotes). Liquidity
  is one-sided and lumpy.

### 4.4 Index-option-specific findings
Goyenko et al. (2021) "Price impact versus bid-ask spreads in the index
option market" [(ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S1386418121000550):
in SPX/SPY, **price impact** dominates spread costs for trades > 50 contracts;
under that threshold, half-spread dominates. Implication: pilotai-credit-spreads
notional sizing is well below the impact regime in SPY/QQQ.

### 4.5 0DTE-specific microstructure (2024-2026)
- 0DTE options are now **24.1% of total US listed options volume** (2025) and
  **59% of SPX volume** (~2.3M contracts/day) [(Cboe Q3 2025)](https://www.cboe.com/insights/posts/the-state-of-the-options-industry-quarter-three-2025/).
- Doshi, Pemy & Singh (2025) "Risky Intraday Order Flow and Option Liquidity"
  [(Bauer working paper)](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf):
  trading costs in **shorter-dated** contracts are far more sensitive to
  intraday order-flow volatility. For 0DTE specifically, effective spreads
  widen ~3× during the last 30 minutes vs midday.
- Cboe research: 0DTE MM intermediation lowers index volatility 60-90 bps
  on average, but during stress windows MM net gamma can spike to 0.04-0.17%
  of S&P futures liquidity — large enough that an aggressive market order
  can move the package mid materially.

---

## 5. Optimal Timing for Spread Entry/Exit

### 5.1 Intraday spread/liquidity profile
- **9:30-10:00 ET (the open)**: spreads are widest, MM inventories unsettled,
  underlying gapping. Avoid for both entry and exit unless event-driven.
- **10:00-11:30 ET**: spreads tighten, complex-book liquidity builds.
  Good for entries.
- **11:30-13:30 ET (lunch)**: shallowest book, but tight quotes; small
  orders fill well, large orders can tip the book.
- **13:30-15:30 ET**: deepest liquidity day-window. Best for both entries
  and exits of meaningful size.
- **15:30-15:55 ET**: 0DTE flow dominates; effective spreads widen 2-3×
  on shorter-dated contracts; gamma-driven price action makes spread
  legs decorrelate.
- **15:55-16:00 ET**: imbalances at close push pricing. Avoid.

### 5.2 Calendar/day-of-week effects
- **Mondays**: weekend gap risk priced in; vol risk premium at its peak
  for VRP-harvesting strategies — historical bias in put-credit spreads
  enters here.
- **Wednesdays**: post-FOMC vol crush often most pronounced; calendars
  benefit if entered *pre-* FOMC.
- **OPEX (third Friday)**: pinning risk near round strikes; avoid
  entering 0DTE-ish spreads near round strikes that day.

### 5.3 Entry timing relative to vol regime
Bollerslev, Tauchen, Zhou (2009) and subsequent VRP literature: realised
edge in put-credit-spread harvesting is concentrated when **VRP > 5
percentage points (annualised vol)**. Recommendation: gate entries by
VIX-RV(20) > 5; skip the day otherwise. EXP-1660 in this repo already
explores VRP deepening signals.

### 5.4 Exit timing — early vs hold-to-expiry
For credit spreads, early-exit profile:
- **At 50% max profit reached**: ~70% of strategy edge realised; vol-of-vol
  exposure beyond this point is unpaid risk. Industry consensus (tastytrade
  research, etc.) supports 50%-of-credit early-close rule.
- **At 21 DTE**: gamma starts to dominate; remaining premium decays
  predictably but tail risk grows non-linearly. EXP-1220 in this repo
  uses this rule.
- **Stop-loss at 2× credit**: standard; reduces tail-loss contribution
  to drawdown by 30-50% with modest impact on win rate.

### 5.5 Quantitative entry-timing framework

```
score = α · VRP_signal
      + β · entry_window_indicator     (1 if 10:00-15:30 ET)
      + γ · liquidity_score            (z-score of current pkg-spread vs day mean)
      + δ · vol_regime_filter          (ATR-based regime gate)
      − ε · event_proximity_penalty    (FOMC, earnings, OPEX within 2 days)
```

Calibrate weights via grid search on historical fills. EXP-2280 / EXP-3230
walk-forward methodology applies.

---

## 6. Quantitative Frameworks Summary

| Framework | Origin | Applicability to Spreads | Notes |
|---|---|---|---|
| Almgren-Chriss optimal execution | Almgren & Chriss (1999/2001) | Apply to delta-equivalent underlying book, not option contract | Permanent vs temporary impact decomposition is correct; sqrt-impact functional form approx OK |
| Implementation Shortfall (Perold) | Perold (1988) | Direct: shortfall vs decision-time package mid | Use package mid, not arrival NBBO |
| Kyle (1985) lambda | Kyle (1985) | Limited: options have asymmetric MM vs informed flow | Goyenko et al. (2021) specialises to index options |
| Glosten-Milgrom adverse selection | Glosten & Milgrom (1985) | Yes: explains why MM half-spread > realised effective spread | Explains the Muravyev "lower than you think" finding |
| Stoikov-Avellaneda market making | Avellaneda & Stoikov (2008) | Inverse use: model the MM, fade aggressive quotes | Useful for fair-value computation when crossing |
| Cartea-Jaimungal limit-order placement | Cartea & Jaimungal (multiple) | Yes: optimal `k` for limit placement | Direct application to walk-the-book ladders |
| Risk-parity portfolio cost model | n/a (in-house) | Required for v8a-style portfolios with multiple spread streams | Drag is approximately additive across streams |

---

## 7. Recommendations Specific to pilotai-credit-spreads

### 7.1 Immediate (re-measurement, no execution change)
1. **Re-audit EXP-2570 drag using fair-value-adjusted half-spread.** Current
   890.3 bps assumes quoted spread; Muravyev-style measurement could shave
   200-400 bps. Proposed experiment: **EXP-3240 — Fair-Value TCA Re-Audit**.
2. **Log COB quotes alongside leg-book quotes** for live trades. Most TCA
   systems miss this; without it, "synthetic NBBO" benchmark over-states cost.

### 7.2 Near-term (execution algorithm)
3. **Always use complex orders** (already standard, but enforce: legging
   should require explicit override).
4. **Walk-the-book ladder** (Section 2.5) for entries; expected savings
   200-300 bps annualised at current turnover.
5. **Time-of-day gate**: shift all non-event entries to 10:00-15:30 ET.

### 7.3 Medium-term (research)
6. **EXP-3250 — Complex-Order Auction Participation.** Quantify expected
   price improvement from AIM/PIM participation. Hypothesis: 5-15 bps per
   marketable spread.
7. **EXP-3260 — 0DTE microstructure exclusion.** Test whether avoiding the
   last 30 minutes for 0DTE-ish DTE (≤ 5) tightens effective spread enough
   to change strategy economics.
8. **EXP-3270 — Broker / SOR comparison.** A/B current broker against a
   Cboe-direct-access broker for SPX-side flow; expected savings 100-200
   bps if current broker is PFOF-routed.

### 7.4 Open / harder
9. **Inventory-conditioning entry signal.** Use options market-maker
   inventory proxies (Muravyev 2016 framework) to time entries when MMs
   are likely inventory-long premium and willing to pay up for relief.
10. **Cross-venue COB stitching.** Build a private aggregated COB view across
    Cboe/Nasdaq/MIAX families. Material work, but materially better
    pre-trade fair value.

---

## 8. Key References

### Academic / working papers
- Almgren, R. & Chriss, N. (1999/2001). *Optimal Execution of Portfolio Transactions*.  [(PDF)](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf)
- Muravyev, D. & Pearson, N. D. (2020). *Options Trading Costs Are Lower Than You Think*. SSRN 2580548.  [(SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2580548)
- Muravyev, D. (2016). *Order Flow and Expected Option Returns*. *Journal of Finance*.  [(Wiley)](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12380)
- Muravyev, D. (2025). *Options Market Makers*. FMA Derivatives 2025.  [(PDF)](https://www.fma.org/assets/docs/Derivatives2025/Muravyev.pdf)
- Goyenko, R., et al. (2021). *Price impact versus bid–ask spreads in the index option market*. *Journal of Financial Markets*.  [(ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S1386418121000550)
- Doshi, H., Pemy, M. & Singh, R. (2025). *Risky Intraday Order Flow and Option Liquidity*.  [(PDF)](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf)
- Adams, G., Fontaine, J.-S., & Ornthanalai, C. *The Market for 0DTE: The Role of Liquidity Providers in Volatility Attenuation*. SSRN 4881008.  [(SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4881008)
- Perold, A. (1988). *The Implementation Shortfall: Paper Versus Reality*. *Journal of Portfolio Management*.
- Kyle, A. (1985). *Continuous Auctions and Insider Trading*. *Econometrica*.
- Glosten, L. & Milgrom, P. (1985). *Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders*. *Journal of Financial Economics*.
- Avellaneda, M. & Stoikov, S. (2008). *High-frequency trading in a limit order book*. *Quantitative Finance*.
- Bollerslev, T., Tauchen, G. & Zhou, H. (2009). *Expected Stock Returns and Variance Risk Premia*. *Review of Financial Studies*.

### Industry / regulatory
- Cboe Exchange — *US Options Complex Book Process v1.2.69*.  [(PDF)](https://cdn.cboe.com/resources/membership/US-Options-Complex-Book-Process.pdf)
- Cboe — *State of the Options Industry, Q3 2025*.  [(Cboe)](https://www.cboe.com/insights/posts/the-state-of-the-options-industry-quarter-three-2025/)
- Cboe — *Volatility Insights: Evaluating the Market Impact of SPX 0DTE Options*.  [(Cboe)](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/)
- SEC / Federal Register — *Future-Option Orders rule filing* (Cboe, Jan 2025).  [(Federal Register)](https://www.federalregister.gov/documents/2025/01/13/2025-00412/self-regulatory-organizations-cboe-exchange-inc-order-instituting-proceedings-to-determine-whether)
- SEC / Federal Register — *Cboe Retail Broker COB data-feed pricing* (Apr 2026).  [(Federal Register)](https://www.federalregister.gov/documents/2026/04/15/2026-07258/self-regulatory-organizations-cboe-exchange-inc-notice-of-filing-and-immediate-effectiveness-of-a)
- SEC DERA — *Customer Use of Limit Orders in the 0DTE Market* (2025).  [(PDF)](https://www.sec.gov/files/dera-hope-reasonable-prc-2503.pdf)
- Wikipedia — *Payment for Order Flow*.  [(Wikipedia)](https://en.wikipedia.org/wiki/Payment_for_order_flow)
- Talos — *Mastering Multi-Leg Algos: Advanced Execution Strategies* (industry whitepaper, crypto-focused but transferable).  [(Talos)](https://www.talos.com/insights/mastering-multi-leg-algos-advanced-execution-strategies-in-crypto-markets)

### Internal references (this repo)
- EXP-2570: cost-drag estimation (890.3 bps/yr, basis for net metrics)
- EXP-2280: 20-fold yearly walk-forward — robustness baseline
- EXP-3150: post-2020 retest, target_vol = 0.18
- EXP-3230: rolling 1-month-step walk-forward
- EXP-1220: 21-DTE-exit credit-spread base stream
- EXP-1660: VRP deepening signal
- `compass.exp2600_north_star_v8`: v8a cube + walk-forward primitives

---

## 9. Open Research Questions

1. **Is there a tractable Almgren-Chriss extension for atomic multi-leg
   complex orders?** The temporary-impact term has to be re-derived against
   the package's own liquidity surface, which is sparser than a single
   security's order book.
2. **Cross-venue C-LOB stitching** — what's the latency/value tradeoff?
3. **MM-inventory-conditioned entry signals** — can we infer inventory
   from public data (option-volume × OI residuals after hedging-flow
   estimates)?
4. **Optimal complex-order pegging policy in stress regimes** (when
   `ρ` of leg-noise breaks down, sequential might temporarily dominate).
5. **0DTE-specific TCA framework** — the Doshi et al. finding that order-flow
   volatility dominates costs in short-dated contracts implies the right
   benchmark is order-flow-conditioned mid, not arrival mid. Construction
   of such a benchmark is non-trivial and worth a dedicated experiment.

---

*Document prepared for the pilotai-credit-spreads research program.
Status: draft v1.0.  All paper citations were verified against published
sources at time of writing; treat any specific empirical numbers as
indicative until reproduced in-house.*
