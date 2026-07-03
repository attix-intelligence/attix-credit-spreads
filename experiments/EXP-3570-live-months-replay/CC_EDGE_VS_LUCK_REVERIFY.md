# CC_EDGE_VS_LUCK_REVERIFY — Independent redo of the EDGE-vs-LUCK reconciliation

**Author:** cc1 (independent re-verification, no reliance on prior analysis)
**Date:** 2026-07-03
**Data sources (all real, Rule Zero):** Alpaca paper API (account, portfolio history, orders, fills, activities incl. OPEXP/OPASN/OPEXC/OPTRD, open positions), Tradier prod API (balances/history/positions), Railway service env vars (account wiring), Alpaca market-data SPY daily bars (2026-03-20 → 2026-07-02), `results/SPY_haltonly.json` (backtest twin trade list).

---

## VERDICT (summary)

**LUCK — and the backtest twin is additionally INVALID as a replication, so the "−8.3 % vs +39.5 %" comparison never measured edge in the first place.**

Both branches of the task question are true at once:

1. **The backtest does NOT replicate the live scanner** — different regime signal (live: VIX 50d-percentile proxy; twin: ComboRegimeDetector with real VIX/VIX3M — documented in `configs/backtest_exp800.json` fidelity notes), different structure choice (live opened **zero** iron condors; the twin opened 3), different sizing (live 16–20 lots/day in June vs twin 1–8 lots), a live **order-duplication event** (12 identical entries in one day) the twin cannot produce, and breaker behavior that diverged completely (the twin's tiers floored sizing from May onward; the live account traded full size straight through a −31 % drawdown). The twin is therefore not evidence about the live strategy either way.
2. **The live +40 % is not evidence of edge.** It is the surviving branch of a high-variance, massively oversized directional book in a V-shaped up-market:
   - **50 % of the entire quarter's P&L came from one bet** (2026-04-02) that was accidentally duplicated **12×** by the 30-minute scan cadence, putting **~81 % of NAV at max-loss risk** (85 lots, max loss $79,211 on $98k equity, with SPY having closed below the long strike three trading days earlier).
   - Direction hit-rate: **6 right / 2 wrong out of 8 resolved direction decisions** — P(≥6/8 | coin flip) = **14.5 %**. Not statistically distinguishable from chance. Only ~10 independent direction bets exist in the whole track.
   - The June "performance" was a round trip: the Jun-05 bullish bet went to **max loss −$16,218** (assigned) and the Jun-08–12 bearish flip made **+$16,063** — net **−$155** — while producing a **−31.1 % drawdown** (equity $126,613 → $87,241) and daily swings of −28.5 % / +28.0 %.
   - Remove the Apr-02 duplication (keep only the first 8-lot fill) and live April realized P&L is **−$1,233 (≈ −1.2 %)** instead of +$18,668 — the same sign as the twin's April.

**Recommendation: unchanged and reinforced — do NOT scale EXP-800 on the strength of the Apr–Jun live paper track.** The live account's risk process (had it been real money) accepted repeated ~80–95 % NAV max-loss exposure and a −31 % realized drawdown inside a single month.

---

## 1. Which account owns the "+40 %"

| Account | Identity | Inception | Seed | Equity (2026-07-03) | Return |
|---|---|---|---|---|---|
| **Alpaca PAPER** (the "+40 %") | `PA3QWQIZO09S` (env `ALPACA_API_KEY_EXP800` on attix-worker) | funded **2026-03-30** (JNLC $100,000) | $100,000 | **$145,402.59** intraday / $146,993.59 last curve point | **+45.4 % / +47.0 %** |
| Tradier real money | `tradier_6YA42569` | **2026-06-23** (env seed) | $133,230.71 | $133,047.74 (all cash, no open positions, 2 pending orders) | **−0.14 %** |

The Apr–Jun "+39.5 %" claim belongs **entirely to the Alpaca paper account**. The Tradier account did not exist until Jun-23 and has done nothing (−0.14 %).

**Actual broker equity curve (Alpaca portfolio history, 1D):**

| Month | Broker curve | Previously claimed |
|---|---|---|
| 2026-04 | **+17.31 %** (end $117,312) | +21.2 % |
| 2026-05 | **+5.63 %** (end $123,916) | +3.4 % |
| 2026-06 | **+14.06 %** (end $141,345) | +11.3 % |
| Jul 1–3 | +4.00 % (end $146,994) | — |
| **Total** | **+47.0 %** (+42.6 % to Jul-2) | ≈ +39.5 % |

The headline magnitude is real (broker-verified), but the previously reported monthly attribution does not match the broker curve (likely scanner-NAV snapshot timing). More importantly, the **path** was never reported:

- **Max drawdown −31.1 %**: peak $126,613 (Jun-05) → trough $87,241 (Jun-11). At the trough the account was **−12.8 % below inception** after ten weeks.
- Second dip: $131,153 (Jun-16) → $111,498 (Jun-18), −15.0 %.
- Worst daily marks: −28.5 %, −13.5 %, −10.4 %. Best: +28.0 %, +18.1 %, +13.2 % (all in June).
- Daily-return σ = 6.5 % (≈ 104 % annualized vol). The +47 % total is a ~0.45σ quarterly outcome at that volatility — i.e., well inside luck territory.

## 2. Full live trade ledger (decoded from Alpaca fills + expiry/assignment activities)

26 spread positions, all SPY verticals: **15 bull put spreads (bullish), 11 bear call spreads (bearish), 0 iron condors.**
Ledger ties to the penny: option premium cashflow +$108,226, assignment/exercise stock cash −$33,600, fees −$61.41 → realized +$74,565; plus open-position marks −$29,162 = **+$45,403 = broker equity gain**.

| Entry | Type | Direction | Strikes | Expiry | Lots | Credit $ | P&L $ | Resolution |
|---|---|---|---|---|---|---|---|---|
| 03-31 | bear call | BEARISH | 645/657 | 04-17 | 6 | 3,258 | **−3,942** | assigned (max loss) |
| 04-01 | bear call | BEARISH | 663/675 | 04-17 | 5 | 2,225 | **−3,775** | assigned (max loss) |
| 04-02 | bull put | BULLISH | 642/630 | 04-17 | **85** | 22,789 | **+22,789** | expired OTM |
| 04-13 | bull put | BULLISH | 666/654 | 05-01 | 10 | 2,300 | +2,300 | closed ~0 |
| 04-14 | bull put | BULLISH | 672/660 | 05-01 | 9 | 1,296 | +1,296 | closed ~0 |
| 04-28 | bull put | BULLISH | 701/689 | 05-15 | 11 | 2,640 | +2,640 | expired OTM |
| 05-26 | bull put | BULLISH | 731/719 | 06-12 | 9 | — | +432 | closed |
| 05-27 | bull put | BULLISH | 736/724 | 06-12 | 17 | — | +1,105 | closed |
| 05-28 | bull put | BULLISH | 735/723 | 06-12 | 16 | — | +976 | closed |
| 05-29 | bull put | BULLISH | 740/728 | 06-18 | 17 | 2,924 | +2,924 | expired OTM |
| 06-01 | bull put | BULLISH | 741/729 | 06-18 | 17 | 3,060 | +3,060 | expired OTM |
| 06-02 | bull put | BULLISH | 743/731 | 06-18 | 16 | 2,896 | +2,896 | expired OTM |
| 06-03 | bull put | BULLISH | 744/732 | 06-18 | 16 | 2,800 | +2,800 | expired OTM |
| 06-04 | bull put | BULLISH | 739/727 | 06-18 | 16 | 2,992 | +2,992 | expired OTM |
| 06-05 | bull put | BULLISH | 742/730 | 06-26 | 17 | 4,182 | **−16,218** | **assigned at max loss** (SPY 729.35 at expiry) |
| 06-08 | bear call | BEARISH | 752/764 | 06-26 | 18 | — | +4,716 | closed 06-11 |
| 06-09 | bear call | BEARISH | 754/766 | 06-26 | 18 | — | +5,220 | closed 06-23 |
| 06-12 | bear call | BEARISH | 753/765 | 07-02 | 19 | 6,127 | +6,127 | expired OTM |
| 06-16 | bull put | BULLISH | 740/728 | 07-02 | 18 | 3,063 | +3,063 | expired OTM |
| 06-18 | bear call | BEARISH | 756/768 | 07-02 | 18 | 5,526 | +5,526 | expired OTM |
| 06-22 | bear call | BEARISH | 762/774 | 07-10 | 19 | — | +3,211 | closed 06-23 |
| 06-23 | bear call | BEARISH | 759/771 | 07-10 | 19 | — | +1,463 | closed 06-26 |
| 06-24 | bear call | BEARISH | 748/760 | 07-10 | 19 | 6,137 | +247 | OPEN (marked) |
| 06-26 | bear call | BEARISH | 749/761 | 07-17 | 20 | 5,200 | −3,320 | OPEN (marked) |
| 06-29 | bear call | BEARISH | 744/756 | 07-17 | 20 | 8,920 | −3,160 | OPEN (marked) |
| 07-01 | bull put | BULLISH | 732/720 | 07-17 | 16 | 2,768 | +96 | OPEN (marked) |

Per-spread win rate on the 22 closed positions: 19W/3L = 86 % — but the three losses were −$3,942, −$3,775 and **−$16,218 (a full max-loss assignment)**, classic short-vol asymmetry.

### The 2026-04-02 duplication event (single biggest P&L driver)

The live scheduler scans 14×/day at 30-minute slots (`main.py scheduler`). On 2026-04-02 it filled the **identical** 642/630 bull put spread **12 times** — 13:45 UTC (8 lots), then 7 lots at every slot 14:30→19:30 — totaling **85 lots**. Every other day in the whole track has exactly one entry per day, so this was a malfunction (entry-dedup/position-sync failure), not designed pyramiding. Consequences:

- Max loss if SPY < 630 at Apr-17 expiry: **$79,211 = 81 % of NAV**. SPY had closed at 632.02 on Mar-30, three trading days earlier — a ~4 % pullback (the size of the Jun-05 NFP move, which actually happened two months later) would have destroyed the account.
- It paid: +$22,789 = **50 % of the account's total P&L for the quarter**.
- Counterfactual with only the first (intended-size) fill: April realized P&L = −$7,717 (bear calls) + $2,888 + $3,596 = **−$1,233** — negative April, same sign as the backtest twin.

## 3. Direction decisions: hit-rate, independence, concentration

Grouping consecutive same-direction entries into independent direction decisions (the scanner holds one regime state across a cluster):

| # | Decision | Cluster | P&L $ | Call |
|---|---|---|---|---|
| 1 | BEARISH | Mar-31–Apr-01 (11 lots) | −7,717 | WRONG (rally) |
| 2 | BULLISH | Apr-02 (85-lot dup stack) | +22,789 | RIGHT |
| 3 | BULLISH | Apr-13–14 (19 lots) | +3,596 | RIGHT |
| 4 | BULLISH | Apr-28 (11 lots) | +2,640 | RIGHT |
| 5 | BULLISH | May-26–Jun-04 (8 spreads, 124 lots) | +17,185 | RIGHT |
| 6 | BULLISH | Jun-05 (17 lots) | −16,218 | WRONG (NFP dip → max loss) |
| 7 | BEARISH | Jun-08–12 (55 lots) | +16,063 | RIGHT |
| 8 | BULLISH | Jun-16 (18 lots) | +3,063 | RIGHT |
| 9 | BEARISH | Jun-18–29 (5 spreads, 96 lots) | +3,967 | mixed, partly open |
| 10 | BULLISH | Jul-01 (16 lots) | +96 | open |

- **6 right / 2 wrong of 8 resolved.** P(≥6/8 under a fair coin) = **14.5 %** — no statistical evidence of direction skill. The whole quarter contains only ~10 independent bets.
- **Concentration:** decision #2 (the bug-duplicated bet) = 50 % of total P&L. Decisions #6+#7 (the June whipsaw) net to **−$155** while generating the −31 % drawdown.
- **Exposure discipline:** on Jun-05 the open book was 99 bullish lots with aggregate max loss ≈ **$100k ≈ 79 % of NAV** — an exposure level the strategy's own tier breakers exist to prevent. No live breaker intervened at any point through the −31 % June drawdown (entries continued daily at full 16–20-lot size), whereas the twin's tier-1/2 fired in April and floored its sizing for the rest of the window.

## 4. Live vs backtest twin, same dates

| Date/window | LIVE (broker record) | TWIN (`SPY_haltonly.json`) |
|---|---|---|
| Mar-31 | bear call 645/657 ×6 → −3,942 | (window starts Apr-01) |
| Apr-01 | bear call 663/675 ×5 → −3,775 | bear call 669/681 ×4 → stopped −2,189 |
| Apr-02 | **bull put 642/630 ×85 (12 dup fills)** → +22,789 | **iron condor** 642/630 put side ×7 → −4,694 (call wing crushed by rally) |
| Apr-06/07 | no entries | 2 more iron condors ×7/×8 → −4,302 / −3,493 |
| Apr 9–30 | 2 bull puts ×10/×9 + 1 ×11 | 14 bull puts ×1–8 lots (small wins) |
| May | 3 bull puts ×9–17, wins | 5 bull puts ×1–3 lots (breaker-floored) |
| Jun 1–5 | 5 bull puts ×16–17/day, incl. the −16,218 max-loss | no entries Jun 1–12 |
| Jun 8–12 | **flips BEARISH**: 3 bear calls ×18–19 → +16,063 | nothing (then Jun-15 bull put ×1, stopped) |
| Jun 16–29 | 1 bull put + 6 bear calls ×18–20 | 6 bull puts ×1–3 lots (no bear calls at all) |
| **April** | **+17.3 %** | **−10.3 %** |
| **Window** | **+42.6 % (Jul-2), −31.1 % MaxDD** | **−8.3 %, −11.6 % MaxDD** |

Divergence mechanisms, ranked by P&L impact:

1. **Apr-02 structure + size**: twin read "neutral" → 7-lot iron condor (call wing destroyed, −$4,694); live read "bullish" → put-spread-only, and the scheduler bug multiplied it to 85 lots (+$22,789). One day, one signal disagreement plus one bug ≈ **$27.5k ≈ 61 %** of the live-vs-twin gap.
2. **Breaker state**: twin's April losses tripped tier-1/2 → 1–3-lot sizing May–June (~flat). Live's April windfall meant no breaker ever fired → 16–20-lot sizing continued (May–Jun clusters #5, #7, #9 = +$37k gross).
3. **June direction flips**: live's regime proxy flipped bearish Jun-08 and Jun-18 (right in chop); the twin's ComboRegimeDetector never emitted a June bear signal (bull puts only). These are *different algorithms* — the config's own fidelity notes say the live scanner proxies VIX term structure from a VIX 50d percentile because it has no live VIX3M feed, while the twin uses real VIX/VIX3M.

## 5. Conclusions

1. **The +40 % is real and broker-verified** — on the Alpaca **paper** account only. Real money (Tradier, since Jun-23) has done −0.14 %.
2. **The backtest twin is invalid as a twin.** It disagrees with the live scanner on regime state (Apr-02 neutral-vs-bullish; June bull-vs-bear), on structure (ICs live-disabled in practice), on sizing (1–8 lots vs 16–85), and on breaker trajectory. EXP-3570's "−8.3 % vs +39.5 %" therefore quantifies implementation divergence, not strategy validity.
3. **The live track is luck, not demonstrated edge.** ~10 independent direction bets, hit-rate consistent with a coin flip (p = 0.145); half the P&L from a single accidentally 12×-oversized bet risking 81 % of NAV; a −31.1 % intramonth drawdown with a −12.8 %-below-inception trough; a June whipsaw that netted −$155; 104 % annualized daily vol. A strategy with this path repeated across quarters has a high probability of ruin — the observed quarter is the surviving branch.
4. **Neither track supports scaling.** The honest statement is: *the deployed EXP-800 system's live behavior is unreplicated by its backtest and its live results are statistically uninformative about edge.* Fixing the twin to bit-match the live scanner (same regime proxy, same per-scan entry logic incl. dedup, same sizing) is a precondition for any future edge claim — but the live risk record (breaker never firing through −31 % DD, the Apr-02 duplication) needs fixing before the *live* system is trustworthy either.

## Appendix — evidence trail

- Alpaca paper account `PA3QWQIZO09S`: 76 orders (51 filled / 17 expired / 8 canceled), 103 fills, 308 activities (18 OPEXP, 3 OPASN, 3 OPEXC, 6 OPTRD, JNLC $100,000 on 2026-03-30). Raw JSON pulled 2026-07-03 (session scratchpad; not committed — contains no secrets but is bulky and reproducible via the APIs above).
- Assignment records: 2026-04-17 short calls 645/663 assigned, longs 657/675 exercised (OPTRD net −$13,200 gross on stock legs); 2026-06-26 short put 742 assigned ×17, long put 730 exercised (OPTRD net −$20,400).
- Tradier `6YA42569` balances 2026-07-03: total_equity $133,047.74, positions `null`, pending_orders 2; account history 200 events since Jun-23.
- SPY closes: Alpaca market-data v2 daily bars (IEX), 2026-03-20 → 2026-07-02 (72 sessions). Key marks: Mar-30 632.02, Apr-17 710.06, Jun-05 737.45, Jun-26 729.35, Jul-02 744.86.
- Twin trades: `experiments/EXP-3570-live-months-replay/results/SPY_haltonly.json` (34 trades, −8.3 %, MaxDD −11.59 %).
- Ledger reconciliation: +$108,226 (option premium) − $33,600 (assignment stock) − $61.41 (fees) − $29,162 (open marks vs credits) = +$45,403 ✅ equals broker equity $145,402.59 − $100,000.
