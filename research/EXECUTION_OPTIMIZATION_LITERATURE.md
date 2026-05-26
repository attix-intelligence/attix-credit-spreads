# EXP-3310 — Execution Optimization Literature Review

**Date:** 2026-05-19
**Author:** Maximus research agent
**Objective:** Survey academic and practitioner literature on options-spread execution to identify techniques that could reduce our current **890 bps/yr** transaction-cost drag closer to the theoretical floor.
**Constraint:** Rule Zero — every hypothesis must be testable on IronVault historical data. No HFT/latency-arb techniques (we are not co-located).
**Scope:** 28-DTE put credit spread entries, 7-DTE close, multi-leg combos, US-listed ETF options (SPY/QQQ/XLF/XLI/GLD/SLV).

---

## Current execution stack baseline (EXP-2470)

| Metric | Value |
|---|---:|
| IBKR commission baseline drag | 2221 bps/yr |
| Alpaca commission-free + EXP-2470 stack | **890 bps/yr** |
| Improvement achieved by EXP-2470 | **1331 bps/yr (60%)** |
| Composition of EXP-2470 stack | limit-at-mid, patient pre-close window, route to cheapest underlier, multi-leg combo orders |

**Headroom estimate (theoretical floor):** Muravyev-Pearson (2020) finds effective spread on options is ~40% of quoted spread when midprice timing is exploited. If our remaining 890 bps is dominated by spread crossing (it largely is), there is plausibly 200-400 bps/yr of additional headroom before microstructural hard floor.

**Target for this review:** identify 3–5 techniques that, in combination, could reduce drag by another **200–300 bps/yr** (i.e., to ~600 bps/yr net).

---

## Literature survey — 12 key sources

### Core microstructure of options spreads

**1. Muravyev & Pearson (2020) — "Options Trading Costs Are Lower Than You Think"**
*Review of Financial Studies, 33(11), 4973-5014.*
- Effective half-spread on options is ~40% of quoted half-spread when account is taken of *predictable* midprice variation.
- Mechanism: option midprices have a high-frequency mean-reverting component driven by hedger inventory; patient liquidity demanders capture this by timing.
- **Implication for us:** our limit-at-mid is good, but mid-then-wait-N-seconds may beat mid-now. Quoted-spread benchmarks materially overstate true cost.

**2. Christoffersen, Goyenko, Jacobs, Karoui (2018) — "Illiquidity Premia in the Equity Options Market"**
*Review of Financial Studies, 31(3), 811-851.*
- Documents an illiquidity premium specifically in options; effective spreads vary strongly with moneyness, DTE, and time of day.
- Cross-sectional finding: OTM puts in 25-50 DTE band — exactly our entry zone — have the second-highest illiquidity premia after deep OTM far-dated.
- **Implication for us:** illiquidity is structural in our entry zone; cannot be entirely escaped but can be timed.

**3. Mayhew (2002) — "Competition, Market Structure, and Bid-Ask Spreads in Stock Option Markets"**
*Journal of Finance, 57(2), 931-958.*
- Multi-listing of options across exchanges (CBOE / ISE / PHLX / BOX / NASDAQ Options) reduces effective spreads by ~25%.
- ISE entry effect: when ISE began listing AMEX-traded options in 2000, spreads fell sharply.
- **Implication for us:** SPY/QQQ are listed on all 16+ US options exchanges; route-aware execution that compares NBBO sources can matter. Alpaca's smart router does this, but auditing how often we capture vs miss the better quote is worthwhile.

**4. Battalio, Griffith, Van Ness (2015) — "Do (Should) Brokers Route Limit Orders to Options Exchanges That Purchase Order Flow?"**
*Journal of Financial and Quantitative Analysis, 50(5), 935-959.*
- Maker-taker vs payment-for-order-flow (PFOF) venues yield different execution quality for limit orders.
- For *liquidity-providing* orders, maker-rebate exchanges (CBOE-EDGX, NASDAQ-NOM) yield better fill quality than PFOF venues; for *marketable* orders, the relationship is reversed.
- **Implication for us:** our credit-spread *entries* are limit-providing (at mid). If Alpaca routes them to a PFOF venue (Citadel, Susquehanna, Wolverine), we likely give up rebate without gaining priority. Worth measuring.

### Execution timing and TWAP/VWAP

**5. Almgren & Chriss (2000) — "Optimal Execution of Portfolio Transactions"**
*Journal of Risk, 3, 5-39.*
- Canonical risk-adjusted execution slicing. For instruments with predictable price impact, optimal trade schedule minimizes a weighted sum of expected cost and execution-risk variance.
- **Implication for us:** for 28-DTE entry we have ≥2 trading days of timing flexibility. Slicing entries across multiple bars within the window can reduce impact at the cost of opportunity risk.

