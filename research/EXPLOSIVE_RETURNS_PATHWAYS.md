# EXP-3310 — Explosive Returns Pathways: Feasibility Study

**Date:** 2026-05-19
**Author:** Maximus research agent
**Status:** Feasibility scoping only. **No backtests run.** Per Rule Zero, every numerical range below is sourced from public literature, exchange data, and practitioner reports — they are guidance ranges, not promises. Each pathway concludes with a data-sourcing checklist required before any backtest is permitted.

---

## TL;DR

| Pathway | Realistic net CAGR ($100K) | Max DD risk | Capacity | Sharpe (lit. ranges) | Verdict vs v8a |
|---|---|---|---|---|---|
| **v8a baseline** | **118%** | **5.1%** | **~$50M** | **6.39** | — |
| **1. Solana on-chain arb / MEV** | 30 – 100% | 30 – 80% | $1 – 5M working capital | 0.5 – 2.5 | Higher gross, far worse risk-adjusted; operationally brittle |
| **2. Crypto basis / funding arb** | 15 – 35% | 15 – 50% | $50 – 500M per venue | 1.5 – 3.5 | Lower mean return; comparable capacity; counterparty tail is unhedgeable |
| **3. 0DTE SPX short gamma** | 20 – 50% | 20 – 80% | $100M – $1B | 0.8 – 1.8 | Lower Sharpe than v8a, larger tails; complementary, not replacement |

**Bottom line:** none of these pathways dominates v8a on a Sharpe basis at our capital scale. The only candidate worth a Rule-Zero-compliant feasibility experiment is **Pathway 2 (basis/funding)** because it has clean data, exchange API access, and a structural (not speculative) edge. Pathways 1 and 3 are documented for completeness but recommended **deprioritized**.

The framing of "100 – 10,000%+ in days/weeks" is inconsistent with the empirical literature for any strategy at $100K – $1M scale that is also durable. Strategies that have produced such returns historically (e.g., 2020 – 2021 Solana memecoin MEV, GME options gamma squeeze) are episodic, non-repeatable, and selection-biased in survivor reports.

---

## Pathway 1 — Solana On-Chain Arbitrage / MEV

### Theoretical edge

- **Triangular DEX arbitrage** across Raydium / Orca / Meteora / Lifinity pools captures price dislocations between USDC pairs and SOL pairs. Edge source: order-flow imbalance + AMM curve fragmentation.
- **Sandwich / JIT liquidity** on Jupiter aggregator routes: insert a transaction before a large user swap, drain a few bps, exit after. Edge source: latency advantage and mempool visibility.
- **CEX – DEX latency arbitrage**: price differences between Binance/Coinbase spot and Solana DEX pools. Edge source: market segmentation and slow-moving on-chain price.

Underlying microstructure: this is **bid-ask spread capture**, not statistical edge. Edge per opportunity is small (1 – 30 bps) but high-frequency.

### Realistic annual return — literature & on-chain data

| Capital | Realistic net CAGR | Notes |
|---|---|---|
| $10K | 50 – 200% | Below institutional searcher minimum; priority fees consume 30 – 60% of gross |
| $100K | 30 – 100% | Forced into mid-tier searchers; competition with Jito tippers compresses edge |
| $1M | 10 – 40% | Must enter top-searcher tier; Jito MEV revenue across all searchers ~$300M/yr (Jito Foundation 2025 reports) — capturing >0.5% is extremely rare for a single operator |

Source basis: Eigenphi MEV dashboards, Jito searcher leaderboards, Flashbots research (Ethereum analogue), Frontier Research's 2024 Solana MEV report.

### Max drawdown risk

- **Smart contract exploit on a pool used in route**: 100% loss of capital parked in that pool (e.g., Cypher, Mango Markets exploits 2022 – 2023).
- **Rug pulls** on niche pools used for multi-hop routes: total loss of any liquidity provided.
- **Toxic flow**: when a faster bot consistently front-runs your transactions, gross can flip negative within hours.
- **Bridge exploits** if cross-chain (Wormhole, Nomad, Multichain — combined ~$1B losses 2022 – 2023).
- **Realistic max DD**: 30 – 80% over any 12-month period for a small operator. Survivorship bias in public reporting hides this.

