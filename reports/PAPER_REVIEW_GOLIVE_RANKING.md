# Paper Trading Review — Go-Live Priority Ranking (Alpaca + IBKR)

**Author:** cc (independent, broker-verified)
**Date:** 2026-07-03
**Data:** Pulled directly from broker APIs on 2026-07-03 — Alpaca paper API for all 9 accounts (account, 1Y daily portfolio history, full order history with legs, full activity ledger incl. expiries/assignments, open positions) and, for IBKR paper (`ibkr_tafintech-p11-paper` / DUO415613): executor API (balance, positions, full order tape with intent metadata + commissions) plus the worker-snapshot equity curve recovered from the attix-dashboard (Jun-09 onward). No internal scanner logs were trusted for P&L. Settlement marks from Alpaca market data. Companions: `experiments/EXP-3570-live-months-replay/CC_EDGE_VS_LUCK_REVERIFY.md` (EXP-800 = LUCK), `reports/IBKR_ASSESSMENT_COMPLETION.md` (IBKR data recovery + executor bug fix).
**Rev 2 (2026-07-03):** IBKR paper upgraded from "not assessable" to a full scorecard and real ranked verdict after data recovery, per Carlos.

---

## Bottom line

**NONE of the ten accounts meet a reasonable go-live bar today.** Not one.

The fleet is nine near-clones of one strategy family (SPY bull put spreads) that all made the same bets in the same quarter — **eight of nine Alpaca accounts held the identical killer trade (SPY 742/730 put spread, entered 2026-06-05, assigned at max loss 2026-06-26)** — plus one broken IBKR pipeline. Aggregate statistical content across the whole fleet is roughly *one* quarter-long bet ("SPY grinds up") with ~5–10 expiry windows. That bet paid, except for one −4 % week (Jun-05 NFP) that put **every single account into a −12 % to −42 % drawdown simultaneously**.

Two accounts deserve continued paper evaluation with priority (EXP-1220, EXP-3311). One urgent flag: **real money is already live (Tradier, exp800_tradier) on the one model formally ruled LUCK, with a Phase-3 cap of 30 contracts and a 14-contract order submitted today.** On this evidence, that deployment should be size-frozen, not scaled.

## Fleet-level findings (why nobody passes)

1. **No independence.** All 9 Alpaca accounts trade SPY short-vol verticals from the same signal core; 8/9 entered the same 2026-06-05 742/730 bull put (P&L −$16.2k / −$16.2k / −$16.2k / −$14.3k / −$6.1k / −$3.9k across accounts). Every equity curve peaked ~Jun-03/05 and troughed Jun-11. Treating them as 9 tracks overstates the evidence ~9×.
2. **No statistical power.** Closed spreads per account: 3–33. Independent expiry windows: ~5–10. Track lengths: 4–14 weeks, one regime (rally + one dip). The only account with directional *decisions* (EXP-800, 11 bear calls) scored 6/8 resolved clusters — p = 14.5 % vs a coin flip.
3. **Short-vol win rates are not edge.** Win rates run 82–100 % by construction; each is one tail event from give-back. EXP-400 is the cleanest illustration: 19W/1L and still only +10.0 % total because the 1 loss (−$16.2k) ate five months of wins — with a **−41.6 % max drawdown**.
4. **Risk process failed fleet-wide in June.** Peak aggregate max-loss exposure (held book, broker-verified entries): EXP-800 **~131 % of NAV**, EXP-400 ~100 %, EXP-401 ~100 %, EXP-1220 ~91 %*, EXP-3303B ~90 %, EXP-3311 ~70 %, EXP-3309 ~56 %, EXP-V8A ~51 %, EXP-503 ~31 % (*upper-bound estimate assuming held-to-expiry; EXP-1220 closes actively, so its realized peak was lower). No account shows breaker-driven size reduction after drawdown; EXP-800/503/1220/3309 kept entering during the Jun-06→15 drawdown window at full size.
5. **Live-ops bugs on the broker record.** EXP-800: the Apr-02 **12× duplicate-entry bug** (85 lots, 81 % of NAV, 50 % of its total P&L). EXP-503: an **orphaned −800-share naked SPY short** sitting in the account right now (−$12.6k unrealized, unmanaged expiry artifact). IBKR: order lifecycle records unusable (see scorecard).
6. **No validated backtest twin.** EXP-3570/EXP-800-BT established the engine twin does not reproduce live EXP-800 behavior (regime signal, structure, sizing all diverge). No other account has a validated twin either. Unreplicated + short + correlated = no basis for capital.

