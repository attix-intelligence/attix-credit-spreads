# Options Market Making at $1MM — Feasibility Study

**Task:** EXP-MM-3
**Analyst:** Options MM analyst (research only — no code/data modified)
**Date:** 2026-06-21
**Question (Carlos):** Can we profitably *market make* options with $1,000,000, given our existing
options/VRP edge (v8a: credit spreads on SPY/QQQ/XLF/XLI + GLD/SLV calendars, backtest Sharpe ~6.4)?

---

## 0. Executive Summary (read this first)

**Standalone options market making at $1MM is marginally viable but NOT recommended as a new desk.**
The edge that makes option spreads wide is real and it is the *same* edge v8a already harvests (the
volatility risk premium / dealer inventory premium). But running a true quoting desk at $1MM means
(a) you cannot beat the wholesalers for the good retail flow — it is internalized off-exchange before
your resting order ever sees it (PFOF); (b) you inherit a *naked* short-gamma/short-vega tail that v8a
deliberately caps with defined-risk spreads; and (c) the honest, adverse-selection-aware Sharpe is on
the order of **1.5–3.0**, nowhere near the v8a backtest's 6.4.

**The high-value version of this idea is not a new desk — it is an execution upgrade to v8a.** Today
v8a *crosses* the spread to enter/exit (paying ~half of a wide ETF-option bid/ask on every leg). If we
instead post *inside* the NBBO and let the market come to us, we capture the spread we currently pay.
On ~180 trades/yr of multi-leg spreads in wide-spread ETF options, that execution alpha is worth
several percent per year with **near-zero added tail risk**. That is the realistic "$1MM options MM"
play: market-maker-style *execution* of the edge we already own, plus a small ring-fenced quoting
pilot to measure live adverse selection before committing capital.

Verdict bullets are in §6.

---

## 1. Why Options MM Structurally Fits a Small Book

### 1.1 Option spreads are wide — in both absolute and relative terms

Equity NBBO spreads on liquid names are sub-penny to a penny (0.5–3 bps of price). Listed *option*
spreads are routinely **5–30% of mid**, and on off-the-run strikes/expiries far worse:

| Instrument | Typical mid | Typical NBBO | Spread % of mid |
|---|---|---|---|
| SPY ATM weekly | $3.00 | 2.99 / 3.01 | ~0.7% |
| XLF 30Δ put, 30 DTE | $0.42 | 0.40 / 0.44 | ~10% |
| XLI 25Δ put, 45 DTE | $0.65 | 0.60 / 0.70 | ~15% |
| SLV back-month call | $0.30 | 0.25 / 0.35 | ~33% |
| Illiquid single-name OTM | $1.20 | 1.05 / 1.35 | ~25% |

The liquidity provider who is *resting* at the bid and the ask, rather than crossing, earns this spread
as compensation. The width is not arbitrage profit lying on the ground — it is the price of three real
risks the dealer warehouses, which is exactly why a small participant can sometimes get paid for them:

1. **Inventory risk is multi-dimensional.** Unlike an equity (delta = 1, no convexity), an option
   carries delta, gamma, vega, theta, and rho. A dealer who buys an option cannot flatten the risk by
   selling "the option" back instantly; they must hedge a vector of greeks in multiple instruments.
   Wider spreads compensate for the cost and residual error of that hedging (§2).

2. **Adverse selection.** Option order flow is, on average, *informed* — protective put buying ahead
   of a move, call buying ahead of news, vol buying ahead of earnings. Garleanu, Pedersen & Poteshman
   (2009), *Demand-Based Option Pricing* (RFS), formalize this: end-user net demand pressure pushes
   option prices away from the Black–Scholes/no-arbitrage value precisely because intermediaries
   **cannot perfectly hedge** and therefore charge a premium that scales with the un-hedgeable
   inventory they are forced to hold. This demand-pressure premium *is* the volatility risk premium and
   *is* the market maker's spread — they are two views of one quantity.

3. **Discreteness / capacity.** Many strikes and expiries trade a handful of contracts a day. A dealer
   posting two-sided quotes there ties up margin and attention for thin flow, so they quote lazily
   (wide) or not at all.

### 1.2 Why being small is an advantage here

