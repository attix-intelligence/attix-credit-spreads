# Execution Optimization — Actionable Rules for Credit Spreads

**Audience.** pilotai-credit-spreads execution layer. Specifically `xlf_cs`,
`xli_cs`, `qqq_cs` streams (verticals) and any future single-name credit-spread
streams (SPX, SPY, IWM).

**Status.** Draft v1.0. Companion long-form research lives in
[`compass/execution_optimization_research.md`](../compass/execution_optimization_research.md);
this document is the operational distillation.

**Why this matters.** EXP-2570 estimated **890.3 bps/yr** cost drag against
the v8a portfolio. That figure assumes quoted half-spread; literature
(Muravyev & Pearson 2020) shows realised costs are typically < 40% of that
when execution is fair-value-aware. Ten of the rules below target reclaiming
~200-400 bps/yr of that drag.

---

## A. Hard Rules (always apply)

### A1. Always use complex (multi-leg) orders. Never leg.
- A complex order is a single atomic instruction on the exchange's Complex
  Order Book (COB), priced as a net debit/credit. Both legs print together
  or neither does.
- Legging risk during a 500ms inter-leg gap on a 30-DTE SPY put-credit
  spread costs ~2-4¢/spread from underlying drift alone in normal vol;
  10-20¢ during event windows.
- Empirical anchor: atomic multi-leg execution reduces slippage by an
  order of magnitude vs sequential in adjacent markets (Talos crypto basis:
  1.3-5.2 bps vs 17-54 bps). Listed-options ratio is smaller (2-4×) but
  still material.
- **Override path**: explicit `force_legged=true` flag with a written
  reason; logged for post-trade audit.

### A2. Reject the open. No entries before 10:00 ET, no entries after 15:30 ET.
- 9:30-10:00: spreads widest, MM inventories unsettled, underlying gapping.
- 15:30-16:00: 0DTE order-flow volatility dominates; effective spreads on
  short-dated contracts widen ~3× vs midday (Doshi et al. 2025).
- Exits inside 10:00-15:30 ET unless triggered by stop or expiry deadline.

### A3. Skip days when VRP < 5 percentage points.
- VRP gate: VIX − RV(20) > 5%.
- Below this threshold the historical edge in short-vol credit spreads
  collapses (Bollerslev/Tauchen/Zhou 2009 and follow-ons; replicated for
  this strategy in EXP-1660).
- This is an **entry filter**, not a position-management rule.

### A4. Avoid event proximity windows.
- Two trading days before / after FOMC: skip new entries.
- Earnings (single-name only): skip if implied move > 5% within DTE window.
- Triple-witching OPEX (third Friday): skip 0-3 DTE entries near round
  strikes (pinning risk).

### A5. Standard exit discipline.
- **50% of max profit** → close. Captures ~70% of total strategy edge while
  shedding the gamma/vol-of-vol tail.
- **21 DTE** → close, regardless of P&L. Past 21 DTE the gamma profile
  flips and tail risk grows non-linearly. Already implemented in EXP-1220.
- **2× credit lost** → stop-loss. Cuts left-tail contribution to drawdown
  by 30-50% with marginal win-rate impact.

---

## B. Limit-Pricing Rules (the walk-the-book ladder)

