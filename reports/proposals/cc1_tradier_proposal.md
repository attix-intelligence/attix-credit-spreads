# cc1 Proposal — Path to a Profitable Tradier Launch

**Author:** cc1 (independent; no coordination with other sessions)
**Date:** 2026-07-05
**Basis:** my own broker-record forensics (EDGE-vs-LUCK reverification, 10-account fleet review, IBKR recovery), the Jul-5 program review, and read-only inspection of configs/code. I agree with much of the program review's direction but **disagree with it in three places**, argued below.

---

## Summary of my position

Launch **EXP-1220 as-is** — not a new composite — hardened with the two safety features the fleet proved matter (event gate, working drawdown breaker) and the ops fixes already identified. Validate **edge** on a 6-year honest backtest twin (which is buildable for 1220 precisely because it has no regime engine) and validate **implementation fidelity** on a fresh paper account across two NFP prints. Halt and drain the EXP-800 Tradier deployment now. First real dollar late September at $25k, scaling only on pre-registered criteria.

Where I differ from the program review:

1. **Don't compose a hybrid.** The review recommends "champion signal + 1220 sizing + 3311 gate." But EXP-1220's survival was not the champion signal with better sizing — it is a *structurally different trade* (30 DTE target vs 15, 5 % OTM vs 2 %, 5-wide vs 12-wide, 50 % profit-target, 2× credit stop). A composite of parts from three accounts is a **new, never-run strategy** that inherits nobody's live evidence. The launch candidate with the most live evidence is EXP-1220 itself, unchanged, plus only additive safety features. Every line of config you change discards live evidence; change as few as possible.
2. **Halt and drain EXP-800 on Tradier — don't "freeze at 1-lot."** (§5.)
3. **Reframe what paper trading validates.** Eight more weeks of paper is ~10–15 independent bets — it can never establish edge. Paper validates *fidelity* (does the deployed thing do what the spec says); **edge must be established by the honest twin over 2020–2026 real marks**, where hundreds of expiry cycles carry actual statistical weight. If the honest twin says the edge at launch sizing is ≤ 0 after costs, we do not launch — that is a pre-registered kill criterion, not a starting point for negotiation.

---

## 1. Strategy choice and why it can be profitable

**Candidate: EXP-1220 v1.1 — SPY bull put spreads, 21–45 DTE (target 30), ~5 % OTM, 5-wide, min credit $0.30 (6 % of width), profit-target 50 % of credit, stop at 2× credit / 90 % of width, ≤ ~9 % max-loss per trade, portfolio max-loss cap tightened from 31 % → 20 % of NAV, 1.0× leverage** (drop the 1.1×), **plus** an NFP/FOMC/CPI entry gate and a real drawdown breaker (§2). Bull-put only — no direction flipping, no compass/regime engine in the trade path.

**Why this one:**

- **It is the only account in the fleet whose *loss mechanism* worked live.** Broker record, Apr-20→Jul-2: 21 spreads, 14W/7L, every loser cut small by process (−$40…−$260 against $550–900 credits; worst settled loss −$260), MaxDD −11.8 % in the week that put siblings down −23 % to −42 %, flat book at quarter end. That is the entire game in short-vol: the wins are structural, survival is engineered. EXP-1220 is the only live proof we own that our engineering can do it.
- **Why profitable at all:** the underlying income source is the index variance risk premium — persistent, well documented (and independently supported by the program's own EXP-3300 GEX work), modest after costs. Nothing in our data suggests we have a *timing* edge (EXP-800's direction calls were p = 0.145 vs a coin flip); everything suggests the VRP harvest is real and that P&L outcomes were decided by sizing and tail handling. So the profitable configuration is: harvest the premium mechanically, at sizing where the inevitable tail hits are survivable, with event gates trimming the worst-scheduled tails. Expected economics are modest and should be stated honestly: **≈ +1–2 %/month in normal months, occasional −5–10 % months, engineered floor near −12 %**. On $25k that is ~$250–500/month at first — v1's purpose is to prove the machine, not to get rich. Scaling comes after proof.
- **Why not the alternatives:**
  - *Champion (15 DTE, 2 % OTM, 12-wide) at any sizing*: 2 % OTM is why one NFP move max-lossed 8 accounts at once. Closer strikes = bigger premium and bigger fragility; the fleet just ran that experiment for us and the answer was −16.2k on a single trade in six of nine accounts.
  - *Any regime/direction engine (EXP-800 style)*: unreplicated in backtest, coin-flip live, and the source of the wildest variance (±28 % days). Cut it from the trade path entirely.
  - *v8a multi-stream*: Sharpe-6.39 backtest, worst live performer (−14.9 %), and the IBKR 3× leg showed the sizing engine doesn't even honor its own design baseline. Adding QQQ/XLF streams is correlation theater (fleet pairwise corr +0.73–1.00) — revisit only after three profitable live months on SPY.
  - *Leverage*: this morning's simulation settles it — vol drag caps useful leverage near 2×, and 1× is the right launch setting.