The headline names — SPX, SPY, QQQ, and the front-month of AAPL/TSLA/NVDA — are owned by Citadel
Securities, Susquehanna (SIG), Jane Street, Optiver, and IMC. Competition there is a **latency and
order-flow arms race**: sub-penny price improvement, co-location, payment for order flow, and
microsecond requoting. A $1MM book has *no* edge in that game and will simply be the slow resting order
that informed sweeps run over.

But the big MMs are economically rational: they concentrate where volume (and PFOF revenue) is highest.
They do **not** bother resting tight two-sided quotes on an XLI March 25Δ put or an SLV back-month call.
In those corners:

- The marginal liquidity provider is *absent*, so the NBBO is structurally wide (the 10–33% spreads
  above).
- A small, patient participant can post **inside** that wide spread (e.g. quote 0.42/0.66 against a
  0.40/0.70 market), improve the NBBO, win queue priority, and *still* capture far more edge per
  contract than a Citadel quote ever earns in SPX.
- Size is not the constraint — at these volumes $1MM is more than enough to be the whole resting book
  on a given strike. The constraint is risk warehousing and adverse selection, not capital.

This is the classic small-MM thesis: **trade where you are paid the most per unit of risk, which is
exactly where the giants find it uneconomic to compete.**

### 1.3 The honest structural caveat — PFOF and who you actually trade against

There is a hard wall to put up front. In US listed options, the *good* flow — uninformed retail —
is overwhelmingly **internalized off-exchange** by wholesalers under payment-for-order-flow
arrangements, or sent to exchange price-improvement auctions (PIM/AIM/SUM) where the order's own broker
gets to step in. By the time a resting limit order on a public exchange book is filled, you have very
likely traded against either (a) another market maker, (b) an institution, or (c) an informed trader.
In other words: **the flow that reaches your resting quote is adversely-selected residual.** The 10–30%
headline spread overstates your realized edge, because the easy half of it never touches your order.

A $1MM account is *not* a registered exchange market maker — it has no quoting obligations, no maker
rebates, no exchange membership, no Series 57 / JBO structure. It is a Portfolio-Margin retail or small
prop account posting marketable-and-passive limit orders. That is fine for the niche thesis above
(patient inside-the-spread liquidity in names the giants ignore), but it means we must model adverse
selection *aggressively* and never assume we capture the quoted half-spread. §5's fill model is built
around this.

---

## 2. The Greeks Problem — the actual core of options-MM P&L

### 2.1 Why this is fundamentally harder than equity MM

An equity market maker runs a **delta-1** inventory: the only risk is that the price drifts while they
hold, and they flatten by selling the shares. One instrument, one risk, one hedge.

An options market maker's inventory is a *portfolio of greeks*:

- **Delta (∂V/∂S):** directional exposure to the underlying. Must be hedged or you are just punting
  direction.
- **Gamma (∂²V/∂S²):** how fast delta changes as S moves — the convexity that forces *re*-hedging.
- **Vega (∂V/∂σ):** exposure to implied-vol level. Un-hedgeable except with other options.
- **Theta (∂V/∂t):** time decay — rent you collect (if net short) or pay (if net long).
- **Rho:** rates exposure — usually third-order for short-dated books.

The job is to keep the *book* delta-neutral continuously while managing the residual gamma/vega/theta
profile. You cannot be neutral in everything: quoting two-sided, you accumulate one-sided inventory
because customer flow is one-directional (they buy puts for protection → you end up **short puts → short
gamma, short vega, long the crash**). That residual profile is where you live or die.

### 2.2 The delta-hedging workflow

1. **Quote** two-sided on N strikes, size capped per strike.
2. **On each fill**, compute the position's delta and immediately hedge it in the underlying:
   buy/sell shares (or futures for index) to bring *book* delta back toward zero. You pay the
   underlying's half-spread + commission on this hedge.