### The June whipsaw, fleet-wide (broker equity curves)

| Account | Return (incep→Jul-3) | MaxDD | Worst day | Best day | Daily vol | Sharpe |
|---|---|---|---|---|---|---|
| EXP-800 | **+45.4 %** | **−31.1 %** | −28.5 % | +28.0 % | 6.5 % | 1.92 |
| EXP-401 | +25.2 % | **−38.6 %** | −29.5 % | +32.2 % | 9.4 % | 1.46 |
| EXP-3311 | +14.7 % | **−40.4 %** | −24.5 % | +28.6 % | 10.7 % | 1.50 |
| EXP-400 | +10.0 % | **−41.6 %** | −31.8 % | +35.0 % | 9.8 % | 1.05 |
| EXP-1220 | +6.2 % | −11.8 % | −10.8 % | +8.8 % | 3.3 % | 0.81 |
| EXP-3309 | +3.6 % | −23.2 % | −15.9 % | +18.2 % | 6.7 % | 0.79 |
| EXP-3303B | +0.2 % | **−41.4 %** | −31.4 % | +34.6 % | 12.7 % | 0.98 |
| EXP-503 | −5.2 % | −13.5 % | −8.4 % | +8.0 % | 2.7 % | −0.39 |
| EXP-V8A | −14.9 % | −21.9 % | −15.8 % | +7.5 % | 4.4 % | −1.50 |
| IBKR (EXP-V8A-IBKR, 3×) | +12.0 % | **−16.6 %**¹ | −9.0 % | +13.1 % | 6.4 % | 3.59² |

¹ Trough $833,937 (Jun-10) vs the $1.0M seed; snapshot curve starts Jun-09, so the Jun-05 NFP week itself is unobserved (observed-window MaxDD −9.0 %). ² 16 daily snapshots only — not comparable to the Alpaca Sharpes.

---

## Per-account scorecards

### EXP-800 — "EXP-400 champion params + tiered breakers" (`paper_exp800.yaml`)
- **Seed $100k (2026-03-30) → $145,403 (+45.4 %).** 68-day curve, 37 spread opens (26 bull put / 11 bear call), 30W/3L closed.
- **Ruled LUCK in the dedicated re-verification:** 50 % of P&L from the Apr-02 12×-duplicated 85-lot entry (81 % of NAV at risk); direction hit-rate p = 0.145 vs coin flip; −31.1 % MaxDD; June whipsaw netted −$155; breakers never fired through the DD; backtest twin non-replicating (−8.3 % on same window).
- Open now: 3 bear calls + 1 bull put (Jul-10/17), unrealized −$6.1k.
- **Verdict: NO.** Blockers: dup-entry bug root-cause+fix, breaker live-fire proof, twin parity, then ≥2 fresh clean quarters. **Urgent: this model is already live on Tradier real money — freeze size (do not use the Phase-3 30-contract cap), pending order today was 14 contracts.**

### EXP-401 — credit spread, 12 % risk, regime-adaptive (`paper_exp401.yaml`)
- Seed $100k (2026-04-20) → $125,231 (+25.2 %). 26 opens, all SPY bull puts, 23W/1L; the 1 loss −$16.2k (the shared Jun-05 trade).
- **−38.6 % MaxDD**, ±30 % single days, peak book ≈ 100 % of NAV (16–18-lot, 12-wide entries stacked daily).
- Best headline after EXP-800, same disease: full-NAV short-put stacking; return is rally beta + surviving Jun-11.
- **Verdict: NO** at current sizing. Would re-qualify only with per-book max-loss cap ≤ ~30 % NAV and 2+ clean quarters.

