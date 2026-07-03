# EXP-MM-2 — Equity / ETF Market-Making Economics at $1,000,000

**Task:** Can a $1MM retail/prop account profitably *market make* (provide liquidity,
capture the bid/ask spread) in US equities/ETFs?
**Analyst role:** economics / feasibility. No code, no data files — first-principles
microstructure reasoning.
**Date:** 2026-06.
**Bottom line (full verdict in §6):** Liquid US equity/ETF market making at $1MM,
non-colocated, is **not viable** — the tick is too thin, the queue is owned by
colocated HFT, and your fills are adversely selected. The edge lives in *wider-spread*
venues. Ranked best path: **crypto spot MM → options MM → small-cap/niche-ETF
liquidity provision → (distant last) liquid ETF scalping.**

---

## 0. Framing: what "market making" actually means

Market making is not "buy low, sell high over days." It is the business of
**continuously quoting a two-sided market** (a bid and an offer), earning the
**spread** as compensation for two services and two risks:

1. **Immediacy** — you let other people trade *now* instead of waiting. The spread
   is the price of immediacy (Demsetz 1968).
2. **Inventory risk** — when you get hit/lifted you accumulate a position you didn't
   want and must lay off. Holding it exposes you to price moves (Ho–Stoll 1981;
   Stoll 1978).
3. **Adverse selection** — some of the people trading against you *know something you
   don't*. They systematically pick you off. This is the dominant cost in liquid
   names (Glosten–Milgrom 1985; Kyle 1985).
4. **Order-processing / fees** — exchange fees, clearing, data, infra.

The spread you earn must cover (2)+(3)+(4) and leave profit. The entire question of
"can $1MM make money" reduces to: **in which instruments is the quoted spread wider
than the adverse-selection + inventory + fee cost you specifically will bear?** A
non-colocated small player bears *more* adverse-selection cost than a colocated HFT
(worse queue position → you only fill when the move is against you), so you need
instruments where the spread cushion is large enough that this handicap doesn't
matter. That is the whole report in one sentence.

---

## 1. Exchange / venue reality — can a $1MM account even do this?

### 1.1 Maker–taker rebates: who actually gets them?

US equity exchanges run a **maker–taker** fee model:

- **Maker** (adds liquidity = a resting limit order that someone else trades against):
  receives a **rebate**, typically **$0.0020–$0.0030/share** on the big lit venues
  (Nasdaq's standard add tier ≈ **$0.00305**, NYSE Arca, Cboe BZX similar; tiers vary
  by volume).
- **Taker** (removes liquidity = a marketable order): pays a **fee**, typically
  **$0.0030/share**.
- **IEX** is the exception: flat, tiny fee both sides, *no* maker rebate — IEX's pitch
  is the 350µs speed bump that *protects* resting orders from being picked off, i.e.
  it reduces your adverse selection instead of paying you a rebate.

**Critical distinction — do you, the $1MM account, capture the rebate?** It depends
entirely on *how you connect*:

- **Commission-free / PFOF retail brokers (Robinhood, Webull, Alpaca's default,
  most "free" apps): NO.** Your marketable orders are sold as order flow to
  wholesalers (Citadel Securities, Virtu) for **payment for order flow (PFOF)**. Even
  your *limit* orders are typically internalized or routed at the broker's discretion;
  the broker keeps any rebate. You cannot reliably add liquidity to a chosen venue and
  bank the rebate. You are the *product*, not the market maker.
- **Direct Market Access (DMA) brokers with cost-plus / "transparent" pricing: YES.**
  IBKR (Tiered / "IBKR Pro" cost-plus), Lime, Cobra, DAS-driven DMA brokers, etc., let
  you **direct-route** a limit order to a specific venue and **pass the exchange add
  rebate through to you** (net of their commission). This is the only retail-accessible
  path to genuinely earning rebates.

### 1.2 Do you need to be a *registered* Market Maker / broker-dealer?