**6. Engle, Ferstenberg, Russell (2012) — "Measuring and Modeling Execution Cost and Risk"**
*Journal of Portfolio Management, 38(2), 14-28.*
- Implementation-shortfall decomposition: spread cost + market-impact cost + timing risk + opportunity cost.
- Modern transaction-cost models calibrate impact decay over minutes; this is critical for liquid-but-not-deep instruments like ETF options.
- **Implication for us:** decompose our 890 bps into these four components and target the largest. Likely dominant terms are spread cost and timing risk, with negligible market impact at our current size (sub-$50M).

### Time-of-day and intraday effects

**7. Andersen, Bondarenko, Todorov, Tauchen (2015) — "The Fine Structure of Equity-Index Option Dynamics"**
*Journal of Econometrics, 187(2), 532-546.*
- Intraday SPX vol surface has a U-shape: highest at open and close, calm midday.
- Implied-vol bid-ask widens during open-auction (9:30-9:45) and close-auction (15:55-16:00).
- **Implication for us:** entries should avoid 9:30-9:45 and 15:55-16:00 ET. Optimal window appears to be 14:30-15:30 — late enough for index discovery, early enough to avoid close imbalance.

**8. Bollen & Whaley (2004) — "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?"**
*Journal of Finance, 59(2), 711-753.*
- Net public buying pressure on OTM puts pushes their implied vol higher; this is the structural source of our VRP edge.
- The intraday timing of that buying pressure matters: hedger demand peaks around macro events.
- **Implication for us:** entering *after* hedger demand has peaked (and IV is locally rich) is favorable to entering before. Calendar gating around FOMC/CPI/NFP is one operationalization.

### Adverse selection

**9. Hu (2014) — "Does Option Trading Convey Stock Price Information?"**
*Journal of Financial Economics, 111(3), 625-645.*
- "Informed" option order flow predicts subsequent stock returns; uninformed market makers widen spreads in anticipation of informed flow.
- Adverse-selection component of spreads peaks in the 30 minutes before earnings, FOMC, and major data releases.
- **Implication for us:** entering credit spreads in the hour before known macro events systematically pays adverse-selection cost without any compensating edge for us (our edge is statistical VRP, not informational). Strong case for a calendar gate.

**10. Kacperczyk, Pagnotta (2024) — "Becker Meets Kyle: Inside Insider Trading"**
*Review of Financial Studies, forthcoming (SSRN 3915015).*
- Detection of informed options trading; effective-spread widening of 20-40% in the 60 minutes before announced material events.
- **Implication for us:** confirms #9 with more recent data. Magnitude estimate (20-40% wider effective spread) gives an upper bound for what avoiding event-adjacent entries could save.

### Multi-leg / combo execution

**11. CBOE Combo Book documentation (2023) + Tastytrade research notes (2024)**
- CBOE's COB (Complex Order Book) provides native combo-spread matching. Combo orders avoid leg-risk and frequently fill *between* the legged NBBO.
- Practitioner reports estimate combo orders save 5-15 bps per spread vs leg-by-leg execution because the legged NBBO is wider than the combo NBBO when matched.
- Alpaca routes multi-leg orders to combo books when supported by the destination exchange.
- **Implication for us:** we already use combos (per EXP-2470). Worth auditing whether Alpaca always lands in COB or sometimes falls back to legged execution. A leg-vs-combo log dimension would expose this.

**12. Bjursell, Wang, Webb (2020) — "Trading Activity, Bid-Ask Spreads, and Quoting Strategies"**
*Journal of Futures Markets, 40(4), 537-562.*
- Quoting strategies in spread markets — when to quote inside the COB NBBO to capture order flow vs sit at the displayed quote.
- **Implication for us:** we are a *taker* of combo spreads, not a maker. Less directly applicable but useful background for understanding combo-book dynamics.

### Pin risk and expiration-week effects

**13 (bonus). Ni, Pearson, Poteshman (2005) — "Stock Price Clustering on Option Expiration Dates"**
*Journal of Financial Economics, 78(1), 49-87.*
- Underlying prices cluster near strike prices on option expiry; pin risk is real but small in magnitude for high-volume names.
- **Implication for us:** we close at 7 DTE precisely to avoid pin and gamma. Worth re-checking whether closing at 8-10 DTE (longer profit window) creates material additional pin risk. Probably not for SPY/QQQ at our spread widths, but should be measured.

---

## Decomposition of our 890 bps/yr drag (estimated)

