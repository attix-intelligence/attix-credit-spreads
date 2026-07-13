# PATH TO 20%+ — the honest map

**Date:** 2026-07-12 · **Author:** cc5 · **Requested by:** Carlos (via Kayley) · **Type:** research only — no backtests run, no live changes, holdout untouched
**Question:** per-stream honest CAGR is 4–6% (EXP-P1A-CAPACITY). What can credibly clear **20%+ portfolio CAGR**, and what does it cost?
**Ground rules inherited from the program:** honest fills only (`reports/honest_fills_fleet/FLEET_ROLLUP.md`), friction-first (`research/FRICTION_LEDGER.md`), prereg-or-it-didn't-happen, survivable tails.

---

## 0. The answer in five lines

1. **Free money first:** compounding + T-bill yield on idle collateral adds **+3 to +4 pp** to any stream we run, at zero new risk and zero cost. A4's 5.9% becomes ~9% before anything clever happens.
2. **Stacking works, but less than hoped:** 4–6 *genuinely* diverse defined-risk streams at realistic correlations (ρ 0.3–0.5) support **8–12% portfolio CAGR** — and the binding constraint is the aggregate max-loss cap, not volatility math.
3. **Capital efficiency (PM/SPAN) is nearly worthless for our current book:** for 5%-OTM defined-risk verticals, portfolio margin ≈ Reg-T. It becomes a real (2–6×) lever only for *undefined-risk* premium — a strategy-class decision wearing a margin costume.
4. **20%+ is reachable only by adding a higher-octane sleeve** (undefined-risk index premium under PM, commodity/crypto vol, or 0DTE) **and accepting portfolio MaxDD in the −20 to −30% range.** No defined-risk ETF-spread portfolio gets to 20% at −10% DD. Anyone who says otherwise is re-selling the old fleet (nine "streams," ρ = +0.73, one bet — FLEET_ROLLUP finding #2).
5. **Fastest credible route:** Phase 1 (compounding + cash yield + 4-stream defined-risk book) → 11–13% by ~Q4 2026 for $0 data cost; Phase 2 (commodity futures options sleeve) → 13–16% for ~$200/mo data; Phase 3 (one octane sleeve, evidence-gated) → 16–22%. Costs and timeline in §5.

---

## 1. STACKING — what 4–6 streams actually buy

### 1.1 The base stream, stated honestly

From `reports/profitability_program/EXP-P1A-CAPACITY.md` (prereg `b2b77df`, in-sample 2020–2024, holdout sealed):

| A4 cell (QQQ 12-wide 5%-OTM put verticals, weekly) | CAGR | MaxDD | Peak book max-loss |
|---|---|---|---|
| 15%/trade (prereg ceiling, flag-adjacent) | **+5.94%** | −8.6% | 29.3% of capital |
| 10%/trade (recommended with margin) | **+3.96%** | −6.2% | 19.8% |

Structural facts that carry over to any stacking plan: cadence is a pure risk-adder (2×/week doubled tail for zero CAGR); position caps don't bind; risk-% scales linearly with no convexity. Sizing is a risk-appetite dial, and the **30% book-max-loss line** is what caps it.

### 1.2 Compounding uplift (the capacity study was non-compounding)

The capacity grid used flat sizing off $100k (A4-as-passed convention). Flat sizing makes P&L arithmetic; equity-proportional sizing makes it geometric. The uplift from switching, over a 5-year horizon:

| Flat annual P&L (% of initial capital) | Flat-sizing CAGR | Compounding CAGR | Uplift |
|---|---|---|---|
| 4.0% | 3.7% | 4.0% | +0.3 pp |
| 5.9% (A4 ceiling) | 5.3% | 5.9% | +0.6 pp |
| 10% (portfolio-level) | 8.4% | 10.0% | +1.6 pp |
| 12% (portfolio-level) | 9.9% | 12.0% | +2.1 pp |

*(Math: flat total = 5×X → CAGR = (1+5X)^{1/5}−1; compounding CAGR = X.)* Two honest caveats: compounding also compounds drawdowns (sizing off equity shrinks size in DDs — mildly protective, the EXP-1220 evidence agrees), and it amplifies the size-blindness limitation — the fill model doesn't know a 26-lot order fills worse than a 13-lot (capacity study limitation #1). **Verdict: worth +0.3–0.6 pp per stream now, +1.5–2 pp at portfolio level later; requires P0B live fill probes before trusting at size.**

### 1.3 Cash yield on idle collateral — the cheapest uplift on the table

A book capped at ≤30% max-loss leaves **~70% of capital idle**. Every backtest in the program credits that cash **zero interest**. Parked in T-bills/SGOV at a ~4% short rate, the idle 70% adds **≈ +2.8 pp CAGR** at no strategy risk (rate-dependent: +2.1 pp at 3%, +3.5 pp at 5%). Defined-risk spreads on ETFs hold BPR = max loss, but nothing requires the collateral to sit in cash at 0%. This should be implemented regardless of every other decision in this document.

**Running subtotal: A4 ceiling 5.9% + 0.6 compounding + 2.8 cash yield ≈ 9.3% — a single honest stream, no new strategies.**

### 1.4 Correlation-honest stacking math

Assume 4–6 streams, each ≈ A4-quality (5.9% at 15%/trade before cash yield), capital split evenly. Per-dollar return is unchanged by splitting; diversification buys a **smoother path**, which can be converted into return only by re-levering back to the single-stream risk budget. Volatility scaling factor f = √(1/n + (1−1/n)ρ); re-lever multiplier m = 1/f; portfolio CAGR ≈ 5.94% × m:

| n streams \ pairwise ρ | 0.15 | 0.30 | 0.50 | **0.73 (the old fleet's actual)** |
|---|---|---|---|---|
| 4 | 9.9% | 8.6% | 7.5% | 6.7% |
| 5 | 10.5% | 9.0% | 7.7% | 6.8% |
| 6 | 11.0% | 9.2% | 7.8% | 6.9% |

Three honest readings:

1. **The ρ = 0.73 column is the fleet lesson quantified.** Nine same-class SPY-vertical "streams" bought ~1 pp. Same-underlier, same-class variants are not streams. Realistic ρ for what we can actually build from the friction-cleared surface (QQQ verticals + SPY/QQQ condors + SPY/QQQ calendars + GLD verticals/calendars — FRICTION_LEDGER finding #4) is **0.3–0.5**: all are index/metal premium, several share the equity-vol factor. ρ = 0.15 requires leaving the equity complex (commodities, rates, crypto) — see §3.
2. **The max-loss cap binds before the vol math finishes.** Re-levering m× multiplies book max-loss m×: A4's 29.3% at m = 1.5 → ~44% aggregate. Worst-case loss doesn't diversify the way vol does (2020-03 would have hit QQQ, SPY, and GLD books in the same week). So every cell right of ρ=0.5 at m>1 requires a **governance decision**: raise the aggregate max-loss budget to ~45–60% on the argument that simultaneous 100%-loss across risk-clusters is remote. That is a Carlos sign-off, not a math result.
3. **Add compounding (+1–1.5 pp at these levels) and cash yield on the still-idle fraction (+1.5–2 pp at a 45–60% deployed book):**

**Honest stacking ceiling: a 4–6 stream defined-risk book at ρ 0.3–0.5 supports ≈ 11–13% CAGR at MaxDD ≈ −10 to −15% and aggregate book max-loss ~45–60%. Not 20%.**

## 2. CAPITAL EFFICIENCY — portfolio margin vs Reg-T, honestly

**Broker facts (verified 2026-07-12):** [tastytrade PM](https://support.tastytrade.com/support/s/solutions/articles/43000435184): $125k to activate, $100k to maintain. [Schwab PM](https://www.schwab.com/margin/portfolio-margin): $100k regulatory minimum account value. [IBKR](https://www.interactivebrokers.com/en/trading/margin-requirements.php): risk-based (TIMS) portfolio margining, IBKR's stated initial threshold is $110k. PM replaces Reg-T's per-position rules with a stress-test (broad-based indexes roughly ±8–15% price shocks depending on class; ETFs typically stressed like equities at ±15%).

**The honest catch for our book:** Reg-T margin on a defined-risk vertical is already just max loss (width − credit). Under PM, the requirement is the portfolio's worst stress-scenario loss. A 5%-OTM QQQ put spread under a −15% stress is **fully in the money** — stress loss ≈ max loss. So for exactly the structures we trade:

- **PM buying-power multiplier for 5%-OTM defined-risk verticals: ≈ 1.0–1.3×.** (Small relief from cross-expiry offsets and the credit received; nothing more.)
- Marginal risks for that ~nothing: house-rule changes at the broker's discretion, concentration add-ons, and the psychological invitation to fill freed BP with more correlated shorts — the fleet disease with a margin subsidy.
- Where PM genuinely multiplies (2–6×): **undefined-risk premium** (index strangles/naked puts), where Reg-T charges ~20% of notional but a ±15% stress on a far-OTM short is small. That is not a margin optimization; it is switching strategy class to unlimited-loss instruments. Treated as such in §3.0.
- Side benefits worth taking if we open an index-options account anyway: SPX/XSP are cash-settled (no assignment/orphan-leg class of ops bugs — see EXP-503's −800-share orphan) and §1256 60/40 tax treatment. Real, but tax is outside CAGR-as-measured.

**Verdict: capital efficiency is not a path to 20% for a defined-risk book. Effective multiplier ~1.0–1.3×, i.e., +0–2 pp. The 6.7:1 numbers in broker marketing apply to books we don't (yet) run.**

## 3. HIGHER-OCTANE CLASSES — honest assessments

### 3.0 Undefined-risk index premium under PM (the classic route, named honestly)

The only well-documented, decades-long benchmark in this space: Cboe's PUT index (systematic SPX cash-secured put writing) returns ≈ **9–10% annualized since 1986** with equity-like drawdowns (−32.7% in 2008) — i.e., full-notional premium harvesting earns index-like returns with a better Sharpe, not 20%. Getting 15–20% out of it requires ~1.5–2× notional leverage under PM, which drags the documented tail to **−35 to −50%**. With strict VIX/term-structure/event gates (which our own evidence supports — EXP-3311's NFP gate; the A4 VIX≤35 gate) a defensible estimate is **12–18% CAGR at −20 to −30% MaxDD** on the sleeve. Requirements: $110–125k PM account (IBKR/tastytrade), breaker governance far stronger than anything the fleet demonstrated (FLEET_ROLLUP: breakers never fired live), and Carlos explicitly signing the tail. Data cost: $0 (SPX/XSP daily data covered; our options_cache + CBOE indices). **Why past attempts failed here: they didn't — we never ran undefined risk; the adjacent failure was sizing, and undefined risk is unforgiving of exactly that.**

### 3.1 0DTE / weekly index premium (SPX/XSP)

- **Documented edge:** academic work confirms a same-day variance premium accrues to sellers: [Beckmeyer, Branger & Gayda (SSRN 4404704)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4404704) find retail 0DTE buyers lost >$70M over 2021–23 (~60% of losses = transaction costs; buyers pay the VRP), while **short positions were profitable even after fees**. Cboe's own research ([0DTEs Decoded](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact/)) documents balanced flow and ~50% of SPX volume in 0DTE. The premium is real; it is also the most crowded premium pool on earth, and the seller's P&L distribution is maximally gap-exposed (no overnight, but intraday −2% moves hit hard; think 2018-02-05 compressed into hours).
- **Why our past attempt failed:** EXP-3400…3505 was shelved because **hourly CBOE bars cannot honestly model 0DTE fills** (program review §1). That diagnosis stands — FIX #3 taught us the fill model *is* the result at short DTE.
- **Data cost to do it honestly:** intraday SPX options quotes. SPX is Cboe-proprietary (not OPRA): CBOE DataShop intraday quote datasets run **$1–5k+ per year-slice** (order-of-magnitude; must be quoted precisely before prereg). XSP (1/10th, same underlying premium pool) is the right sizing vehicle at our account scale.
- **Ops:** full-session automation, intraday breakers, cancel/replace latency — a materially heavier ops bar than anything we run; our live-ops record (dup entries, orphans, stuck orders) says we earn this last, not first.
- **Honest CAGR range at survivable sizing (defined-risk 0DTE structures — iron flies/condors with stops, per the friction ledger's P2B surface):** **8–15%** on the sleeve, wide CI, with tail events that will periodically eat quarters. Estimated 3–6 months to honest evidence.

### 3.2 Futures options premium (ES / CL / GC on SPAN)

- **Edge documentation:** variance risk premia are documented as significantly negative (seller-favorable) across commodity markets — Prokopczuk, Symeonidis & Wese Simen (2017, *J. Banking & Finance*) find robust VRP in crude and gold among others; CME's own margin efficiency (SPAN) is the standard institutional route. **The honest attraction is not ES** — ES premium ≈ SPY premium (ρ ≈ 0.9+ to our book; adds margin efficiency, zero diversification). It is **CL and GC: genuinely distinct premium pools** that fix the ρ problem in §1.4's table (equity↔oil↔gold vol correlations ≈ 0.2–0.4).
- **Capital efficiency:** SPAN on defined-risk futures-option spreads ≈ scenario loss (same honest catch as PM for far-OTM defined risk), but SPAN on *strangles* is dramatically lighter than Reg-T equivalents. Same class-decision as §3.0.
- **Data cost:** cheap and immediate — [Databento GLBX.MDP3](https://databento.com/datasets/GLBX.MDP3/options/ES) usage-based historical (options on ES/CL/GC; standard plan **$179/mo** + usage of order ~$100s one-time for 5 years of daily/minute data).
- **Broker/ops:** IBKR futures-options permissions on the existing relationship; no new account minimums for defined risk. §1256 treatment.
- **Why past attempts failed:** never attempted — the program has been equity-ETF-only. Nearest analogue (GLD verticals/calendars) *cleared* the friction ledger.
- **Honest CAGR:** a CL+GC defined-risk premium sleeve at A4-grade discipline: **4–8%** on the sleeve — but its portfolio value is the correlation, pulling the §1.4 table toward the ρ≈0.15–0.3 columns. Est. 8–12 weeks to prereg-grade evidence.

### 3.3 Crypto vol (Deribit / CME)

- **Edge documentation:** the BTC variance risk premium is the largest documented VRP in liquid markets — [Alexander & Imeraj (SSRN 3383734, *J. Alternative Investments*)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734) measure annualized risk-neutral vs realized variance of 0.72 vs 0.58, a **VRP ≈ 14 variance points vs ~2 for the S&P 500**. Later work (Almeida, Grith & Miftachov, arXiv 2410.15195) confirms rich, regime-dependent premia.
- **The blockers, honestly:** (a) **jurisdiction — Deribit does not onboard US persons**; whether the Coinbase acquisition changes that for us must be resolved by a human before any planning; (b) counterparty/custody risk on an offshore venue is a different risk class than SIPC brokerage; (c) BTC realized tails are −40–60% quarters — the premium is large because the insurance is real. The compliant route is **CME bitcoin options via IBKR** (SPAN, §1256, thinner liquidity, smaller premium than Deribit but the same pool directionally).
- **Data cost:** [Tardis.dev](https://tardis.dev/) for full Deribit history — minimum order **$300**, professional **$599/mo**; CME BTC options via the same Databento subscription as §3.2.
- **Honest CAGR:** on the sleeve, **10–25%** at survivable sizing — but the sleeve itself must be capped at **10–15% of portfolio** given tail magnitude, so its portfolio contribution is **+1.5–3 pp**. Est. 8–12 weeks (CME route) once data is in hand.
- **Why past attempts failed:** paper_crypto_ibit/etha configs exist but were never taken through the honest pipeline; no prereg, no friction ledger row — i.e., not failed, never honestly tried.

## 4. What we will NOT do

1. **Re-mine closed families.** XLF/XLI/TLT verticals are DOA at the friction line before any signal is considered (FRICTION_LEDGER #2). The champion 17%-flat family produced four account ruins under honest fills (FLEET_ROLLUP #2). EXP-800 is decommissioned with four strikes. Closed means closed.
2. **Leverage-as-edge.** The program review's own sweep showed vol drag caps useful leverage ≈2× on the current edge and 5× would have been ruin. Leverage multiplies an edge; it does not create one. Any proposal whose only mechanism is "same trades, bigger" is rejected on arrival.
3. **Anything that can't pass a prereg.** Signed prereg before any run, friction-ledger citation mandatory, holdout sealed until Carlos spends it, honest fills only. A strategy that only works under naive fills doesn't work (nine-for-nine evidence: FLEET_ROLLUP #1).
4. **Correlation cosplay.** No more than one stream per (underlier-class × structure-class) counted toward diversification. Nine SPY verticals = one stream. The ρ used in sizing must be measured on broker equity curves, not asserted.
5. **Undefined risk without pre-signed tail governance.** §3.0/§3.2 strangles enter only with Carlos's written acceptance of the modeled −25–35% sleeve DD and live-fire-tested breakers (the fleet's breakers never fired once in June — that bar is unmet today).

## 5. Ranked recommendation — fastest credible route to 20%+

| # | Move | Portfolio CAGR after (est.) | Cost ($ / time / accounts) | Risk added |
|---|---|---|---|---|
| 1 | **Cash yield on idle collateral + compounding sizing** (any stream we run) | ~9% (single stream) | $0 / days / none | none / size-blindness caveat |
| 2 | **4-stream defined-risk book** from the friction-cleared surface (A4-QQQ verticals, SPY/QQQ 30-DTE condors, SPY/QQQ calendars, GLD) — each through prereg + honest fills | **11–13%** | $0 data / 6–10 wks pipeline / none — needs Carlos sign-off on 45–60% aggregate max-loss budget | MaxDD −10 to −15% |
| 3 | **CL+GC futures-options sleeve** (defined risk, SPAN, IBKR) — the correlation fixer | **13–16%** | ~$179/mo + ~$300 one-time (Databento) / 8–12 wks / futures perms | commodity gaps; sleeve-capped |
| 4 | **One octane sleeve, evidence-gated — in order of preference:** (a) PM undefined-risk index premium (§3.0), (b) CME BTC vol (§3.3), (c) 0DTE (§3.1, last: heaviest ops+data) | **16–22%** | (a) $0 data, PM account $110–125k min; (b) Databento (have) or Tardis $300+; (c) CBOE DataShop $1–5k + 3–6 mo | **MaxDD −20 to −30% portfolio — this is the price of 20%; there is no version without it** |

**Recommendation:** execute 1–2 immediately (they are underwriting-free), start 3's data purchase now ($300 unblocks two sleeves), and put the octane decision (4a vs 4b) to Carlos as an explicit risk-acceptance question with the tail numbers above — because the honest summary is: **the gap between 13% and 20% is purchased entirely with drawdown, not with cleverness.** If Carlos's true constraint is "20%+ at fleet-crash-week survivability," the honest answer is that target pair doesn't exist in this asset class, and 12–16% at −15% is the frontier we can actually stand behind.

---

### Sources

**Internal:** `reports/profitability_program/EXP-P1A-CAPACITY.md` (+ prereg `b2b77df`); `reports/honest_fills_fleet/EXP-P1A_ADDENDUM_RESULTS.md` (A3/A4 passes); `research/FRICTION_LEDGER.md` (EXP-P0A); `reports/honest_fills_fleet/FLEET_ROLLUP.md`; `reports/attix_program_review_2026-07-05.html` (leverage sweep; EXP-3400 0DTE shelving); `reports/EXP-800-AUTHORITY-PULL.md`.
**External:** [Beckmeyer, Branger & Gayda — Retail Traders Love 0DTE Options… But Should They? (SSRN 4404704)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4404704) · [Cboe — 0DTEs Decoded](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact/) · [Alexander & Imeraj — The Bitcoin VIX and its Variance Risk Premium (SSRN 3383734)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734) · [Almeida, Grith & Miftachov — Risk Premia in the Bitcoin Market (arXiv 2410.15195)](https://arxiv.org/pdf/2410.15195) · Prokopczuk, Symeonidis & Wese Simen — Variance Risk Premia in Commodity Markets (J. Banking & Finance, 2017) · Cboe PUT Index long-run performance (Cboe benchmark studies) · [tastytrade PM minimums](https://support.tastytrade.com/support/s/solutions/articles/43000435184) · [Schwab Portfolio Margin](https://www.schwab.com/margin/portfolio-margin) · [IBKR margin requirements](https://www.interactivebrokers.com/en/trading/margin-requirements.php) · [Databento GLBX (CME) options](https://databento.com/datasets/GLBX.MDP3/options/ES), [CME plans](https://databento.com/blog/introducing-new-cme-pricing-plans) · [Tardis.dev (Deribit history)](https://tardis.dev/), [billing](https://docs.tardis.dev/faq/billing-and-subscriptions).
**Verify-before-relying flags:** IBKR's exact PM initial minimum ($110k figure is IBKR's stated threshold — confirm current); CBOE DataShop SPX intraday quote pricing (order-of-magnitude only); Deribit US-person policy post-Coinbase acquisition; current T-bill rate for §1.3 arithmetic.