### B1. Initial limit at mid − 0.10 · S_pkg
For credit spreads (you're a net seller), the package mid is
`mid_pkg = mid_short_leg − mid_long_leg`. Place initial sell limit at
`mid_pkg − 0.10 · S_pkg` where `S_pkg` is the package quoted half-spread.

### B2. Step the limit toward the far quote on a fixed schedule
| t (sec) | Limit offset from mid | Aggressiveness |
|---|---|---|
| 0   | mid − 0.10·S_pkg | passive |
| 5   | mid − 0.20·S_pkg | mildly passive |
| 10  | mid − 0.30·S_pkg | balanced |
| 20  | mid − 0.45·S_pkg | aggressive |
| 35  | mid − 0.50·S_pkg (cross) | take liquidity |
| 35+ | abandon — re-attempt next minute | accept opportunity cost |

Expected effective half-spread savings vs immediate cross at t=0:
**35-55%**.

### B3. Rationale for `k` (where on the spread to peg)
- For a strategy with weekly entry cadence and known target premium,
  missing a fill is cheap (next opportunity is fine).
- That makes opportunity cost low and supports passive `k ≈ 0.10-0.20`.
- **Closing trades are different.** Use `k ≈ 0.35-0.50` (more aggressive)
  because (a) you're managing position risk, not opportunity, and (b)
  closing fills on retail-symmetric flows tend to get less price
  improvement than openings.

### B4. Use price-improvement auctions for marketable orders
- When the package is already crossable (would be filled at mid −
  0.50·S_pkg), submit it as an AIM/PIM order rather than a market.
- AIM/PIM steps the package through a flash auction; routine
  improvement of 1-3¢/spread.

---

## C. Venue / Routing Rules

### C1. Single-COB routing, not sweep
- C-LOB quotes are NOT in the OPRA SIP; sweeping requires direct exchange
  feeds and rarely improves vs single best-COB routing for non-marketable
  package limits.
- For SPX-side flow: route to **Cboe C1** (~70% of SPX complex flow).
- For ETF spreads (SPY, QQQ, IWM, XLF, XLI): route to broker default if it's
  a Cboe-direct-access broker; otherwise prefer C1 first, then BZX/EDGX.

### C2. Broker selection criteria
| Criterion | Why |
|---|---|
| Direct exchange access (no PFOF on options) | Avoids passive-fill degradation from order internalisation |
| Native COB orders supported | Required for atomic execution |
| AIM/PIM auction participation | Recovers price improvement on marketable orders |
| Per-contract pricing < $0.65 | Above this, fees are ~10% of total drag |

If current broker fails any of these, A/B it against an alternative
(proposed: **EXP-3270 — Broker / SOR Comparison**).

### C3. PFOF awareness
- US options brokers including Robinhood, tastytrade, Schwab, E*TRADE
  accept PFOF from MMs (Citadel, Susquehanna, Wolverine).
- Effect on retail option fills: documented price improvement on
  *marketable* orders, but **worse passive fills** (orders sit longer,
  fill at the far quote more often).
- Implication for credit spreads: passive limit orders (most of our flow)
  are the regime hurt most by PFOF routing.

---

## D. Transaction Cost Analysis Rules

### D1. Don't benchmark against synthetic NBBO mid
- C-LOB has tighter quotes than the leg-by-leg synthetic NBBO. Benchmarking
  vs synthetic NBBO systematically *under*-credits complex fills.
- **Correct benchmark**: package mid from the COB at decision time, plus
  per-leg micro-mid from the simple book at fill time.

### D2. Decompose every fill into 5 components
```
Total cost = quoted_half_spread (A)
           + adverse_selection (B)
           + opportunity_cost (C)            ← unfilled / partial / delay
           − price_improvement (D)            ← fills inside synthetic NBBO
           + fees (E)
```
Tag each component on every closed trade. Aggregate monthly to a TCA
dashboard. Look for the components driving period-over-period change.

### D3. Use Muravyev fair-value adjustment
- Conventional half-spread overstates effective cost by ~60% when execution
  timing is fair-value-aware.
- Compute fair value as: leg micro-mid (size-weighted bid/ask) plus a
  short-window inventory drift correction.
- Adjusted half-spread = max(0, fill price − fair value) for sells, and
  symmetric for buys.

### D4. Maintain a 30-day rolling effective-half-spread
- Stream-level (per `xlf_cs`, `xli_cs`, etc.).
- Alarm if any stream drifts > 1.5σ above its trailing baseline; investigate
  before next entry.
- **Proposed**: EXP-3240 — refit EXP-2570's 890.3 bps drag using
  fair-value-adjusted half-spread on the same trade tape; expected
  reduction 200-400 bps.

---

## E. Market Impact Rules

### E1. Stay below the impact regime
- Goyenko et al. (2021): for SPX/SPY, price impact dominates spread cost
  for trades > 50 contracts; below that, half-spread dominates.
- pilotai-credit-spreads at current AUM operates well below the 50-contract
  per-spread threshold per stream — **half-spread is the right thing to
  optimise**, not market impact.
- Re-evaluate when single-stream notional implies > 25 contracts/order
  (current scale buffer: ~2× AUM).

### E2. Apply Almgren-Chriss to the delta book, not the option contract
- The option contract notional grossly overstates "size" because most of
  it is non-exposed (intrinsic + time value). Order-book impact is driven
  by the *delta-equivalent underlying* the dealer must hedge.
- Useful rule of thumb: package delta-equivalent shares = `|net_delta| ·
  notional_underlying ÷ underlying_price`.
- Compare this number to the underlying's average 1-min volume. If
  package delta-equivalent < 0.5% of 1-min volume → impact is negligible.

### E3. Don't try to time MM inventory directly
- Tempting (Muravyev 2016: MM inventory has first-order effect on prices)
  but data is not publicly observable and proxies are noisy.
- Park as a research idea (proposed: EXP-3280 — MM-inventory-conditioned
  entries) but do not deploy in production rules.

---

## F. 0DTE / Short-DTE Special Rules

### F1. If trading 0-5 DTE credit spreads at all, gate to 11:00-15:00 ET
- Effective spreads in short-dated contracts widen ~3× during the last 30
  minutes (Doshi et al. 2025).
- The first hour also has elevated spreads from overnight-imbalance unwind.
- 11:00-15:00 ET is the cleanest microstructure window for short-dated.

### F2. Respect the gamma cliff
- 0DTE MM net gamma can spike to 0.04-0.17% of S&P futures liquidity in
  stress windows (Cboe research). Aggressive market orders in the package
  can move the package mid by multiple ticks.
- Always passive (limit) on entries; aggressive only for risk-management exits.

### F3. SPX 0DTE = own benchmark
- SPX 0DTE represents 59% of all SPX volume in 2025 (Cboe). Existing TCA
  benchmarks built from longer-dated SPX trades do not apply.
- If we add 0DTE-ish streams, build a separate effective-half-spread baseline.

---

## G. Implementation Checklist

For each new live deployment:

- [ ] Order type defaults to `complex_net_credit` (A1)
- [ ] Time-of-day gate active: window = `["10:00", "15:30"]` ET (A2)
- [ ] VRP filter live: `vix - rv20 > 5` (A3)
- [ ] Event calendar gate: FOMC ±2d, OPEX same-day, earnings if relevant (A4)
- [ ] 50% / 21 DTE / 2× stop exit logic (A5)
- [ ] Walk-the-book ladder for entries: schedule from B2 (B1, B2)
- [ ] AIM/PIM submission for marketable orders (B4)
- [ ] Single-COB routing per C1; broker checked against C2 criteria
- [ ] Per-fill TCA decomposition logged (D2)
- [ ] Fair-value adjusted spreads used for monitoring (D3)
- [ ] Rolling 30-day effective-half-spread alarm (D4)
- [ ] Delta-equivalent size check pre-order; abort if > 0.5% of 1-min
      underlying volume (E2)

---

## H. Proposed Follow-Up Experiments

| Exp | Title | Expected savings |
|---|---|---|
| EXP-3240 | Fair-Value TCA Re-Audit (re-measure EXP-2570 drag) | 200-400 bps/yr (re-attribution, not change in PnL) |
| EXP-3250 | Complex-Order Auction Participation A/B | 5-15 bps/spread on marketable orders |
| EXP-3260 | 0DTE microstructure exclusion (last 30 min gate) | 3-8 bps/spread on short-dated only |
| EXP-3270 | Broker / SOR comparison | 100-200 bps/yr if PFOF currently degrades passive fills |
| EXP-3280 | MM-inventory-conditioned entry signal (research) | Speculative; bound at ~50 bps if it works |

---

## I. References

Foundational:
- Muravyev, D. & Pearson, N. D. (2020). *Options Trading Costs Are Lower Than You Think*. [SSRN 2580548](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2580548)
- Muravyev, D. (2016). *Order Flow and Expected Option Returns*. [Journal of Finance](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12380)
- Almgren, R. & Chriss, N. (1999/2001). *Optimal Execution of Portfolio Transactions*. [PDF](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf)
- Goyenko, R. et al. (2021). *Price impact versus bid-ask spreads in the index option market*. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1386418121000550)
- Bollerslev, T., Tauchen, G., Zhou, H. (2009). *Expected Stock Returns and Variance Risk Premia*. *RFS*.