### AUM capacity before edge decay

- **Hard ceiling ~$5M working capital** for a single operator on Solana DEX arb. Above this, arb sizes that fit available liquidity (typical pool depth $50K – $500K) become a small fraction of capital; capital efficiency collapses.
- **MEV/searcher tier**: $5M – $50M possible but requires building a competing searcher operation against incumbents (Jito-Solana validators, BloXroute, Manifold) who have multi-year R&D leads.

### Infrastructure required

- **Dedicated Solana RPC**: Helius / QuickNode / Triton ($1K – $5K/mo for dedicated, $20K+/mo for co-located)
- **Jito-Solana validator or Block Engine bundle relay access** (revenue-share or direct staking ~$1M+ SOL to run validator)
- **Rust searcher bot**: 6 – 12 months engineering for a competitive bot; or fork open-source frameworks (Jito-Searcher, ellipsis-labs)
- **Capital float**: ~$50K – $200K spread across pools and CEX hot wallets to avoid slippage and enable rebalancing
- **Redundant geographic deployment**: minimum two regions for failover; latency-sensitive
- **24/7 monitoring + on-call**: bugs in production drain capital fast

### Regulatory and operational risks

- **OFAC/SDN screening** required for all counterparty addresses — non-trivial implementation; failure = sanctions exposure.
- **MEV ethics and PR risk**: sandwich attacks extract value from retail; subject to growing community pushback and potential protocol-level mitigations (e.g., Jupiter's "JupSwap shielded" mode reduces sandwichable flow).
- **IRS reporting**: every arb cycle is a taxable event in the US; thousands of transactions per day creates a bookkeeping problem (CoinTracker / TaxBit at scale costs $10K+/yr).
- **Exchange withdrawal limits** to fund hot wallets; KYC requirements; bank de-risking of crypto-active accounts.
- **No customer recourse** if exchange or bridge fails (FTX precedent).

### Rule Zero data sourcing checklist (required before any backtest)

1. Eigenphi / Flashbots historical MEV opportunity dataset (Solana): full priority fee, gross, net per opportunity.
2. Jito bundle submission history (public via Jito API).
3. Raydium / Orca / Meteora pool history (publicly indexable via Helius archive RPC).
4. Reconstruct realistic *competitive* fill rates (not theoretical opportunity counts) — this is the killer assumption that makes most retail MEV backtests dishonest.

### Verdict

Higher gross return than v8a is plausible at $10K. **Risk-adjusted return is far worse**: realistic Sharpe 0.5 – 2.5 vs v8a 6.39 net. Drawdown risk includes total-loss tail (smart contract exploit). Infrastructure cost dominates economics below ~$500K capital.

**Recommend: do not pursue.** The asymmetry is wrong — we'd be trading a 6.39 Sharpe credit spread book for a 1.5 Sharpe high-tail-risk operation in an adversarial environment where we have no edge over incumbents.

---

## Pathway 2 — Crypto Volatility / Basis Arbitrage

Sub-strategies under this umbrella:
- **Perp-spot funding rate arbitrage**: short perpetual, long spot, capture funding (or reverse).
- **CEX – DEX basis**: e.g., Binance perp vs Hyperliquid perp; or CEX spot vs Uniswap V3 LP delta-hedged.
- **Term-structure basis**: Deribit dated future vs perp.
- **Realized vs implied vol** on Deribit options (DVOL premium harvesting).

### Theoretical edge

- **Structural, not speculative**. Funding rate is the market-clearing mechanism for derivatives demand. When perps trade at premium (most bull regimes), funding is positive; cash-and-carry shorts perp + longs spot to harvest.
- Historical perp funding on BTC / ETH has averaged **10 – 30% APR** in 2021 – 2024 (source: Glassnode, Binance Futures funding history, Coinglass aggregator).
- Edge is **persistent** because it reflects retail leverage demand, which is unlikely to vanish.

### Realistic annual return

| Capital | Realistic net CAGR | Notes |
|---|---|---|
| $10K | 15 – 40% | Constrained by minimum trade sizes and gas/fee drag |
| $100K | 15 – 35% | Institutional-rate tiers unlock at $100K+ on Binance/OKX (50 – 80% fee reduction) |
| $1M | 10 – 25% | Approaching meaningful share of OI on tier-2 venues; needs venue diversification |

Sharpe historical ranges per practitioner reports (Galaxy Digital research, 21Shares, Amberdata): **1.5 – 3.5** for delta-neutral basis books in 2021 – 2024. Notably below v8a's 6.39.

### Max drawdown risk

- **Exchange counterparty failure**: FTX (Nov 2022), Mt. Gox, BitMEX OFAC settlement (2020) — **unhedgeable**. A funding arb book held on FTX in Nov 2022 went to zero overnight regardless of position quality.
- **Liquidation cascades**: thin liquidity on perp side during fast moves can blow through stops; if cross-margin breaks, collateral lost on one venue.
- **Stablecoin depeg**: USDC depegged to $0.87 in March 2023 (SVB exposure); USDT has had multiple <$0.95 events. Most basis books are collateralized in stablecoins.
- **Regulatory shutdown**: Binance US, Kraken (SEC settlement Feb 2023), Coinbase (SEC suit June 2023). US persons restricted from offshore perps.
- **Realistic max DD**: 15 – 30% in normal regimes; **50 – 100% tail** if a venue fails.

### AUM capacity before edge decay

- **Per-venue**: $50M – $500M depending on OI and ADV. Top-3 venues (Binance, Bybit, OKX) can absorb $200M+ each.
- **Aggregate**: $1B+ is plausible across 5+ venues with redundancy.
- **Edge compression**: funding rate has compressed from 25%+ APR in 2021 bull to single digits during chop. **Edge is regime-dependent.**

### Infrastructure required

- **API access** to 3 – 5 venues (Binance, Bybit, OKX, Deribit, Hyperliquid)
- **CCXT or direct WebSocket** integration (~2 – 4 weeks engineering)
- **Cross-margin collateral manager**: monitors stablecoin balance across legs; auto-rebalances. Critical and non-trivial.
- **KYC / institutional onboarding**: typically 2 – 8 weeks per venue; minimum $100K – $1M for institutional fee tiers
- **Cold → hot wallet operational flow**: bank → fiat ramp → exchange; multi-day settlement
- **Co-location not required** — funding arb is not latency-sensitive on the position-entry side; latency matters on liquidation defense

### Regulatory and operational risks

- **US persons restricted** from offshore perp venues (CFTC enforcement on BitMEX, Binance). For US-based fund, must use Coinbase Derivatives, CME, or Kraken Futures — significantly worse funding terms.
- **CFTC vs SEC classification** of perpetuals remains unsettled; could shift quickly.
- **Tax treatment**: funding receipts are ordinary income (not 1256 mark-to-market); creates large W-2-style tax burden vs v8a's 60/40 on SPX index options.
- **Stablecoin risk**: USDC issuer (Circle) and USDT issuer (Tether) have regulatory exposure; redemption gates possible.
- **Books-and-records**: SEC custody rule applies if any portion of capital represents customer assets.

### Rule Zero data sourcing checklist

1. **Binance Futures funding rate history** (free API, 8-hourly back to 2019).
2. **Coinglass aggregator** for cross-venue funding (free tier sufficient for backtest).
3. **Deribit DVOL and option chain** (free CSV downloads back to 2020).
4. **Glassnode on-chain stablecoin metrics** for liquidity context.
5. **Realistic execution model**: include taker fees (4 – 6 bps), maker rebates (-1 to -2 bps), funding payment timing (8h ticks on most venues), and stablecoin transfer latency.

### Verdict

The only pathway among the three with a structural edge, clean data, and tractable infrastructure cost.

**Realistic expectation**: 15 – 25% net CAGR at $100K – $1M with Sharpe 1.5 – 3.0 — clearly inferior to v8a on a risk-adjusted basis but uncorrelated (potential portfolio addition rather than replacement).

The **counterparty tail** (one venue failure = significant capital loss) is the dominant risk and is not insurable. Position limits per venue must be sized to make total loss bearable, which structurally caps the strategy's contribution to portfolio NAV.

**Recommend**: small Rule-Zero-compliant feasibility experiment using Binance funding history (free) before any allocation. Cap research budget at one experiment cycle.

---

## Pathway 3 — 0DTE SPX Options (Short Gamma)

### Theoretical edge

- **Variance risk premium concentrated in last 0 – 1 day** to expiry. Per Vasquez et al. (2025, SSRN 5113405), 0DTE SPX volume is ~59% of total SPX option volume; per Dim, Eraker, Vilkov (2023, SSRN 4692190), market-maker net gamma on 0DTE is positive and dampens realized volatility.
- This is **volatility premium harvesting**, not bid-ask spread capture. Edge source: structural demand for tail protection that pays a small risk premium even at 0 DTE.
- Modern research (Terstegge 2025) finds the residual VRP after the 2010s decline materializes **overnight on SPX puts** specifically; the 0DTE intraday window has a smaller premium but high frequency.

### Realistic annual return

| Capital | Realistic net CAGR | Notes |
|---|---|---|
| $10K | 10 – 30% | PDT rule, assignment risk; constrained to small wing structures |
| $100K | 20 – 50% | Iron condors / broken-wing flies sized prudently; per literature, Sharpe 0.8 – 1.5 |
| $1M | 15 – 35% | Tail-risk-dominated; portfolio margin required; one bad day can erase a quarter |

Sources: TastyTrade research (2023 – 2024 0DTE iron condor backtests), CBOE 0DTE research papers, Bondarenko-Bernardi (2024) on intraday VRP, ORATS practitioner data.

### Max drawdown risk

- **Aug 5, 2024 SPX -3% intraday**: simulated 0DTE short-vol books lost 15 – 40% in a single session (per ORATS and practitioner postmortems).
- **Feb 5, 2018 (VIXmageddon)**: not 0DTE but the closest analog for short-vol — XIV terminated, LJM Preservation lost 80%+ in one day.
- **OptionSellers.com (Nov 2018)**: short naked NG strangles wiped customer accounts to negative balances. While different underlier, this is the recurring failure mode for unhedged short-gamma.
- **Realistic max DD**: 20 – 40% in defined-risk wing structures; **50 – 80%+ tail** in undefined-risk structures or under-sized wings.

### AUM capacity before edge decay

- **Very large**: 0DTE SPX volume is $500B+ notional daily (CBOE 2024 data). Capacity at retail-style sizing is $100M – $1B.
- Beyond that, market impact on entry/exit becomes material. Iron condor combo books at >$10M notional per day require careful execution.
- The edge itself has **not visibly decayed** through 2025 despite massive volume growth — Vasquez et al. show customer flow is two-sided, so the VRP residual is preserved.

### Infrastructure required

- **Low infrastructure barrier**: this is the lowest-infra pathway of the three.
- **Brokerage**: IBKR Pro, TastyTrade, or Schwab with portfolio margin enabled ($200K minimum at most prime brokers for PM).
- **Data**: OPRA top-of-book ($200 – $1500/mo depending on use); CBOE LiveVol if backtest infrastructure required (~$3K/mo).
- **No co-location, no private RPC, no custody concerns.** Standard listed-options trading.
- **Position sizing engine**: critical; must enforce hard wing-width caps as % of NAV.

### Regulatory and operational risks

- **Well-regulated environment**: CBOE-listed; SEC and FINRA oversight; standard 1256 60/40 tax treatment (favorable vs Pathway 2 ordinary-income funding).
- **FINRA scrutiny of 0DTE**: 2024 – 2025 reports flagged retail 0DTE losses; future rule changes (margin, PDT, suitability) are possible.
- **No novel regulatory risk** — this is an extension of strategies we already understand.
- **Operational risk** is execution-quality-driven, not custody/counterparty driven.

### Rule Zero data sourcing checklist

1. **IronVault `options_cache.db` SPX coverage**: verify whether 0DTE SPX is in cache. If not, source from CBOE LiveVol or ORATS.
2. **Realistic fill model**: 0DTE bid-ask spreads are wider in % terms than 28-DTE; effective spread vs quoted needs measurement (Muravyev-Pearson 2020 methodology).
3. **Backtest period must include** Feb 2018, March 2020, Aug 2024 for tail-risk calibration.

### Verdict

Lowest infrastructure barrier, well-regulated, tax-advantaged. **But Sharpe is structurally lower than v8a** (0.8 – 1.5 vs 6.39) and the tail is meaningfully worse (Aug 2024 precedent).

**Recommend**: medium-priority candidate for a Rule-Zero-compliant feasibility experiment as a *complementary* stream to v8a, not a replacement. Note that v8a already harvests VRP via 28 – 7 DTE SPY credit spreads; the diversification benefit of adding 0 – 1 DTE SPX is empirical and must be measured (the streams may not be as independent as they appear).

---

## Side-by-side comparison vs v8a

| Dimension | v8a (current) | Pathway 1 (Solana MEV) | Pathway 2 (Crypto basis) | Pathway 3 (0DTE SPX) |
|---|---|---|---|---|
| Net CAGR ($100K) | 118% | 30 – 100% | 15 – 35% | 20 – 50% |
| Sharpe (lit/backtest) | 6.39 | 0.5 – 2.5 | 1.5 – 3.5 | 0.8 – 1.8 |
| Max DD (realized / tail) | 5.1% / ~12% (stress) | 30 – 80% (tail = total loss) | 15 – 30% / 50 – 100% tail | 20 – 40% / 50 – 80% tail |
| Edge type | Volatility risk premium | Bid-ask spread capture | Structural funding demand | Volatility risk premium |
| Capacity | ~$50M (SLV-bottlenecked) | $1 – 5M working capital | $50 – 500M / venue | $100M – $1B |
| Infrastructure cost | Existing (Alpaca + Polygon) | $50K – $500K + 6 – 12 mo eng | $10K – $50K + 2 – 4 mo eng | Existing (broker upgrade only) |
| Reg / op risk | Low (US-listed) | Very high (sanctions, IRS, exploit) | High (US restrictions, custody) | Low (CBOE-listed, 1256) |
| Counterparty tail | Negligible (cleared) | Total (exploit, rug) | Total (exchange failure) | Negligible (cleared) |
| Rule-Zero data ready? | Yes (IronVault) | No (Eigenphi/Jito needed) | Mostly (Binance + Coinglass) | Partial (verify SPX 0DTE coverage) |

---

## Recommendation

1. **Do not pursue Pathway 1 (Solana MEV)**. Risk-adjusted return is materially worse than v8a, infrastructure cost is prohibitive at our scale, and the tail risk (smart contract exploit, sanctions exposure, IRS bookkeeping) is operationally toxic. Public success stories are heavily survivor-biased.
2. **Run a single low-cost Pathway 2 (basis/funding) feasibility experiment** using free Binance funding history. Target: validate whether a delta-neutral funding harvest book can produce ≥10% net CAGR with Sharpe ≥1.5 after realistic fees. If yes, consider a $50K – $100K satellite allocation later — never replace v8a.
3. **Pathway 3 (0DTE SPX) is the most natural extension** of our existing competence, but the empirical question is whether it adds *independent* return on top of v8a's 28 – 7 DTE SPY book. Cheap to test if IronVault has the SPX 0DTE chain; otherwise data acquisition (CBOE LiveVol / ORATS) costs ~$3K to start.

**The headline finding**: v8a's 6.39 Sharpe / 118% CAGR / 5.1% DD is not casually beaten by any of the three pathways. The mental model of "explosive returns in days/weeks" is largely the survivorship bias of crypto cycles and viral options trades; the durable, replicable strategies in each space have Sharpe ratios well below v8a.

The most reliable way to add explosive expected return is not to swap to a worse-Sharpe strategy — it is to **lever v8a** within its drawdown budget. At 5.1% max DD, the strategy has room for additional vol-targeting that current overlays do not consume. That work belongs in a separate experiment (EXP-3320 candidate), not in chasing crypto.

---

## Honesty disclosures

- **Zero backtests were run** in producing this document. Every return range, Sharpe estimate, and capacity number is sourced from the cited literature, exchange data, or practitioner reports. Numbers should be treated as order-of-magnitude guidance.
- **Survivor bias** is severe in Pathways 1 and 2 — public reports of successful operators are not representative.
- **None of these strategies has been tested against IronVault data** as required by Rule Zero. The recommendation to "run a feasibility experiment" assumes that data sourcing checklist is completed first.