### EXP-3311 — champion CS+IC with **day-before-NFP gating** (`paper_exp3311.yaml`)
- Seed $100k (2026-05-20) → $114,713 (+14.7 %) in 6 weeks. 8 opens, 7W/0L closed.
- **Its differentiator worked**: the NFP gate skipped the 2026-06-05 entry that max-lossed 8 sibling accounts. That is a real, mechanism-based risk improvement — but it has fired exactly **once** (n=1 event).
- Concerns: sizing ballooned 8→17→33→35→37→38 lots (max loss per trade $33–40k ≈ 30–35 % of NAV); still ate a **−40.4 % MaxDD** on marks despite dodging the realized loss; 31-day track.
- **Verdict: HOLD (evaluate, don't fund).** Blockers: cap sizing (~10 % max-loss/trade), 2+ quarters incl. ≥3 more NFP events, twin validation.

### EXP-1220 — bull puts with dynamic leverage, 5-wide (`paper_exp1220.yaml`)
- Seed $100k (2026-04-20) → $106,155 (+6.2 %). 21 opens / 13 closes, 14W/7L — the **only account whose losses are small by process** (stops fire: typical loser −$40…−$130 vs credits +$550…$900; biggest settled loss −$260).
- 5-wide spreads, 11–20 lots → per-trade max loss ≈ 4–9 % of NAV — the only sane per-trade sizing in the fleet. MaxDD −11.8 % (worst in fleet-crash week but 3–4× shallower than siblings). No dup/orphan anomalies; zero open risk as of Jul-3 (flat book, all closed).
- Weaknesses: modest return, Sharpe 0.81, 53-day track, same one-directional signal family (its June dip shows the correlation), and the deploy configs contemplate 1.5×–5× leverage versions — the 5× would have been fleet-average risk.
- **Verdict: HOLD — top priority for continued evaluation.** Blockers: 2+ more quarters, explicit DD-breaker proof, keep leverage at 1.0–1.5×.

### EXP-3309 — champion CS+IC, entries restricted 15:30–16:00 ET (`paper_exp3309.yaml`)
- Seed $100k (2026-05-20) → $103,586 (+3.6 %). 15 opens, 13W/1L (its Jun-05 loss was −$6.1k at 8 lots — half-sized vs siblings), MaxDD −23.2 %, peak book ~56 % NAV.
- Nothing broken, nothing compelling: 31 days, +3.6 %, −23 % DD.
- **Verdict: HOLD (passive).** Needs the same sizing cap + longer track; below EXP-3311 because it has no demonstrated protective mechanism.

### EXP-400 — champion signal source (dte 15, 2 % OTM, $12 width) (`paper_exp400/…`)
- Seed $100k (2026-04-20) → $109,963 (+10.0 %). 22 opens, 19W/1L, **−41.6 % MaxDD**, peak book ~100 % NAV, ±31–35 % days.
- The purest expression of the champion signal: five months of small wins, one trade gives back everything, survival by two days.
- **Verdict: NO.** +10 % is not compensation for a realized 42 % drawdown; as the signal parent, fix sizing here first if the family is to survive.

### EXP-3303B — champion CS+IC with regime-transition gate (`paper_exp3303b.yaml`)
- Seed $100k (2026-05-21) → $100,243 (**+0.2 %**). 13 opens, 10W/1L, **−41.4 % MaxDD**, −31.4 % worst day, 12.7 % daily vol.
- Round-tripped to zero: its gate did NOT skip the Jun-05 killer (−$14.3k at 15 lots). The one thing it was built to add didn't protect.
- **Verdict: NO.**

### EXP-503 — ML V2 Aggressive sizing overlay (`paper_exp503.yaml`)
- Seed $100k (2026-04-20) → $94,752 (**−5.2 %**), Sharpe −0.39. 20 opens, 19W/1L but small credits (5-wide, 10 lots) that didn't cover the loss + bleed.
- **Live-ops failure: the account currently holds −800 SPY shares naked** (unrealized −$12.6k, growing as SPY rallies) — an expiry/assignment artifact nobody cleaned up; last option trade Jun-30 while the stock leg sat unmanaged.
- **Verdict: NO.** Negative return, no evidence the ML overlay adds anything, and it can't keep its own book clean.

### EXP-V8A (Alpaca) — canonical V8A regime-adaptive CS+IC (`paper_expv8a.yaml`)
- Seed $100k (2026-05-26) → $85,132 (**−14.9 %**) in 4 weeks, MaxDD −21.9 %. 7 opens across SPY/XLF/QQQ (multi-stream book), open positions in 3 tickers, unrealized −$3.6k.
- This is the live incarnation of the already-diagnosed V8A June disaster: EXP-3510/3520/3540 root-caused it to per-stream oversizing/aggregation (canonical engine sizing replay of the same month: +1.6 %, −0.16 % DD). The paper account confirms the deployed scanner ≠ the canonical config.
- **Verdict: NO.** Blocker: deploy-vs-canonical sizing parity before this account means anything.

### IBKR paper — EXP-V8A-IBKR, "VRP Multi-Stream 3× Leverage" (`ibkr_tafintech-p11-paper` / DUO415613)
- **What it is:** Carlos's 2026-05-30 leverage A/B — the parallel sibling of EXP-V8A on identical 4-stream signals (exp1220/qqq_cs/xlf_cs/xli_cs), designed at 3× max-loss/equity on a **$120k NAV baseline** ($360k aggregate max-loss target), accepted expectations +5–7 %/mo, −38 % 1-y MaxDD, 15 % blow-up probability. Live since 2026-06-01, seed $1,000,000 (env-configured; actual Jun-01 NAV unverified).
- **Broker-verified state:** equity **$1,119,728 (+12.0 %)**, zero open positions, all cash. Worker-snapshot equity curve (Jun-09→Jul-03, 17 points): trough **$833,937 (Jun-10) = −16.6 % below seed**; daily swings −9.0 %/+13.1 %; the Jun-01–06 NFP week is unobserved (snapshots begin Jun-09) — broker statements (Flex) required to see how deep it actually went.
- **Trades (forensically recovered):** 24 spread orders, only **4 filled (17 % fill rate)** — SPY 719/714 ×560, QQQ 701/696 ×159 + 702/697 ×333, XLF 49/44 ×547 (last one inferred, not commission-verified) — all bull puts, all expired worthless: **+$50–65k** in credits. 16 rejected stock orders at inception; 4 orders stuck "pending" for weeks (executor lifecycle bug, root-caused and patched — see companion report).
- **Sizing is off-design:** the intended week-1 book was **$1.04M max loss = 2.9× the $360k design target = 104 % of actual NAV**; the filled subset still peaked ≈ $734k (73 % of NAV). The scanner sizes off the real $1M account, not the $120k design baseline — the "3×" experiment is actually running ~9× the intended dollar exposure, saved only by missed fills.
- **The A/B is inconclusive by construction:** IBKR filled 4/24 orders while the Alpaca sibling filled its book — the two legs did not trade the same realized positions, so "+12.0 % vs −14.9 %" says nothing about leverage; it mostly measures which limit orders happened to fill.
- **Verdict: NO** (now on evidence, not absence of it). 4 correlated short-put wins in a chop month, ≥−16.6 % excursion below seed, execution machinery that misses 5 of 6 orders, sizing 2.9× its own design target, and a five-week track. Blockers: deploy the reconciliation fix; fix fill rate (limit pricing/repricing); recalibrate sizing to the design baseline (or update the design); populate `FLEX_TOKEN` and reconcile June against statements; then 2+ clean quarters.

---

## Final ranking (go-live priority)

**Today: fund nothing. GO count = 0.** Priority below is *evaluation* priority — the order in which models should earn live capital if their blockers are cleared and they survive ≥2 further clean paper quarters at capped sizing.

| # | Model | Broker return / MaxDD | Verdict | Rationale (one line) | Blockers before any GO |
|---|---|---|---|---|---|
| 1 | **EXP-1220** | +6.2 % / −11.8 % | **HOLD — top candidate** | Only account with working per-trade risk (4–9 % NAV, stops cut losers small, flat book today) | 2+ more quarters; DD-breaker proof; keep ≤1.5× leverage |
| 2 | **EXP-3311** | +14.7 % / −40.4 % | **HOLD** | NFP gate demonstrably dodged the fleet-killer trade (n=1) | Cap sizing (8→38-lot creep must end); ≥3 more NFP events; twin |
| 3 | EXP-3309 | +3.6 % / −23.2 % | HOLD (passive) | Half-sized the killer trade; otherwise unremarkable | Sizing cap; longer track |
| 4 | EXP-401 | +25.2 % / −38.6 % | NO (re-test resized) | Best clean headline, but 100 % NAV book and −39 % DD | Halve book; 2 clean quarters |
| 5 | EXP-400 | +10.0 % / −41.6 % | NO | Signal parent: 19W/1L and the 1 L ate it all | Family-level sizing redesign |
| 6 | EXP-3303B | +0.2 % / −41.4 % | NO | Its regime gate failed its one test; round-trip to zero | Gate rework or retire |
| 7 | IBKR (EXP-V8A-IBKR, 3×) | +12.0 % / −16.6 %¹ | NO | Active leverage A/B, but 17 % fill rate invalidates it; sizing 2.9× its own design target; 4 wins = chance | Deploy reconciliation fix; fix fill rate; recalibrate to $120k baseline; Flex reconcile June |
| 8 | EXP-800 | +45.4 % / −31.1 % | **NO** | +45 % formally attributed to LUCK + dup bug; twin non-replicating | Dup fix, breaker proof, twin parity — **and freeze the existing Tradier real-money size now** |
| 9 | EXP-503 | −5.2 % / −13.5 % | NO | Negative, ML overlay unproven, orphaned −800 SPY naked short in book | Clean the book; retire or rebuild |
| 10 | EXP-V8A (Alpaca) | −14.9 % / −21.9 % | NO | Known multi-stream oversizing disaster, still deployed wrong | Deploy-vs-canonical parity |

### What would change these verdicts
A model earns GO consideration when ALL of: (a) ≥2 additional paper quarters with per-trade max-loss ≤10 % NAV and book max-loss ≤30 % NAV; (b) a drawdown breaker observed firing correctly on the broker record; (c) a backtest twin that reproduces the live trades within tolerance over the same window; (d) no unexplained broker-record anomalies (dups, orphans, phantom fills); (e) enough independent bets (≥30 non-overlapping, or demonstrated performance across ≥2 distinct regimes) that the track is statistically distinguishable from rally beta. None currently satisfies more than one of the five.

### Immediate housekeeping (independent of go-live)
1. **Freeze/limit exp800_tradier real-money sizing** (model ruled LUCK; 14-lot order pending today under a 30-lot cap).
2. Buy in EXP-503's −800 SPY orphan short and add an expiry-cleanup job.
3. Root-cause the EXP-800 Apr-02 duplicate-entry path (30-min scheduler re-entry) — it is a live-money risk if it recurs on Tradier.
4. Fix executor↔IBKR order-state reconciliation before running any more IBKR paper — patch ready on executor branch `fix/reconciliation-stale-sto-and-fill-backfill` (also auto-expires the 4 stale "pending" orders from Jun-01/Jun-30).
5. **Security: the public attix-dashboard is running the DEV default password and session secret** (`DASHBOARD_PASSWORD`/`SECRET_KEY` unset in prod) while exposing account numbers, positions, equity and admin push endpoints. Set both now.
6. Recalibrate EXP-V8A-IBKR sizing: the scanner sizes off the real $1.0M account instead of the $120k design baseline — the intended book hit 2.9× its own $360k max-loss target.

## Appendix — method
Per account: JNLC deposit = seed/inception; equity = broker account endpoint; curve = 1Y daily portfolio history (dates are Alpaca daily stamps; the ±1-day skew around late-session timestamps does not affect magnitudes); spreads reconstructed from mleg order legs; expired positions settled against real SPY closes (Alpaca IEX daily bars); assignment/exercise verified via OPASN/OPEXC/OPTRD activities; duplication = identical (date, type, expiry, strikes) opened >1× same day; peak book max-loss = Σ open spreads (width·qty·100 − credit), held-to-expiry upper bound where closes couldn't be matched. Raw pulls in session scratchpad (not committed; reproducible from the APIs listed in the task file).