Industry / regulatory:
- Cboe — *US Options Complex Book Process*. [PDF](https://cdn.cboe.com/resources/membership/US-Options-Complex-Book-Process.pdf)
- Cboe — *State of the Options Industry, Q3 2025*. [Cboe](https://www.cboe.com/insights/posts/the-state-of-the-options-industry-quarter-three-2025/)
- Cboe — *Evaluating Market Impact of SPX 0DTE Options*. [Cboe](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/)
- Doshi, Pemy & Singh (2025). *Risky Intraday Order Flow and Option Liquidity*. [PDF](https://www.bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf)
- SEC DERA — *Customer Use of Limit Orders in 0DTE Market* (2025). [PDF](https://www.sec.gov/files/dera-hope-reasonable-prc-2503.pdf)
- Talos — *Multi-Leg Algos / Slippage* (industry whitepaper). [Talos](https://www.talos.com/insights/how-talos-multi-leg-algos-slash-execution-slippage-for-basis-trades)

Internal:
- Long-form research: [`compass/execution_optimization_research.md`](../compass/execution_optimization_research.md)
- EXP-2570: cost-drag estimation (890.3 bps/yr basis for net metrics)
- EXP-1220: 21-DTE-exit rule baseline
- EXP-1660: VRP-deepening signal
- EXP-3150 / EXP-3230: walk-forward robustness baselines

---

*Operational distillation; for derivations and academic context see the
companion long-form research document.*