This is an *informed estimate*, not a measured decomposition (the measurement itself is EXP-3311's secondary deliverable):

| Component | Estimated bps/yr | Source |
|---|---:|---|
| Spread crossing (effective half-spread per leg × turnover) | 450 – 550 | Largest driver; aligned with Muravyev-Pearson framework |
| Adverse selection (event-proximate entries) | 80 – 150 | Hu (2014), Kacperczyk-Pagnotta (2024) |
| Timing risk (entering during wide-spread windows) | 60 – 120 | Andersen et al., Christoffersen et al. |
| Combo-fallback (occasional legged execution) | 30 – 80 | CBOE practitioner data |
| Exchange routing (suboptimal NBBO selection) | 20 – 50 | Battalio et al. |
| Residual / unallocated | 30 – 80 | — |
| **Total** | **890** | EXP-2470 measured |

The four bottom rows sum to **190 – 480 bps/yr**, which broadly aligns with the 200–300 bps/yr target if we can address even half of each.

---

## 5 testable hypotheses, ranked by expected impact

### H1 — Calendar gate: avoid entries within 24h of FOMC/CPI/NFP/OpEx
- **Mechanism**: Hu (2014), Kacperczyk-Pagnotta (2024) — adverse-selection spread widening 20-40% in event-proximate windows. Our VRP edge does not compensate.
- **Expected savings**: **80 – 150 bps/yr**
- **Implementation difficulty**: **Low**. We have a FOMC calendar already (`fomc_calendar.py`). Add CPI/NFP via FRED API; OpEx is the third Friday of each month (deterministic).
- **Test design**: backtest v8a on IronVault with and without the gate; measure (a) realized P&L delta, (b) effective-spread proxy delta (entry mid vs daily settle), (c) trade-count impact.
- **Failure mode**: if event windows happen to coincide with high-IV regimes where our edge is also highest, the gate could give up more than it saves. Must verify on real data.

### H2 — Mid-then-patient: replace "limit at mid" with "limit at mid, hold N minutes, re-mid if filled-or-killed"
- **Mechanism**: Muravyev-Pearson (2020) — option midprices mean-revert intra-bar; patient passive captures the reversion.
- **Expected savings**: **60 – 90 bps/yr**
- **Implementation difficulty**: **Low–Medium**. Alpaca supports cancel/replace; needs a state machine with a timeout (e.g., 5 min initial, 5 min retry at new mid, then market-or-skip).
- **Test design**: backtest is approximate (we don't have IronVault intraday tick), but settlement-price vs entry-price proxy is informative. Live forward-test on small sleeve is the gold standard.
- **Failure mode**: opportunity cost — if we wait and miss a fill on a day the market gaps down, we forfeit the trade. Need to log fill-failures, not just fills.

### H3 — Time-of-day entry window: restrict entries to 14:30 – 15:30 ET
- **Mechanism**: Andersen et al. (2015), Christoffersen et al. (2018) — U-shaped intraday liquidity; midday window has narrowest effective spreads on ETF options.
- **Expected savings**: **30 – 50 bps/yr**
- **Implementation difficulty**: **Low**. Clock gate on the entry scheduler.
- **Test design**: backtest by restricting entry timestamp; IronVault has end-of-day chains, so we need to model the time-of-day spread effect via the multipliers in the cited literature. Cleaner test is forward-test.
- **Failure mode**: signal at 10:00 may not be the same signal at 15:00; delaying entry could fold signal into noise. Need to verify edge stability intraday.

### H4 — Combo-vs-legged audit: ensure every order lands in COB
- **Mechanism**: CBOE combo books fill inside the legged NBBO; legged fallback gives up 5-15 bps per spread.
- **Expected savings**: **40 – 80 bps/yr**
- **Implementation difficulty**: **Medium**. Alpaca order-status fields expose whether a combo filled as combo vs as legs; need to log and aggregate. Then experiment with combo-only routing flags.
- **Test design**: forward-test in paper trading; backtest doesn't help because IronVault doesn't expose execution route.
- **Failure mode**: a combo-only flag will reduce fill rate when COB is shallow; opportunity cost again.

### H5 — DTE-aware patience: spread entries across 28→26 DTE window rather than entering on the 28-DTE bar exactly
- **Mechanism**: Almgren-Chriss (2000) — splitting an order across multiple bars reduces market-impact and improves average fill quality, at the cost of timing risk.
- **Expected savings**: **40 – 80 bps/yr**
- **Implementation difficulty**: **Medium**. Requires per-position state (partial fills tracked across days) and entry budgeting.
- **Test design**: backtest two entry rules — "all at 28 DTE" vs "1/3 at 28, 1/3 at 27, 1/3 at 26" — on IronVault. Measure realized P&L delta and Sharpe.
- **Failure mode**: at our small position size (currently sub-$50M), market impact is probably negligible; the savings here may be smaller than the literature suggests. This is the hypothesis most likely to disappoint.

### Combined target

If H1 + H2 + H3 land at the midpoint of their ranges, the combined effect is ~**195 bps/yr**. With H4 partial credit, ~**240 bps/yr**. H5 is "optional, low expected value at our scale."

| Hypothesis | Expected bps/yr | Difficulty | Recommended priority |
|---|---:|---|---|
| H1: Event calendar gate | 80 – 150 | Low | **Immediate (EXP-3311)** |
| H2: Mid-then-patient | 60 – 90 | Low–Medium | Next (EXP-3312 candidate) |
| H3: Time-of-day window | 30 – 50 | Low | Bundle with H2 |
| H4: Combo audit | 40 – 80 | Medium | Live-only test |
| H5: DTE-spread entries | 40 – 80 | Medium | Optional; low expected value at <$50M |

---

## EXP-3311 spec — immediate experiment

### Title
**EXP-3311: Event-proximate entry blackout calendar gate**

### Hypothesis
Restricting v8a entries to dates that are *not* within 24 hours (one trading day) of an FOMC announcement, CPI release, NFP release, or third-Friday OpEx will reduce transaction-cost drag by **80 – 150 bps/yr** without materially reducing the strategy's gross return, because (a) adverse-selection spreads widen 20-40% in those windows (Hu 2014; Kacperczyk-Pagnotta 2024), (b) our edge is statistical VRP and is not concentrated in those windows.

### Setup

- **Codebase touchpoint**: extend the existing FOMC gate (`shared/fomc_calendar.py`) to a unified `event_calendar.py` covering FOMC, CPI, NFP, OpEx.
- **Data**: FOMC dates already in repo; CPI and NFP via FRED API (or hardcoded historical schedule); OpEx is deterministic (third Friday).
- **Backtest engine**: existing v8a portfolio runner.
- **Universe**: all 8 streams (SPY, QQQ, XLF, XLI, GLD, SLV credit spreads + GLD/SLV cal + cross-vol + v5 hedge). Cross-vol and v5_hedge are not options-entry-driven; gate applies only to the 6 options streams.

### Procedure

1. Implement `event_calendar.is_blackout(date, window=(-1, +1))` returning True if `date` is within ±1 trading day of any tracked event.
2. Re-run v8a backtest on IronVault data, 2020-01-01 to 2026-04-30, with two configurations:
   - **Baseline**: current entry logic (no event gate beyond FOMC).
   - **Treatment**: skip entry on any blackout date; signal stays armed and may fire on next non-blackout date.
3. Compute three deltas:
   - **(a) Net P&L delta** (treatment − baseline), in $ and bps/yr.
   - **(b) Effective-spread proxy delta**: for each entry, (entry credit) vs (daily settlement midpoint of the same spread) on the entry date. Difference is a proxy for the adverse-selection component captured.
   - **(c) Trade count delta**: how many entries were skipped. Important for assessing opportunity cost.
4. Sub-analysis: stratify the P&L delta by event type. If FOMC dominates (we already gate FOMC), CPI/NFP/OpEx may be the marginal contribution.
5. Walk-forward replication on 5 folds (matching EXP-2280 protocol) to confirm robustness.

### Success criteria

- **Primary**: net P&L improvement ≥ 50 bps/yr after costs, on pooled data and ≥ 3/5 walk-forward folds.
- **Secondary**: effective-spread proxy delta ≥ 5 bps per spread on event-adjacent dates.
- **Failure**: if treatment reduces gross P&L by more than the bps it saves, abandon the gate or narrow it (e.g., FOMC + NFP only).

### Cost / time estimate

- Engineering: ~4 hours (extend calendar module, plumb into entry logic).
- Backtest runtime: ~30 minutes on existing v8a runner.
- Analysis + writeup: ~2 hours.
- **Total**: half a day of focused work.

### Rule Zero compliance

- All P&L computed against IronVault `options_cache.db` real spread prices.
- No synthetic dates, no fabricated economic events — FRED for CPI/NFP, BLS calendar for past releases, public FOMC minutes for FOMC.
- No counterfactual midprice generation; effective-spread proxy uses real same-day settlements.

### Owner / next step

Spec ready for handoff to Carlos for approval and assignment. Recommend running before EXP-3312 (H2 mid-patience) so that any savings from H1 don't get attributed to H2.

---

## Honesty disclosures

- **No backtests were run** in producing this review. All bps/yr figures are *expectations* informed by the cited papers; actual savings will be smaller than literature midpoints because we already capture some of these effects in EXP-2470.
- **Effect sizes from microstructure papers** typically come from US equity options on liquid names; our universe (SPY/QQQ/XLF/XLI/GLD/SLV) is close but not identical to the samples in those papers. Magnitudes should be discounted by 20-40% for safety.
- **The 890 bps/yr decomposition is an estimate**, not a measurement. Producing a true decomposition is itself worth an experiment (call it EXP-3315) — it would let us prioritize H1-H5 with quantitative confidence rather than literature-informed guesses.