## 2. Risk framework

All limits are config-enforced, not conventions, and each must be *observed working* before go-live (§3, gate G3).

**Sizing.**
- Per-trade max loss ≤ 9 % of NAV in paper, **≤ 5 % of NAV on real money** (on $25k: ~2–3 contracts of a 5-wide).
- Aggregate open-book max loss ≤ 20 % of NAV — hard reject on any order that would breach it (the fleet died at 70–130 %).
- Hard per-order contract cap (10) *and* a duplicate-entry guard: an idempotency key on (date, expiry, strikes) at the order sink, mirroring what the executor already does — the Alpaca scanner path has no such guard today, which is how Apr-2's 12× duplication happened.
- Leverage 1.0×. No sizing that scales with winning streaks (EXP-3311 crept 8→38 lots into its win streak; cap is a cap).

**Exits (unchanged from 1220 — they are the evidence).** 50 % profit target; stop at 2× credit or 90 % of width; close below 5 DTE. Plus one addition: an **expiry-hygiene job** that force-closes any leg the day before expiration if the short is within 1 % of spot (the fleet's assignment artifacts — EXP-503's −800-share orphan short — came from unmanaged expiries).

**Event gate.** No new entries from T-1 close through T0 close for **NFP, FOMC, CPI**. Live evidence: EXP-3311's NFP gate is the only mechanism in the fleet that demonstrably dodged the killer trade. FOMC/CPI are included by identical logic (scheduled variance events with gap risk that a 30-DTE entry gains nothing by straddling). Existing positions are *not* auto-flattened at events — that's untested; the gate only stops adding.

**Drawdown breaker (the fleet has never had a working one).**
- −5 % from month-start NAV → halve per-trade size.
- −10 % → halt new entries; existing positions run their normal exits.
- Resume next calendar month at half size; full size after the first positive month.
- **Breaker drill is a launch gate:** in paper, temporarily lower thresholds so the breaker actually fires, and verify state transitions + resumption on the broker record. No account in the program has ever shown a breaker firing; "configured" ≠ "works."

**Kill switch (real money).** −10 % from launch NAV → flatten everything, stop, post-mortem before any restart. Pre-registered, non-negotiable.

## 3. Validation before real money

The principle: **backtest proves edge, paper proves fidelity, micro-live proves the broker.** Each phase has pre-registered pass/fail written down *before* it runs.

- **G0 — Ops hardening (week 1).** Root-cause + fix the Apr-2 duplicate-entry path (add sink idempotency); deploy the executor reconciliation patch (branch exists); buy in EXP-503's orphan short; set the dashboard's `DASHBOARD_PASSWORD`/`SECRET_KEY` (it currently runs dev defaults, publicly). None of this is strategy work; all of it is "can this platform be trusted with money."
- **G1 — Honest twin + 6-year edge test (weeks 1–2).** Because v1 has **no regime engine**, the twin only needs to replicate a mechanical rule — this is why it's buildable in days where the EXP-800 twin failed. Two deliverables: (a) *fidelity check*: twin reproduces EXP-1220's actual Apr–Jul paper trades from broker records — ≥ 90 % trade-date/strike agreement, P&L within tolerance; (b) *edge check*: run 2020 → mid-2026 on IronVault real marks (Rule Zero), through the 2020 crash, 2022 bear, and 2024–26. **Pass:** positive expectancy net of costs, MaxDD consistent with the −12 % engineering target at launch sizing, no single year worse than −15 %. **Fail → do not launch; there is no step 2 for an edgeless strategy.**
- **G2 — Fresh paper account, exact launch config (≈ Jul 20 → Sep 18).** Covers NFP Aug + Sep, FOMC late-Jul + Sep, two CPIs. Pass criteria pre-registered: ≥ 15 closed spreads; twin-vs-paper trade match ≥ 95 %; zero duplicate entries; zero orphaned legs; event gate observed blocking on ≥ 2 real event days; MaxDD ≤ 12 %. Note what is *absent*: a return target. Eight weeks of returns is noise; demanding profit here just re-selects for luck.
- **G3 — Breaker drill (during G2).** As above; observed on the broker record or no launch.
- **G4 — Micro-live (2 weeks, ~Sep 21).** $25k allocation on Tradier, 1–2 contracts per spread, purpose: measure real fills/commissions/assignment behavior vs paper assumptions, and exercise daily automated twin-vs-live reconciliation. Pass: slippage within modeled bounds, reconciliation report green 10/10 days.