**No — to earn the maker *add* rebate.** The add rebate is paid by the exchange to the
*member firm* for any order that posts and is then taken; the DMA broker passes it
through. A retail/prop account posting non-marketable limit orders on Nasdaq/Arca/BZX
*does* add liquidity and *does* earn the rebate (via a cost-plus broker). Posting on
IEX earns no rebate but buys speed-bump protection.

**But registered Market Maker status is a different animal**, with obligations and
privileges:

- **Obligations:** continuous two-sided quoting, maximum-spread / minimum-size quoting
  requirements, presence a high % of the day, Reg SHO market-maker exception duties,
  net capital rules (SEC Rule 15c3-1), FINRA membership, compliance/supervision
  overhead.
- **Privileges:** better/elevated rebate tiers, sometimes rebates on *some* removing
  volume, the **bona-fide market maker locate exemption** for short sales, and
  favorable **margin/haircut** treatment.
- **Reality for a $1MM solo/prop shop:** becoming a registered MM (broker-dealer
  registration, exchange MM agreement, clearing relationships, compliance staff, net
  cap) is **not realistic** at this size. The capital is fine; the *fixed
  organizational cost and regulatory burden* are not. So you operate as a
  **non-registered account posting passive limit orders via DMA** — you can earn add
  rebates but you have **no quoting privileges, no locate exemption, and no priority
  benefits**. You compete from the *back* of the queue.

### 1.3 PDT rule and Reg T margin — non-issues at $1MM

- **Pattern Day Trader (PDT):** 4+ day trades in 5 business days flags you and requires
  **≥ $25,000** account equity. At $1MM this is **irrelevant** — cleared by 40×.
- **Reg T margin:** standard margin account → **2:1 overnight, 4:1 intraday**
  day-trading buying power. So $1MM → up to ~**$4MM** intraday gross.
- **Portfolio Margin (PM):** available > $125k (often gated higher in practice). Risk-
  based; effective leverage on a hedged, market-neutral book can reach **~6:1+**. A
  market-neutral MM book (long and short legs roughly offsetting) is exactly what PM
  rewards, so PM is the right account type.
- **The binding constraint is NOT margin.** As §2 shows, even $4–6MM of buying power is
  orders of magnitude short of the *turnover* liquid-ETF MM requires. Leverage doesn't
  save you; it just lets you lose faster.

### 1.4 Realistic venues for a $1MM prop, ranked by fitness for MM

| Venue / broker | Rebate pass-through | DMA / direct route | Notes |
|---|---|---|---|
| **IBKR Pro (Tiered, cost-plus)** | Yes | Yes (SMART or directed) | Best general-purpose retail DMA; passes rebates; PM available; API (TWS) for automation. **Top pick.** |
| **Lime / Cobra / DAS-driven DMA** | Yes | Yes, fast routes | Day-trader DMA, lower latency than IBKR, hot-key/algo friendly. Good for active equity. |
| **Alpaca** | Default route = no; some plans differ | Limited | API-first and great for *prototyping*, but routing/PFOF means weak rebate story. Not a serious MM venue. |
| **Robinhood / Webull / "free" apps** | No | No | PFOF model. **Disqualified** for real MM. |
| **Crypto: Coinbase Adv., Binance, Kraken, OKX** | Maker fee tiers (rebate at high tiers) | Native API | No PDT, no BD registration, 24/7, real spreads. See §3. |
| **Options: any OCC-cleared DMA (IBKR, Tasty, Lime)** | n/a (different fee model) | Yes | Wide spreads = the real edge. See §3. |

**Conclusion of §1:** The *mechanical* ability to post passive limit orders and earn
add rebates exists for a $1MM account **via a cost-plus DMA broker (IBKR Pro / Lime /
Cobra)**. You do *not* need to be a registered MM to earn add rebates, but you also do
*not* get any of the registered MM's structural advantages. You will quote from the
back of the queue with retail-grade latency. Whether that is *profitable* is §2.

---

## 2. The brutal math — passive spread capture on a liquid ETF (SPY)

### 2.1 The setup

Take SPY at **~$600/share**, the most liquid instrument on earth (ADV ≈ 70–80M shares).
Its quoted spread sits at the **minimum tick = $0.01** essentially all day.