3. **As S moves**, your option delta changes (that's gamma). Re-hedge at intervals to keep |book delta|
   under a band. Each re-hedge again pays underlying half-spread + commission.
4. **Manage vega/gamma inventory** by skewing quotes: when you are getting too short puts, lean your
   quotes (raise both bid and ask on puts) to discourage more selling-to-you and encourage buying-from-
   you — the Avellaneda–Stoikov reservation-price shift, generalized to a greek (§5.4).
5. **Roll/close** inventory near expiry to avoid pin and assignment risk (§6.4).

### 2.3 The gamma–theta–vega P&L identity (this *is* the business)

For a delta-hedged option position, the P&L over a small interval dt is, to second order:

```
dPnL ≈ 0.5 · Γ · (dS)²        ← realized move captured by convexity
       − 0.5 · Γ · S² · σ_impl² · dt   ← theta, i.e. the implied move you paid/collected for
       + Vega · dσ_impl        ← mark-to-market of implied-vol changes
       − (hedging transaction costs)
       − (discrete-hedging error)
       − (adverse-selection markout on fills)
       + (spread captured on fills)
```

The first two terms collapse to the famous **realized-vs-implied variance** relationship:

```
dPnL_hedged ≈ 0.5 · Γ · S² · (σ_realized² − σ_implied²) · dt   (+ vega + costs + spread)
```

- A **long-gamma** MM (net long options) *gamma-scalps*: the convexity lets them buy-low/sell-high as
  they re-hedge, earning `0.5 Γ (dS)²`; they profit when **realized vol > implied vol**, and pay theta
  as rent. (Reference treatment: Sinclair, *Volatility Trading*, 2nd ed., ch. on gamma scalping;
  Natenberg, *Option Volatility & Pricing*.)
- A **short-gamma** MM (net short options — the usual state, because customers are net long options)
  has the signs flipped: they *collect* theta as rent, but their re-hedging is **buy-high/sell-low**
  (negative gamma scalping = bleed). They profit when **realized vol < implied vol** — i.e. when the
  market is calmer than the vol they sold. This is precisely the **volatility risk premium**, and it is
  the *same edge* v8a harvests with credit spreads. An options-MM book run net-short is a continuous,
  finer-grained, *un-capped* version of v8a.

So the full MM P&L decomposition is:

```
MM P&L = spread capture
       + theta collected (if net short)
       − negative-gamma hedging losses (whipsaw)
       − vega mark-to-market (vol regime risk)
       − transaction & financing costs
       − adverse-selection markouts
```

A profitable short-vol MM book needs: **spread capture + theta > gamma hedging losses + adverse
selection + costs**, with vega risk kept inside the capital buffer.

### 2.4 The cost of delta-hedging (quantified)

Two distinct costs:

**(a) Transaction cost per re-hedge.** Each hedge crosses the underlying's spread and pays commission.
- SPY/QQQ/IWM/GLD/SLV/XLF/XLI underlyings have tight ETF spreads (0.5–2 bps); index uses ES futures
  (~0.25–0.5 tick). Per re-hedge cost is small in % terms but **frequency** kills you: a short-gamma
  book in a choppy tape re-hedges constantly.
- Boyle & Emanuel (1980) give the discrete-hedging error: hedging at finite intervals Δt instead of
  continuously leaves a residual P&L with **variance ∝ Γ² σ⁴ S⁴ Δt**. Halving the hedge interval halves
  the error variance but doubles the transaction cost. There is an optimal hedge frequency
  (Leland 1985; Whalley & Wilmott 1997 — the "hedging bandwidth" / no-transaction-cost band): you only
  re-hedge when |delta| breaches a band whose width grows with transaction cost and gamma. A small MM
  *must* hedge in bands, not continuously, or commissions eat the edge.

**(b) Whipsaw / negative-gamma bleed.** When short gamma, every band-breach re-hedge locks in a
buy-high-sell-low loss. In a trendless-but-jittery tape this is "death by a thousand cuts." This is the
single largest controllable cost and it is *path-dependent* — it does not show up in any EOD backtest
(see §5's granularity warning).

### 2.5 Gamma × theta interaction — the trade we are actually putting on

The book is short gamma and short vega, collecting theta. We *want* calm: realized vol below the implied
vol embedded in the spreads we sold. We *lose* on jumps and on sustained high realized vol, because then
`0.5 Γ S² (σ_real² − σ_impl²) dt` goes against us faster than theta accrues, and the negative gamma
forces costly re-hedging into the move. This is structurally identical to v8a's risk: v8a's Monte Carlo
found exactly one kill scenario — **"vol explosion (VIX 80): 100% breach."** An MM book has the *same*
single point of failure, but **worse**, because the positions are naked/continuous rather than capped by
defined-risk spread wings (§6.4).

---

## 3. Capital / Margin — what $1MM actually controls

### 3.1 Reg-T vs Portfolio Margin

**Reg-T (the default) is unusable for an options MM book.**
- Naked short option margin ≈ max( 20% × underlying − OTM amount, 10% × underlying ) + premium, per
  contract. Roughly 2–5× notional buying power but with **no cross-netting** of offsetting risk.
- Reg-T margins each leg in isolation: a delta-neutral, gamma-hedged book of longs and shorts is
  charged as if the hedges did not exist. This makes a real two-sided book impossibly capital-hungry.
- Defined-risk spreads are margined at max loss (good), which is exactly why v8a uses spreads — but a
  *quoting* book is not all neat verticals.

**Portfolio Margin (PM) is mandatory for this to work.**
- Eligibility: FINRA minimum $100k–$150k equity (most brokers gate at **$125k+**; IBKR, TastyTrade,
  Schwab/TOS). $1MM clears this comfortably and keeps a buffer above the maintenance floor (drop below
  and you are force-converted to Reg-T mid-book — a real operational risk to manage).
- Method: risk-based (TIMS, the OCC's options-clearing methodology; SPAN-like). The broker shocks the
  whole portfolio across a grid of underlying moves — typically **−12% / +10%** for broad-based indices,
  **±15%** for equities/most ETFs, with implied-vol shifts layered in — and charges the **worst-case
  loss** in that grid as margin.
- Consequence: a **delta-neutral, well-hedged** book nets enormously. PM charges you essentially for the
  *convexity tail* — the gamma/vega P&L at the edges of the shock grid — not the gross notional. Typical
  effective leverage is **~6×** for a balanced book, and more for a tightly delta-hedged one.

### 3.2 How much can $1MM quote?

The binding constraint is **not** the number of strikes N — it is the **aggregate stressed loss** of
the book in the PM shock grid.

- Rough budget: keep the PM-stress loss (e.g. underlying −12%/+10% with vol +X pts) below **~40–50% of
  net liquidation value**, leaving the rest as buffer for intraday moves and to stay clear of the PM
  minimum. So at $1MM, design the book so its worst-grid-point loss is **≤ ~$400–500k**.
- For a delta-neutral short-vol book, that stress loss is dominated by short gamma (the −12% point) and
  short vega (vol-up point). Each short option you quote adds to that tail. So you can quote two-sided
  across **dozens** of mid-liquidity strikes *as long as* the aggregate down-and-vol-up scenario stays
  inside the budget — which in practice means actively hedging delta and capping net short gamma/vega,
  not counting strikes.
- Gross option notional supportable: a well-hedged delta-neutral book at $1MM PM can warehouse on the
  order of **$2–4MM gross option notional** before the stress tail eats the buffer. Naked, undhedged,
  that number collapses toward Reg-T-like levels.

**Net liquidity to quote 2-sided on N strikes:** there is no clean per-strike number — it is the
portfolio stress loss that matters. The practical rule for a $1MM PM book: **size each strike so that
even if the entire book goes maximally one-directional in the down/vol-up scenario, the loss stays under
~half of net liq.** That typically lands at a few hundred contracts of *net* short gamma across the
book, spread over 20–60 quoted strikes depending on their gamma/vega.

### 3.3 Operational/regulatory notes at $1MM

- You are a PM retail/small-prop account, **not** a registered MM: no quoting obligations, no maker
  rebates, no exchange membership. You compete in the public-book queue without rebates — another reason
  realized edge < quoted half-spread.
- High message rates (constant requoting) can hit broker order-throttling or fees; budget for it.
- PDT rules are irrelevant at $1MM (well above $25k), but the **PM maintenance minimum** is a live
  constraint — a drawdown that takes equity under the broker's PM floor triggers forced Reg-T
  conversion and a margin call at the worst possible time.

---

## 4. The Realistic Niche for $1MM

### 4.1 What to avoid

- **SPX / SPY / QQQ 0DTE and front-month ATM:** owned by Citadel/SIG/Jane Street/Optiver/IMC. Penny/
  sub-penny competition, latency arms race, sweep flow that is informed on the second-to-second
  horizon. We have the *data* here (CBOE hourly SPX 0–3DTE, §5) but we have **no structural edge**. Do
  not quote here.
- **Meme single names (TSLA/NVDA/GME-type):** wide spreads, yes, but the spread is wide *because* the
  adverse selection and jump risk are extreme. You are being paid for tail risk you do not want.

### 4.2 Where $1MM can actually be paid

**Tier 1 — mid-liquidity ETF options on our own VRP underliers (the bullseye).**
XLF, XLI, GLD, SLV, IWM, EEM. These have:
- Structurally wide spreads (10–33% of mid on off-ATM strikes — see §1.1) because the giants ignore
  them.
- Enough genuine two-sided flow to get filled.
- **And we already have the VRP/dealer-GEX signal and the data pipeline for them** (v8a streams 3–6:
  XLF 22.6%, XLI 15.9%, GLD 14.2%, SLV 12.6% of Sharpe). This is the decisive advantage.

**Tier 2 — off-the-run strikes/expiries of SPY/QQQ.** Back-month, far-OTM, odd expiries where the front-
month MMs are not resting tight. Wider spreads, less competition, but more pin/liquidity risk into
expiry.

**Tier 3 — mid-cap single-stock options with lazy quotes.** Possible but adverse selection (earnings,
M&A, informed flow) is the dominant risk and we have no edge there. Only with an explicit per-name
catalyst calendar to *stand down* before events. Not recommended for an initial deployment.

### 4.3 The defensible thesis: *informed* market making, not pure spread capture

A pure spread-capture MM with no view is a latency/queue game we lose. But we are not view-less — for
exactly the Tier-1 underliers we have a **VRP / dealer-GEX signal** (the entire v8a thesis: 81.3% of its
Sharpe is non-SPX, from XLF/XLI/GLD/SLV where "different dealer flow → VRP edge survives"). So we can
**skew our two-sided quotes toward the side the signal says is rich**:

- When VRP says puts are rich (implied >> our realized forecast), lean to *sell* puts inside the spread
  (raise our put bid less, our put ask more — invite the customer to lift our offer / hit our bid on the
  side we want).
- This converts market making from a pure microstructure game into **spread capture + a directional vol
  lean driven by alpha we already validated.** That overlay is what makes a $1MM book competitive: we
  are not faster than Citadel, but in XLI puts we are *better-informed about fair vol* than the lazy
  resting quote we are improving on.

This is the Stoikov–Sağlam (2009) "option market making under inventory risk" picture with an alpha
term added to the reservation price (§5.4).

### 4.4 The single most important reframing

At $1MM, the highest-EV use of "MM technique" is **not** a standalone quoting desk — it is upgrading
**v8a's execution** from spread-crossing to spread-capturing:

- v8a today *crosses* to enter/exit credit spreads and calendars, paying ~half of a wide ETF-option
  bid/ask on every leg, every trade.
- If v8a instead **posts inside the NBBO** on entry (and on profit-taking exits) and lets the market come
  to it, it *captures* the spread it currently pays.
- On ~180 trades/yr × 2–4 legs × 10–30%-wide ETF spreads, recovering even half the spread is worth a
  meaningful multi-percent uplift on the existing book — **with essentially no new tail risk**, because
  the positions and risk limits are unchanged; only the execution style changed.

That is the realistic "$1MM options market making" program: MM-style *execution* of an edge we already
own, plus a small ring-fenced inside-the-spread quoting pilot to measure live adverse selection.

---

## 5. How to Backtest Options MM with Our Data

### 5.1 What we actually have (verified against the repo)

- **CBOE DuckDB export** (`data/cboe_duckdb/spx/...`): per-strike rows with
  `bid_open/high/low/close`, `ask_open/high/low/close`, **`bid_size`/`ask_size`** (quoted depth!),
  full greeks (`delta/gamma/theta/vega/rho`), `implied_volatility`, `open_interest`,
  `trade_volume`, `high_px/low_px/close_px/open_px`, and **`underlying_bid`/`underlying_ask`/
  `underlying_price`**, stamped with `quote_timestamp`. Granularity is **HOURLY — 8 snapshots/day**
  (10:00, 11:00, 12:00, 13:00, 14:00, 15:00, 16:00, 16:15). Coverage: SPX **0DTE and 1–3DTE**, with
  **14 clean months (Apr 2023 – May 2024)** after the underlying-price-=-0 data fix (per
  `CBOE_DATA_DIAGNOSIS.md`).
- **IronVault** `options_cache.db`: ~276K contracts / 6.3M option-days, 2018–2024, real bid/ask
  preserved, across the v8a underliers (SPY/QQQ/XLF/XLI/GLD/SLV). This is **EOD** (the v8a backtester
  uses "sparse exit-date P&L"), not intraday.

**This combination tells us exactly what is and is not backtestable**, which is the crux of the section.

### 5.2 The fill model

The core MM backtest loop, per bar t:

1. **Observe NBBO** for each quoted strike from `bid_close`/`ask_close` (and the bar's `bid_low`/
   `ask_high` for the touch). Read quoted depth from `bid_size`/`ask_size`.
2. **Post inside the spread:** our bid' = `bid + δ`, our ask' = `ask − δ`, for a chosen tick step δ and
   size = min(our size, fraction of displayed `*_size`). This improves the NBBO and earns queue
   priority on the public book.
3. **Fill rule (conservative — the honest version):** we are filled on our bid' only if, during the
   bar, the market **traded *through* our price** — i.e. `low_px ≤ bid'` *and* `trade_volume > 0`,
   meaning a print occurred at or below where we were resting and we were not merely the marginal quote.
   Symmetrically for our ask' vs `high_px`. We assume we capture a fraction of `trade_volume`
   proportional to `our_size / (our_size + displayed_size)` (queue position proxy). **Do not** assume we
   capture flow that merely touched the NBBO without trading through — that models the queue + the fact
   that the easy flow is internalized off-exchange (§1.3).
4. **Adverse-selection markout (the metric that matters):** after a fill at bar t, mark the position at
   bar t+1 (and t+k) mid. If we bought and the next-bar mid fell, we book the markout loss — we bought
   from someone better-informed. Report **realized P&L decomposed into spread captured vs markout
   given back.** A naive backtest that books the full half-spread and ignores markout will look like
   the v8a 6.4 Sharpe and be a fiction. The markout series *is* the adverse-selection cost and is the
   single most important output.
5. **Delta-hedge:** on each fill, hedge the resulting book delta in the underlying at
   `underlying_ask`/`underlying_bid` (pay the underlying half-spread) + commission ($0.65/contract +
   exchange fees per v8a's model; ETF shares at per-share commission). Re-hedge each subsequent bar to
   pull |book delta| inside a band (Leland/Whalley–Wilmott bandwidth, §2.4) — do **not** re-hedge to
   exactly zero every bar or transaction costs explode.
6. **Track the greek P&L:** at each bar accrue theta, mark vega against `implied_volatility` changes,
   and accumulate the realized gamma-scalp P&L = hedge trades' realized P&L. Reconcile against the
   `0.5 Γ S² (σ_real² − σ_impl²) dt` identity (§2.3) as a sanity check.
7. **Inventory control:** cap net book gamma/vega; skew quotes via the reservation-price shift (§5.4)
   as inventory builds.

### 5.3 Minimum viable data granularity — and the hard limit of what we have

The MM backtest needs, per strike: **two-sided quotes + a trade/volume series + the underlying price**,
at a cadence fine enough that "we posted inside, the market traded through" is a *meaningful* event and
that intrabar delta-hedging is representable.

- **EOD (IronVault) is NOT enough.** With one snapshot a day you cannot model intraday fills, you cannot
  model intrabar re-hedging, and you cannot compute markouts. EOD data can only backtest the
  **execution-upgrade thesis** (§4.4): "instead of crossing on entry, assume we posted inside and got
  filled at mid or better when the day's range traded through our limit." That is realistic, valuable,
  and directly applicable to v8a — but it is *not* a market-making backtest.
- **Hourly (CBOE) is the practical floor.** With 8 bars/day we *can* build an honest-ish MM sim with
  intrabar fill + per-bar re-hedge. **But hourly hedging massively understates short-gamma path risk:**
  the negative-gamma whipsaw (§2.4) happens on the minute-to-second scale; a model that only re-hedges
  hourly will *underestimate hedging cost and overestimate Sharpe.* Any hourly-CBOE result must carry a
  loud caveat that it is an **upper bound** on profitability.
- **True fidelity needs 1-minute or trade-and-quote (OPRA/TAQ) data — which we do not currently have.**
  This is a concrete data-acquisition requirement, not a nice-to-have. Flag it: to validate a standalone
  MM desk we need intraday OPRA quotes/trades for the Tier-1 ETF underliers (XLF/XLI/GLD/SLV/IWM), not
  just SPX 0DTE.

### 5.4 The quoting model: Avellaneda–Stoikov, generalized to options

The canonical optimal-MM framework is **Avellaneda & Stoikov (2008), "High-frequency trading in a limit
order book"** (Quantitative Finance). For a single inventory q:

- **Reservation price** (inventory-adjusted fair value):
  `r(s, q, t) = s − q · γ · σ² · (T − t)`
  — as inventory q grows long, you mark your fair value *down* to encourage selling it off.
- **Optimal half-spread:**
  `δ ≈ (γ σ² (T − t)) / 2 + (1/γ) · ln(1 + γ/k)`
  where γ is risk aversion and k is order-flow intensity (how fast quotes get hit).

You then quote `r ± δ` rather than symmetric around mid — inventory automatically skews your two-sided
quotes to mean-revert your position.

**Generalization to an options book** (Stoikov & Sağlam, 2009, *Option market making under inventory
risk*, Review of Derivatives Research): replace the scalar inventory q with the **greek vector**
(net delta/gamma/vega) and σ² with the **covariance of the delta-hedged book's P&L**. The reservation
price shifts in the direction that unwinds the most-exposed greek; the optimal spread widens with gamma
and vega inventory and with vol-of-vol. This is precisely the model to implement in the backtest, and
the natural place to add our **alpha term** (§4.3): bias the reservation price by the VRP/GEX signal so
the book leans toward the side our edge says is rich.

Supporting literature to cite in the build: Ho & Stoll (1981) (original inventory-MM model); Garleanu,
Pedersen & Poteshman (2009) (demand-based option pricing = source of the spread); Boyle & Emanuel
(1980), Leland (1985), Whalley & Wilmott (1997) (discrete delta-hedging cost / bands);
Natenberg and Sinclair (gamma-scalping practitioner treatment).

### 5.5 Backtest deliverables

A credible MM backtest on our data should output, per regime:
1. Spread captured (gross) vs **markout given back** (adverse selection) — net spread P&L.
2. Theta collected vs realized gamma-hedging P&L — the vol-carry P&L.
3. Vega mark-to-market — the vol-regime P&L.
4. Transaction + financing costs.
5. Net P&L, daily distribution, and **a stress overlay** (re-run the worst week of the sample, e.g. any
   vol spike in Apr 2023–May 2024, with hedging only at the hourly grid to expose gap/whipsaw risk).
6. An explicit statement of the granularity caveat (hourly → optimistic).

---

## 6. Verdict

### 6.1 Is standalone options MM viable at $1MM?

**Technically yes, practically marginal, and not recommended as a new desk.** The edge is real and we
own the signal for it, but the realized economics at $1MM are dominated by adverse selection and tail
risk, and they do not beat what v8a already delivers.

### 6.2 Expected P&L — rough, honest, wide ranges

Build it up for the realistic Tier-1 inside-the-spread book (PM at $1MM, delta-hedged, VRP-skewed):

- **Spread capture:** suppose we get filled on ~100 contracts/day round-turn across the book. On a wide
  ETF-option spread we post inside, we might *quote* $0.06–0.10 of half-spread, but **net of markout we
  realistically keep $0.03–0.06 per contract** (adverse selection eats the rest). On ~$2-mid options
  that's ~$3–6/contract. 100 × $5 ≈ **$500/day ≈ $125k/yr** gross spread capture in calm regimes —
  high-variance, and adverse selection in a bad month can halve or erase it.
- **Vol-carry overlay (the VRP lean):** running net-short with the v8a signal stacks the *same* VRP edge
  on top — this is where most of the *return* (and most of the *risk*) is.
- **Base case:** mean ~$400–$800/day in calm tape; **annual ~$80k–$200k (≈ 8–20% on $1MM)** — but with
  a fat left tail: a short-gamma/short-vega book can give back 1–3 months of P&L in a *single* gap day.
- **Sharpe:** in calm regimes the profile is high-Sharpe carry (like v8a), but the **honest,
  adverse-selection-and-no-colocation-aware Sharpe is ~1.5–3.0**, not 6.4. The v8a 6.4 benefits from
  EOD sparse-exit P&L and benign fill assumptions; a live quoting book eating real markouts will not
  replicate it. Anyone who backtests this on hourly data and reports a 6+ Sharpe has not modeled
  adverse selection or sub-hourly gamma whipsaw.

### 6.3 The comparison that actually matters — MM vs just running v8a

| Dimension | v8a credit spreads | Standalone options MM |
|---|---|---|
| Underlying edge | VRP / dealer-GEX | **Same** VRP + microstructure spread capture |
| Trading cadence | ~180 trades/yr, scheduled | Continuous, all-day quoting |
| Tail risk | **Capped** (defined-risk spread wings) | **Naked** short gamma/vega — uncapped |
| Kill scenario | VIX 80 vol-explosion (MC: 100% breach) | **Same, but worse** (no wings) |
| Operational load | Weekly rebalance | Full-time quoting + continuous hedging + infra |
| Adverse selection | Low (we choose when to trade) | **High** (we're the resting target) |
| Honest Sharpe | 6.4 backtest (benign fills) | ~1.5–3.0 (after markout) |
| Capacity | $50M (SLV-bottlenecked at $2M) | Lower; constrained by quoted-name liquidity |

The MM book is essentially **v8a's edge in a more continuous, less-capped, more operationally-demanding,
more adversely-selected wrapper.** At $1MM the marginal *return* over v8a is modest and the marginal
*risk and cost* is large. That is a poor trade.

### 6.4 Main risks

- **Gap / overnight risk:** short gamma into an overnight or open gap = the structural killer. You cannot
  hedge between bars, let alone overnight.
- **Vega blowup:** a vol-regime shift reprices the entire short-vega inventory at once — the v8a "VIX 80"
  scenario, but naked.
- **Pin risk / assignment:** quoting near expiry leaves you with short strikes that may pin at expiration,
  creating uncertain assignment and a delta whipsaw over the weekend.
- **Structural PFOF disadvantage (§1.3):** the good flow is internalized; the resting book gets the
  adversely-selected residual. This is permanent, not a tuning problem.
- **PM-minimum force-conversion:** a drawdown under the broker's PM floor triggers Reg-T conversion and a
  margin call at the worst time.

### 6.5 Recommendation

1. **Do NOT stand up a standalone options-MM desk at $1MM.** The Sharpe is well below v8a, the tail risk
   is worse (naked gamma/vega), and we cannot beat wholesalers for the good flow.
2. **DO adopt MM-style *execution* on v8a immediately** — post inside the NBBO on entries and profit-take
   exits instead of crossing. This captures the spread we currently pay, on ~180 trades/yr of wide-spread
   ETF legs, for a multi-percent uplift with **near-zero added tail risk.** Backtestable *today* on EOD
   IronVault data (§5.3).
3. **DO run a small ring-fenced pilot** (≤ ~$100k, PM) quoting inside-the-spread on **XLF/XLI/SLV** —
   exactly where we have VRP signal and data — with the explicit goal of **measuring live markouts /
   adverse selection** before any scale decision. Use the VRP-skewed Stoikov–Sağlam quoting model (§5.4).
4. **Acquire intraday OPRA quote/trade data** for the Tier-1 ETF underliers before trusting any
   standalone-MM backtest; hourly CBOE data gives an *optimistic upper bound* only (§5.3).

---

## 7. References

- Avellaneda, M. & Stoikov, S. (2008). *High-frequency trading in a limit order book.* Quantitative
  Finance, 8(3), 217–224. — reservation price & optimal spread.
- Stoikov, S. & Sağlam, M. (2009). *Option market making under inventory risk.* Review of Derivatives
  Research, 12(1), 55–79. — A–S generalized to a delta-hedged options book (greek inventory).
- Ho, T. & Stoll, H. (1981). *Optimal dealer pricing under transactions and return uncertainty.* JFE. —
  foundational inventory-based MM model.
- Garleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009). *Demand-Based Option Pricing.* Review of
  Financial Studies, 22(10), 4259–4299. — end-user demand pressure = source of the option spread / VRP.
- Boyle, P. & Emanuel, D. (1980). *Discretely adjusted option hedges.* JFE. — discrete-hedging error
  variance ∝ Γ²σ⁴Δt.
- Leland, H. (1985). *Option pricing and replication with transactions costs.* Journal of Finance. —
  hedging with costs.
- Whalley, A. E. & Wilmott, P. (1997). *An asymptotic analysis of an optimal hedging model with
  transaction costs.* Mathematical Finance. — no-transaction-cost hedging band.
- Sinclair, E. *Volatility Trading* (2nd ed.) & Natenberg, S. *Option Volatility & Pricing.* —
  practitioner treatment of gamma scalping and the gamma–theta trade-off.
- Internal: `V8A_COMPLETE_GUIDE.md`, `CBOE_DATA_DIAGNOSIS.md`, EXP-3150/3151 (dealer-GEX/VRP post-2020),
  EXP-3200 (Monte Carlo vol-explosion kill scenario), EXP-3230 (walk-forward).
```

*Prepared for EXP-MM-3. Research only — no code or data modified.*