## 4. Timeline

| When | What |
|---|---|
| Jul 6–10 | G0 ops hardening; EXP-800 Tradier halt (§5); v1.1 config authored + reviewed |
| Jul 13–17 | G1 twin: fidelity vs 1220's live record, then 2020–2026 edge run → **go/no-go #1** |
| ~Jul 20 | G2 fresh paper account starts (exact launch config, frozen) |
| Aug 7 / Sep 4 | NFP #1, #2 through the gate; G3 breaker drill in between |
| Sep 18–20 | Score G2 against pre-registered criteria → **go/no-go #2** |
| ~Sep 21 – Oct 2 | G4 micro-live $25k, 1–2 lots |
| Oct | If green: full v1 sizing on $25k; +$25k after first clean month. Not above $50k or 5 %/trade in 2026 |

~11 weeks to first real dollar. This is the same order of magnitude as the review's timeline because the constraint is physical (two NFP prints), not effort. Anyone offering a shortcut is offering to skip the only two event windows that would have caught this fleet's failure mode.

## 5. The current EXP-800 Tradier deployment

**Halt new entries now and drain: let the open Jul-17 positions exit via their normal profit-target/stop/expiry, then sit in cash. Revoke the 30-contract Phase-3 authority.** ($133k account, essentially flat since Jun-23 inception — nothing material is being given up.)

This goes further than the review's "freeze at 1-lot," deliberately. The arguments for keeping a 1-lot trickle are (a) it keeps the execution plumbing warm and (b) it's cheap. But (a) is better served by G4's micro-live *of the model we actually intend to run*, and (b) is wrong on information value: every EXP-800 trade is a draw from a strategy whose direction engine is statistically a coin flip, whose paper P&L was half a bug, and whose duplicate-entry path is un-root-caused **on the same scheduler architecture now attached to real money**. A 14-contract order went out under the 30-lot cap on Jul-3; a 12× duplication event at that size would put ~$450k of max-loss exposure on a $133k account. The expected learning is ~zero and the tail is account-ending. Stop-and-drain costs nothing except the admission that it should not have been launched — which the evidence already forced.

## 6. Top 3 risks of my own proposal

1. **EXP-1220's survival may itself be one lucky quarter.** 21 spreads, one adverse event, one regime — its clean loss record could be small-sample fortune, and I'm proposing to anchor the launch on it. Mitigation: G1's 6-year twin is the real test of the mechanism (the 5 %-OTM/30-DTE structure must survive 2020 and 2022 on real marks); the paper phase adds two more event windows. Residual: a config that passes both can still disappoint live — which is what the $25k cap, kill switch, and slow ramp are for.
2. **Structural short-vol, long-beta with no bear-market mode.** Bull-put-only means a genuine downtrend produces a steady bleed that gates and breakers bound but don't prevent; and I've deliberately removed the direction engine that might (in principle) have adapted. I accept this trade-off because our only live direction engine was indistinguishable from chance — but the risk is real: v1 makes money in flat/up tapes and is designed merely to *lose acceptably* in down tapes. The breaker's monthly halt is the actual bear-market defense; if G1 shows 2022-style bleed beyond −15 %/year, that's a fail.
3. **Modest edge may not clear real-world frictions at launch size.** At $25k and ≤ 5 %/trade, we're netting ~$60–90 credit per contract on 2–3 contracts against commissions, slippage on 5-wide SPY spreads, and occasional stop-outs; the honest expectancy could be a few hundred dollars a month — and a couple of bad fills can erase it. If G4 measures slippage materially worse than paper assumed, the strategy might be profitable in theory and roughly break-even in practice at this size. Mitigation: G4 exists precisely to measure this before scaling; the response to thin-but-positive economics is patience and scale-on-proof, not wider strikes or leverage — the fleet already showed where those roads go.

---
*Written independently per Carlos's instruction. Not committed. No code, configs, or orders were touched.*