- Spread in % terms: `$0.01 / $600 = 0.00167% = 0.167 basis points` round trip.
- **Half-spread** (your theoretical edge per fill vs mid): `$0.005/share = 0.083 bps`.

That is the entire gross prize per round trip *before* costs. It is microscopic. Now
subtract reality.

### 2.2 Why the spread is already "fair" — Glosten–Milgrom

In Glosten–Milgrom (1985), a *competitive* market maker sets the spread so that the
half-spread **exactly equals the expected loss to informed traders**. In equilibrium
the MM earns **zero economic profit**: gains from uninformed (liquidity) traders are
handed back to informed traders via adverse selection. Formally, the half-spread ≈
`P(informed) × E[price move | informed]`.

The punchline: **in a maximally competitive name like SPY, the $0.01 tick is pinned at
the regulatory minimum and is, if anything, *below* the fair adverse-selection
spread.** The market clears not on price (it can't go below 1 tick) but on **queue
priority and speed** — whoever is first in the FIFO queue at each price gets the good
(uninformed) fills; everyone behind them gets the toxic (informed) fills. This is
*precisely* why colocation and the rebate exist: the rebate is the *only* remaining
margin once the spread is tick-constrained, and speed is how you win the rebate-bearing
fills. **A non-colocated player is structurally adversely selected.**

### 2.3 Adverse-selection round-trip model (the user's framing)

Model a round trip as "attempt to capture 1 tick ($0.01), but get adversely selected a
fraction X of the time." When adversely selected, the market runs through your quote
and you lose `k` ticks before you can react/unwind.

```
Net edge per round trip (excluding rebate):
  E = (1 − X)·(+$0.01)  −  X·(k · $0.01)

Breakeven (E = 0):  (1 − X) = X·k   →   X* = 1 / (1 + k)
```

| Loss severity k (ticks lost when picked off) | Breakeven adverse-selection rate X* |
|---|---|
| k = 1 | 0.50 |
| k = 2 | 0.33 |
| k = 3 | 0.25 |

So with `k = 2` (a modest run), you **lose money if you're adversely selected more than
33% of the time.** A non-colo player at the back of the queue in SPY is adversely
selected *far* more than 33% of fills — you fill *only when the queue ahead of you
exhausts*, which happens precisely when there's a one-sided move, i.e. when you're
wrong. Realistically X for a slow player approaches 60–80% on the fills that matter.
**E is negative before you even add fees.**

### 2.4 Now add rebates — why they're the whole game

Add maker rebate `r ≈ $0.0025/share`, earned on each posted fill (entry and exit if
both are passive ⇒ ~$0.005/share total):

```
  E = (1 − X)·($0.01)  −  X·(k·$0.01)  +  $0.005
```

Solve breakeven for k = 2:
```
  (1−X)(0.01) − X(0.02) + 0.005 = 0
  0.015 = 0.03·X   →   X* = 0.50
```

The rebate pushes breakeven adverse selection from **33% → 50%**. That is a *huge*
relative improvement — and it is exactly why every liquid-name MM strategy is, at its
core, a **rebate-harvesting** strategy, not a spread-capture strategy. The spread is
too thin; the rebate is the margin. **But** capturing the rebate reliably requires
winning queue priority (front of FIFO) — which requires speed/colo you don't have. So
even the rebate-improved breakeven of 50% is out of reach for a back-of-queue player
whose realized X is 60–80%.

> **Markout intuition:** institutional MMs measure fill quality by *markout* — where
> mid is 1ms/100ms/1s/5s after your fill. Good (uninformed) fills have flat/positive
> markout; toxic fills have negative markout that swamps the half-spread. Colo HFT +
> PFOF wholesalers harvest the *uninformed* retail flow (flat markout) and leave the
> *informed* lit-book flow (negative markout) for everyone else. You are structurally
> on the wrong side of this sort.

### 2.5 What turnover would $1MM need to net $500–$1,000/day?

Suppose, *generously*, you net **$0.002/share** after adverse selection + fees + rebate
(0.2¢ — already optimistic for non-colo SPY). To net **$1,000/day**:

```
  shares/day = $1,000 / $0.002 = 500,000 shares/day
  notional   = 500,000 × $600  = $300,000,000 traded/day
```

Against $1MM capital that is **300× capital turnover per day**. Even with $4MM Reg-T
intraday buying power, you must flip your entire book ~**75 times/day**, every day,
each flip a *clean* tick. To do 500k shares of SPY you need ≈ **0.7% of total SPY
volume**, sustained — which means being at the *front of the queue* a meaningful
fraction of the day. Back of queue, you simply won't get the fills; front of queue
requires colo. The turnover requirement is **physically inconsistent** with a non-colo
$1MM account.

Flip it around — be conservative on net edge (the honest number for non-colo SPY is
**≤ $0 / share**): then no amount of turnover produces profit; more turnover just
compounds the loss and the fees.

**§2 conclusion:** Passive spread capture in SPY/QQQ at $1MM non-colo is a **negative-
expectancy** activity. The gross prize (0.083 bps half-spread) is smaller than your
adverse-selection handicap, the rebate that would rescue it requires queue priority you
can't win, and the turnover needed for even $1k/day is 300× capital. **Do not do this.**

---

## 3. Where market making actually pays at small scale

The lesson of §2 is mechanical: **go where the spread is wide enough that your latency
handicap is small relative to the spread cushion.** Ranked by feasibility for a $1MM
solo/prop operator:

### 3.1 #1 — Crypto spot MM (most accessible)

**Why it fits $1MM:**
- **Real spreads, no PFOF.** Spot crypto has no payment-for-order-flow; the spread you
  see is the spread you can earn. Majors (BTC/USDT, ETH/USDT) are tight (~1–2 bps) but
  **alt/mid-cap pairs run 10–50+ bps**, and many venues/pairs are *not* saturated by
  HFT.
- **Maker fee structure.** Coinbase Advanced, Binance, Kraken, OKX use maker/taker
  tiers. Low-volume tiers charge a **maker fee** (~0.1–0.4% — *bad*, this is a cost not
  a rebate); high-volume tiers go to **near-zero or actual maker rebates**. A $1MM book
  doing real volume can climb into low-fee/rebate tiers. **Watch this carefully — at
  low tiers the maker fee can exceed a tight-pair spread and turn edge negative.**
- **24/7.** Capital works ~168 hrs/week vs ~32.5 for US equities → ~5× the "at-bats"
  per dollar. Big multiplier on a turnover-limited strategy.
- **No regulatory barrier.** No PDT, no broker-dealer registration, no Reg SHO for spot.
- **Latency is less binding** in non-major pairs (see §4).

**Risks:** exchange counterparty / custody risk (hacks, freezes, insolvency — *not*
SIPC-protected), thinner true liquidity than screen suggests, regulatory whiplash,
inventory risk in a 24/7 market that gaps while you sleep (you *must* automate
inventory limits / kill-switches), and HFT *does* exist in majors. **Verdict: most
accessible niche; start in mid-cap pairs with genuine spread, automate ruthlessly,
respect counterparty risk by spreading across venues.**

### 3.2 #2 — Options MM (highest edge per trade, hardest to run)

**Why the edge is real:**
- Option spreads are **enormous in relative terms**: a nickel-wide market on a $2.00
  option is a **2.5% spread**; dime-wide is 5%. Per-contract edge dwarfs equities.
- Many strikes/expiries are **illiquid** and ignored by the biggest HFTs.

**Why it's hard:**
- You are not making a market in a scalar price; you're making a market in **a
  derivative with greeks**. Get filled and you inherit **delta, gamma, vega, theta** —
  you must **delta-hedge** in the underlying continuously, manage **gamma/pin risk**
  near expiry, and **vega** exposure to vol shifts.
- **Adverse selection is vicious**: option order flow is often *informed* (someone
  buying calls ahead of news). Glosten–Milgrom on steroids.
- Requires a real **pricing/vol-surface model** and risk system. This is a quant
  operation, not a hot-key job.

**Verdict:** the **highest-edge** niche *if* you have the quant chops and risk
discipline. The wide spread means **latency is genuinely not the binding constraint** —
pricing accuracy and greek/risk management are. Best fit for a $1MM operator with
derivatives modeling capability. Start with liquid underlyings (so you can hedge the
delta cheaply) but quote the *less-liquid strikes* (where the spread cushion lives).

### 3.3 #3 — Small-cap / niche-ETF / single-name equity MM

- Single stocks **$5–$50 with 5–20 bps spreads**, or thinly-traded sector/thematic
  ETFs, offer **5–60× the per-dollar spread of SPY**. A $20 stock with a 10 bp spread =
  $0.02 spread, $0.01 half-spread = **5 bps half-spread vs SPY's 0.083 bps** — a ~60×
  fatter cushion.
- The wide spread means your **latency handicap matters far less** (§4).
- **But:** lower ADV (hard to unwind inventory; you can get stuck), **higher idiosyncratic
  / news / halt risk**, single-name informed flow, locate/borrow constraints on the
  short leg (you have **no MM locate exemption**), and you can become a meaningful % of
  volume and move the price against yourself.
- This is best run as **semi-passive liquidity provision blended with short-horizon
  mean-reversion alpha** (hold seconds–minutes), not pure tick-scalping.

**Verdict:** workable in a **narrow, hand-picked universe** with strict inventory and
news risk controls. Mid-tier feasibility — better than liquid ETFs, riskier and lower-
capacity than crypto.

### 3.4 #4 (distant last) — Liquid ETF / large-cap equity scalping

SPY/QQQ/AAPL etc. **See §2. Negative expectancy for non-colo $1MM. Avoid.**

### 3.5 Feasibility ranking summary

| Rank | Niche | Spread cushion | Latency-bound? | Reg barrier | Risk profile | $1MM fit |
|---|---|---|---|---|---|---|
| 1 | **Crypto spot (mid-cap pairs)** | Med–High (10–50bp) | Low (in non-majors) | None | Counterparty/custody | **Best** |
| 2 | **Options (illiquid strikes)** | Very High (1–5%) | Low | Low | Greeks/informed flow | High edge, hard |
| 3 | **Small-cap / niche ETF** | Med (5–20bp) | Medium | Low | News/halt/borrow | Workable, narrow |
| 4 | **Liquid ETF (SPY/QQQ)** | ~0 (0.08bp) | **Extreme** | Low | Adverse selection | **Avoid** |

---

## 4. Competition reality — is latency the binding constraint?

### 4.1 The opposition

Citadel Securities, Virtu, Jane Street, Hudson River, Jump, Tower, etc.:
- **Colocate** servers in the exchange data centers (Mahwah/Carteret/Secaucus),
  **microwave/laser** links between venues, **sub-microsecond** tick-to-trade, FPGA
  matching-logic.
- **Buy retail order flow (PFOF)** — they get first look at the *uninformed* flow
  (flat markout) and internalize it, leaving the *informed* flow on the lit book.
- Win **queue priority** at every price level. In a FIFO, tick-constrained book,
  priority ≈ profit.

### 4.2 Where latency IS the binding constraint (avoid)

**Liquid, tick-constrained, FIFO names (SPY, QQQ, mega-cap single stocks).** Here the
spread is pinned at 1 tick, so the *only* margins are (a) the rebate and (b) avoiding
toxic fills — **both decided by queue position, which is decided by speed.** A
millisecond is the difference between a clean rebate fill and a pick-off. A non-colo
$1MM player **cannot compete** and **should not try.** Latency is decisive.

### 4.3 Where latency is NOT the binding constraint (your opening)

Latency matters in proportion to `(value of being first in queue) / (spread)`. When the
spread is wide, being 5–50ms slower costs you a small fraction of the spread, so:

- **Wide-spread names** (small-cap, niche ETF, illiquid option strikes): a 20bp spread
  dwarfs the sub-bp value of queue priority. Speed stops being decisive; **pricing,
  inventory management, and risk control** become the edge.
- **Non-major crypto pairs / less-trafficked venues:** HFT presence is thinner, infra is
  more level, and holding inventory for seconds–minutes (not microseconds) is viable.
- **Longer-horizon "liquidity provision" that is really short-term mean-reversion
  stat-arb** (hold seconds to minutes): here **predictive alpha** dominates raw speed.
  You're not racing to the front of the queue; you're being paid to take the *other*
  side of transient imbalances and revert. This is the form of "market making" a
  thoughtful $1MM quant can actually win at.
- **Options pricing:** greek/vol-surface accuracy and hedging discipline matter more
  than nanoseconds (though hedging latency still matters somewhat).

**§4 conclusion:** Latency is the binding constraint **only in liquid, tick-constrained
equities** — exactly the arena to avoid. Step into wider-spread instruments and the
binding constraint shifts to **modeling, inventory/risk management, and alpha** — things
a small disciplined operator *can* be good at. Don't fight HFT on its turf (speed);
fight where the turf rewards judgment.

---

## 5. The model that *does* apply at small scale: Avellaneda–Stoikov

For the niches where you *can* play (§3), the right operating framework is **Avellaneda–
Stoikov (2008)** layered on **Ho–Stoll (1981)** inventory theory:

- You don't quote symmetrically around mid. You quote around a **reservation price**
  `r(s,q,t) = s − q·γ·σ²·(T−t)`, which **skews your quotes against your inventory** `q`:
  long inventory ⇒ shave both quotes down to sell faster; short ⇒ raise them. `γ` =
  risk aversion, `σ` = volatility.
- Optimal **total spread** ≈ `γσ²(T−t) + (2/γ)·ln(1 + γ/κ)`, where `κ` captures order-
  flow intensity / how fast fills arrive at a given distance from mid.
- **Reading for the $1MM operator:** your edge is **inventory-aware skewing and
  volatility-aware spread-widening**, not raw speed. In wide-spread instruments this is
  implementable on retail-grade latency. The framework also tells you to **widen quotes
  / pull when σ spikes** — the discipline that prevents the blow-ups that kill small MMs.
- **Glosten–Milgrom / Kyle** tell you *why* you'll be picked off and to **price adverse
  selection into the spread** (and to *step away* from names/times where informed flow
  dominates — earnings, news, the open/close auctions).

**Operational requirements (non-negotiable for any niche):** full automation, hard
**inventory caps**, automated **kill-switch** on σ/PnL/position breaches, per-name and
portfolio risk limits, and continuous **markout monitoring** to detect when your fills
have gone toxic and pull.

---

## 6. VERDICT

**Is equity market making viable at $1MM?**

- **Liquid US equities/ETFs (SPY/QQQ/large-cap), non-colocated: NO.** The tick is
  pinned at $0.01 (0.083 bp half-spread on a $600 ETF), the queue and the rebate are
  owned by colocated HFT, your fills are adversely selected (back-of-queue ⇒ you fill
  when you're wrong), and you'd need ~$300MM/day turnover (~300× capital) just to net
  $1k/day. **Realistic $/day ≈ $0 to negative.** Registered-MM status would help but is
  not realistically attainable for a $1MM solo/prop shop (BD registration, net cap,
  compliance, sponsorship). Don't.

- **In a wider-spread niche: YES, conditionally.** The edge survives where the spread
  cushion exceeds your latency handicap:
  - **Crypto spot MM (mid-cap pairs): most accessible.** Real spreads, no PFOF, 24/7
    (~5× at-bats), no reg barrier, latency non-binding off the majors. Watch maker-fee
    tiers (they can eat tight-pair edge) and counterparty/custody risk. **Realistic
    target for a well-run automated $1MM book: ~$300–$1,500/day in normal conditions,
    high variance, with real drawdown and blow-up risk if inventory limits aren't
    enforced.** This is the recommended starting point.
  - **Options MM (illiquid strikes on liquid underlyings): highest edge per trade**
    (1–5% spreads), latency non-binding, but requires a vol-surface/greek pricing model,
    continuous delta-hedging, and respect for vicious informed flow. Best for an
    operator with derivatives-modeling capability. Highest ceiling; hardest to run.
  - **Small-cap / niche-ETF liquidity provision: workable in a narrow, curated
    universe** (5–20bp spreads, ~60× SPY's cushion), best blended with short-horizon
    mean-reversion alpha. Constrained by ADV, news/halt risk, and no MM locate exemption.

**The single most important reframe:** at $1MM you are **not** in the speed business and
**cannot** win it. You are in the **wide-spread, inventory-aware, risk-managed
liquidity** business (Avellaneda–Stoikov skewing + Glosten–Milgrom adverse-selection
pricing). Pick instruments where judgment, not nanoseconds, is the binding constraint.

**Recommended path:** prototype an **automated crypto spot MM** on mid-cap pairs
(inventory caps + kill-switch from day one), and in parallel scope an **options MM**
capability if the quant/hedging skills exist. Treat liquid US equity ETF MM as a
**closed door**.

---

## 7. Worked examples (the numbers made concrete)

### 7.1 A fully-loaded SPY round trip (why non-colo is negative)

Walk one realistic round trip for a back-of-queue $1MM account on SPY at $600,
posting 100 shares ($60k notional) per clip:

```
GROSS half-spread captured vs mid, per side:        +$0.0050 /sh
Maker add rebate (cost-plus DMA, ~Nasdaq add tier): +$0.0025 /sh
Broker commission (IBKR-style, ~$0.0035/sh):        −$0.0035 /sh
                                                    ----------
Best-case bookable per passive fill:                +$0.0040 /sh   (if flat markout)

Now apply realized markout for a slow player.
Toxic-fill rate X ≈ 0.65; when picked off, ~1.5 ticks move against you (k≈1.5):
  benign  (35%): +$0.0040
  toxic   (65%): you eat 1.5 ticks = −$0.0150, partly offset by rebate +$0.0025
                 ⇒ net −$0.0125 /sh on toxic fills

Expected net per fill = 0.35·(+$0.0040) + 0.65·(−$0.0125)
                      = +$0.00140 − $0.00813
                      = −$0.0067 /sh
```

**Negative.** On 100 shares that's −$0.67/clip. Do 5,000 clips/day chasing volume and
you lose ~**$3,350/day** plus fees — you don't earn $1k/day, you *pay* it. The rebate
and the half-spread are simply too small to survive a 65% toxic-fill rate, and a
non-colo account *will* run hot on toxicity because it only fills when the queue ahead
clears (i.e., during the move against it). This is §2's algebra with realistic inputs.

To flip this positive you'd need X ≤ ~0.42 (k=1.5, with rebate) — achievable only with
front-of-queue priority, i.e., colocation. **Confirmed: closed door.**

### 7.2 A crypto mid-cap pair where the edge flips positive

Contrast with a mid-cap crypto pair, price $5.00, quoted spread **20 bps = $0.010**
(half-spread $0.005 = 10 bps on a $5 coin — i.e. **120× SPY's per-dollar cushion**):

```
GROSS half-spread captured vs mid, per side:        +$0.0050  (10 bps)
Maker FEE at a low tier (~0.10%):                   −$0.0050  (kills it!)  ⚠
Maker FEE at a mid tier (~0.02%):                   −$0.0010
Maker REBATE at a high/VIP tier (~ +0.01%):         +$0.0005

At MID tier, benign fill nets: +$0.0050 − $0.0010 = +$0.0040 (8 bps)
Toxic-fill rate in a less-HFT'd pair ≈ X ≈ 0.45, k ≈ 1 (1 half-spread against):
  benign (55%): +$0.0040
  toxic  (45%): −$0.0050 (give back the half-spread) − $0.0010 fee = −$0.0060

Expected net = 0.55·(+0.0040) + 0.45·(−0.0060)
             = +$0.00220 − $0.00270
             = −$0.0005 /unit   ← still marginal at MID tier!
```

The crypto example is instructive precisely because it's **not automatically a win**:
- At a **low fee tier the maker fee (0.10%) exceeds the entire half-spread** — you lose
  on every fill. *You must reach volume tiers before MM is viable.*
- Even at a mid tier with a 20bp spread, a 45% toxic rate leaves you roughly break-even.
- **What tips it positive:** (a) reaching a **rebate tier** (high-volume VIP), (b)
  picking pairs with **wider spreads (30–50bp)** and *lower* toxicity, (c) **inventory
  skewing** (Avellaneda–Stoikov) so you're not always passively run over, and (d) the
  **24/7 at-bat multiplier**. Redo the mid-tier case with a 40bp spread:

```
GROSS half-spread (20 bps):                         +$0.0100
Mid-tier maker fee:                                 −$0.0010
  benign (55%): +$0.0090
  toxic  (45%): −$0.0100 − $0.0010 = −$0.0110
Expected net = 0.55·(0.0090) + 0.45·(−0.0110) = +$0.00495 − $0.00495 = $0.0000
```

Still knife-edge at 45% toxicity — which is the honest lesson: **even in wide-spread
crypto, profitability hinges on getting toxic-fill rate down (pair selection, inventory
skew, pulling in vol spikes) and fees down (volume tier).** The edge is *available* here
in a way it simply is not in SPY, but it is *earned*, not free. A well-tuned book that
gets toxicity to ~35% and reaches a near-zero/rebate tier on 40–50bp pairs is solidly
positive; a naive one is flat-to-negative.

## 8. Capacity & capital scaling — does $1MM "fit"?

A subtle but decisive point: **MM strategies are capacity-constrained by the *spread
cushion and ADV of the niche*, not by your capital.** $1MM is often *more* than the
viable niches can absorb at the per-name level, which is good (you won't move the price)
but means you must **spread across many names/pairs** to deploy it.

| Niche | Per-name daily capacity (rough) | Names needed to use $1MM | Binding limit |
|---|---|---|---|
| Liquid ETF (SPY) | huge ADV, but ~0 edge | n/a | edge, not capital |
| Small-cap / niche ETF | low ADV ⇒ small clips, you become the volume | 20–50 names | ADV / inventory unwind |
| Crypto mid-cap pairs | moderate; venue/pair depth | 10–30 pairs across venues | venue depth + counterparty caps |
| Options strikes | per-strike OI is small | many strikes | hedging capacity + greeks |

**Implication:** the operation is a **portfolio of many small quoting books**, each
risk-capped, not one big bet. $1MM is deployed as, say, $30–80k of working inventory
across 15–40 instruments, each turning over many times. The constraint you actually hit
is **how many instruments you can model and risk-manage simultaneously**, not buying
power. This reinforces §4: the binding resource at $1MM is **modeling/ops bandwidth**,
not capital or speed.

### 8.1 Honest expected-return framing

For a competently automated, risk-disciplined $1MM book in the viable niches:
- **Good regime:** crypto + options MM can plausibly run at **annualized 20–80%**
  (Sharpe ~2–4 if well-built), i.e. ~**$500–$3,000/day** on good days.
- **Reality of variance:** wide dispersion, real drawdowns, and **tail blow-up risk**
  (a volatility spike while long toxic inventory, an exchange halt/insolvency, a gap
  through your kill-switch). Many retail attempts **net ~zero or negative after fees**
  because they underestimate toxicity and fee tiers (see §7.2) and over-trade.
- **The expected value is conditional on execution quality**, not on the strategy
  existing. The strategy is real; most implementations are not good enough.

---

### References / concepts cited
- **Demsetz (1968)** — spread as the price of immediacy.
- **Stoll (1978); Ho–Stoll (1981)** — inventory-based spread; quote skewing vs inventory.
- **Glosten–Milgrom (1985)** — adverse-selection spread; competitive MM earns ~0 economic profit in liquid names.
- **Kyle (1985)** — informed trading, market depth (Kyle's λ), price impact.
- **Avellaneda–Stoikov (2008)** — reservation price, inventory-aware optimal quoting; the operating framework for small-scale MM.
- Supporting microstructure: maker–taker fee economics, PFOF / wholesaler internalization, markout-based fill-quality measurement, FIFO queue priority, Reg T / Portfolio Margin, PDT (FINRA 4210), Reg SHO MM locate exemption, SEC Rule 15c3-1 net capital.
