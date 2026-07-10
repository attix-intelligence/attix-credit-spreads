# CC2 Independent Proposal — Path to a Profitable Real-Money Model on Tradier

**Author:** cc2 (independent; no coordination with other sessions — `cc1_tradier_proposal.md` deliberately not read)
**Date:** 2026-07-05
**Inputs:** `reports/attix_program_review_2026-07-05.html`, `reports/PAPER_REVIEW_GOLIVE_RANKING.md` (rev 2), `experiments/EXP-3570-live-months-replay/CC_EDGE_VS_LUCK_REVERIFY.md`, plus my own read-only inspection of `configs/live_exp800_tradier.yaml`, `configs/paper_exp1220.yaml`, `configs/paper_exp3311.yaml`, `configs/event_blacklist.json`, `sentinel_state.json`, and `execution/execution_engine.py`.

---

## 0 · Bottom line

Stop EXP-800 on Tradier now (fully — not "freeze at small size"). Promote **EXP-1220's exact broker-validated configuration, unchanged**, hardened with three strictly risk-reducing additions (event gate, broker-layer hard caps, a breaker that actually persists its high-water mark), validate it on a fresh paper account through the **Aug-7 and Sep-4 NFP prints** against **pre-registered acceptance criteria written down today**, run a 1-lot real-money execution probe from early August, and go live on Tradier at a **$50k allocation in mid-September**.

Expected honest economics: **~8–20%/yr net, worst-case drawdown bounded at −15% of allocation (−$7.5k, −5.6% of the account) by a flatten breaker.** Not 45%. Anyone promising more from this codebase today is reading the luck, not the edge.

One engineering finding of my own, which reframes part of the program's history: **the fleet-wide "no breaker ever fired" mystery has a probable root cause in code.** `ExecutionEngine`'s drawdown breaker tracks its high-water mark in an in-memory attribute (`_peak_equity`, `execution/execution_engine.py:962`) — it resets on every scheduler restart, silently re-anchoring the HWM at current (possibly drawn-down) equity — and the entire check **fails open** (`except Exception: return False`, line ~977). EXP-1220 had a 10% breaker configured all along (`drawdown_cb_pct: 10`); it took a −11.8% June drawdown and kept entering. The breakers weren't mis-tuned; they were structurally incapable of firing across restarts. This is fixable, testable, and central to my plan.

---

## 1 · Strategy choice: EXP-1220 verbatim + risk-only hardening ("EXP-1221")

### What launches

The exact `paper_exp1220.yaml` strategy that produced the broker-verified +6.2% / −11.8% MaxDD track (Apr-20 → Jul-3, 21 opens, 14W/7L, losers cut at −$40…−$260 vs credits +$550–900, flat book on Jul-3):

- SPY credit spreads, **$5 wide**, 21–45 DTE (target 30), 5% OTM, Monday-only entry cadence
- 9.35% max-loss per trade, max 5 concurrent positions, 31% portfolio max-loss cap
- Profit target 50% of credit, stop at 2× credit, close under 5 DTE
- VIX entry window 10–35, 20/50-MA trend filter, combo regime detector
- **1.0× leverage only.** The deploy specs' 1.5×–5× variants are out of scope (the Jul-5 leverage study shows vol drag caps useful leverage at ~2× — and that's *after* the edge is proven, not before).

Plus three additions, each of which can only **remove** trades or exposure, never add:

1. **Event gate** (EXP-3311's mechanism, live-proven n=1 on Jun-5): no new entry when the next trading day is an NFP print; extend `configs/event_blacklist.json` to include **FOMC decision days and CPI releases** (currently NFP-only — the blacklist already carries NFP dates through Dec-2026, verified against BLS).
2. **Broker-facing hard caps** (enforced at order submission, not inside strategy logic): ≤12 contracts/order; book aggregate max-loss (Σ width·qty·100 − credit over open **and pending**) ≤25% of allocation; and a **same-structure dedup preflight** — reject any order matching (underlying, strikes, expiry, side) of anything submitted in the prior 24h. This is the direct, mechanical answer to the Apr-2 12× duplication class of bug, and it works even if the scheduler misbehaves again.
3. **A breaker that can actually fire**: HWM persisted to the trade DB, drawdown computed from **broker-reported equity** (not scanner NAV), **fail-closed** (an errored check blocks entries rather than allowing them). Tiers: −6% from HWM → halve size; −10% → halt new entries; −15% → flatten everything + hard stop pending human review.

Call it EXP-1221 so the track is unambiguous.

### Why I expect it to be profitable — the honest version

I am **not** claiming direction-timing skill. The re-verification showed the fleet's regime calls are indistinguishable from a coin flip (6/8, p=0.145). The profit thesis is narrower and better supported:

1. **The premium is real independent of our backtests.** Short-dated, OTM index put-credit is a persistent, economically-grounded risk premium — compensation for writing crash insurance. It exists in decades of index put-write data and doesn't depend on any Attix engine being right. In-house, EXP-3300's finding that the SPY put-credit edge strengthened 2023→2025 is corroborating (not load-bearing).
2. **The fleet proved harvesting works when tails are controlled — and only then.** All ten accounts collected premium successfully for months; the entire dispersion in outcomes (+45% to −15%, −12% to −42% DD) was risk process, not signal. Same family: EXP-400 at ~100% NAV books → −41.6% DD; EXP-1220 at 4–9%/trade with working stops → −11.8% DD *through the same NFP crash* and positive on the quarter. Sizing was the whole difference. I'm proposing to fund the risk process, which is the only thing broker evidence supports.
3. **The one mechanism that dodged the killer trade is included.** EXP-3311's NFP gate skipped the Jun-5 entry that max-lossed 8 sibling accounts (n=1, but a mechanism, not a fit).
4. **Return math that doesn't require heroics.** 1220's quarter ran ≈+6% in 10.5 weeks including a fleet-killing event. I explicitly discount that to 8–20%/yr net: the observed quarter was rally-favorable, and my gates remove some winning entries too. At a −15% hard-flatten floor, the worst year is bounded and survivable; the strategy stays in the game long enough for the premium to pay. That asymmetry — bounded left tail, persistent positive drift — is the entire argument.

### Why verbatim-1220 instead of the review's composite

The program review recommends "champion signal + 1220 sizing + 3311 gate." I 80% agree, but with one material difference: **a composed hybrid is a brand-new strategy with a zero-length track**, and this program's core lesson is that recombinations behave unexpectedly (EXP-3303B's gate failed its only test; V8A's deployed incarnation diverged from its own canonical config). EXP-1220 *already is* champion-family signal + sane sizing, live-validated as a unit (corr 0.53–0.70 to siblings — the risk process genuinely changes the return stream). Keeping it byte-identical and adding only entry-blocking guards preserves the evidential value of its 10-week broker track: the gated strategy's trade stream is a strict subset of the validated one.

---

## 2 · Risk framework

**Capital structure (on the $133k Tradier account):**

| Layer | Value | Enforcement point |
|---|---|---|
| Strategy allocation | **$50,000** (fixed; `account_size` pinned; no compounding above allocation until first scale review) | config + preflight |
| Cash buffer | ~$83k untouched | account structure |
| Per-trade max loss | 9.35% of allocation ≈ $4,675 ≈ 10–11 lots of $5-wide | strategy + **order preflight recompute** |
| Per-order contract cap | **12** | executor/broker-facing layer |
| Book aggregate max-loss (open + pending) | **≤25% of allocation ($12.5k)** | pre-submit computation from broker positions, not scanner state |
| Max concurrent positions | 5 (config), book cap binds first (~3 at full size) | strategy |

**Breakers (from broker equity, HWM persisted in DB, fail-closed):**

| Trigger (DD from allocation HWM) | Action | Reset |
|---|---|---|
| −6% | Halve position size | recover above −4% |
| −10% | Halt new entries | recover above −5%, or 10 sessions + human review |
| −15% | **Flatten all positions, hard stop** | Carlos-level review only |

**Event gates:** no entry when next trading day ∈ {NFP, FOMC decision day, CPI}; blacklist file re-verified quarterly (existing job) and extended beyond its current NFP-only scope.

**Process kill-switches (any one → immediate halt + alert):** duplicate order detected post-hoc; orphaned single leg or stock position (the EXP-503 −800-share lesson); position reconciliation mismatch between DB and broker; two consecutive scans with stale market data.

**Execution safety specific to Tradier:** multileg orders only, never legged entry; a reconciliation job every 30 min comparing broker positions to the trade DB (paper never exercises partial-fill leg-out paths — real money will).

---

## 3 · Validation plan before real money

**Pre-registered acceptance criteria — written now, evaluated ~Sep-11, no goalpost moves.** GO requires ALL of:

1. **Zero broker-record anomalies** over the window (no dups, orphans, phantom fills, unexplained positions).
2. **Gates observed working on the record**: ≥2 scheduled entries visibly blocked by the event gate (Aug-7 and Sep-4 NFP windows guarantee the opportunities).
3. **Breaker live-fire drill passed** (see below) and weekly verification that breaker inputs match broker-reported equity.
4. **Every realized exposure within caps**, computed from broker records: no trade >9.35%, book never >25% of paper NAV.
5. **MaxDD ≤12%** over the window.
6. **P&L gate (deliberately weak):** final P&L > −5%. I will *not* require statistically significant positive returns from ~9 weeks — that bar is unreachable and pretending otherwise re-creates the 150-backtest problem. The GO decision is process-based plus the economic prior; P&L only vetoes.

**The drills (proving machinery, not waiting for disasters):**

- **Breaker fire drill (week 2):** temporarily tighten thresholds on the paper account (e.g. halt at −1.5%) so a normal small drawdown fires the full halt → alert → resume chain on the broker record. Restore real thresholds after. This converts "breakers never fired" from an open question into a tested path — something no account in the fleet has ever demonstrated.
- **Duplication drill (sandbox):** replay the Apr-2 30-minute scheduler cadence in a test harness against the dedup preflight; prove 11 of 12 identical orders are rejected.
- **Reconciliation drill:** inject a synthetic DB/broker mismatch in a test env; prove halt + alert.

**Decision-context logging (my replacement for historical twin parity):** every scan logs its full input snapshot (quotes, VIX, regime inputs, sizing math) so any live trade can be deterministically replayed and audited later. See §7 for why I demote the backtest twin relative to the review.

**Fresh paper account** (no inherited book, no inherited HWM), seeded $50k to match the live allocation exactly.

---

## 4 · Timeline

| Dates (2026) | Work |
|---|---|
| **Jul 6–10** | Stop EXP-800-TRADIER (§5). Engineering: gates on 1220 config, broker-layer caps + dedup preflight, HWM-persisted fail-closed breaker, decision logging. Root-cause the Apr-2 dup bug. Housekeeping from the ranking report: buy in EXP-503's −800 SPY orphan, set the dashboard `DASHBOARD_PASSWORD`/`SECRET_KEY` (real-money account data is currently behind a dev default — this is a today problem). |
| **Jul 13** | EXP-1221 paper starts, fresh Alpaca account, $50k. |
| **Jul 20–24** | Breaker + dup + reconciliation drills on the record. FOMC Jul 28–29 exercises the FOMC gate. |
| **~Aug 3** | If 3 clean weeks: **1-lot real-money execution probe on Tradier** — same config, same code path, max loss ≈ $470/trade. Purpose: measure real Tradier fills/slippage/multileg behavior vs Alpaca paper's optimistic fills, and exercise the executor sink with negligible capital. |
| **Aug 7, Sep 4** | The two NFP prints the validation window exists for. |
| **Sep 11** | Evaluate against §3 criteria, decision memo to Carlos. |
| **~Sep 14** | GO: $50k allocation on Tradier, full risk framework. |
| **~Nov (2 more NFP windows)** | First scale review: raise allocation and/or 1.5× only if the live record stays clean. 2× is the ceiling per the leverage study; 5× variants never. |

If any criterion fails: no launch, publish the failure analysis, iterate or kill. That is a real possible outcome and pricing it in now is the point of pre-registration.

---

## 5 · The current EXP-800 Tradier deployment: stop it, don't shrink it

The review recommends freezing size. **I recommend stopping it entirely, this week:** flip `live_submit: false` (the mechanism built for exactly this), cancel the two pending orders, close the open book in an orderly way, leave the account funded and the plumbing warm for EXP-1221.

Why full stop rather than 1-lot freeze:

1. **It's the LUCK model.** Direction hit-rate p=0.145; 50% of its paper P&L was one 12×-duplicated bug-trade; its twin is invalid. There is no experimental question that 1-lot live trading of this model answers. (The "does Tradier plumbing work" question is already answered — the Jun-29→Jul-2 IC round trip — and is better answered going forward by the §4 probe running the actual launch candidate.)
2. **The un-root-caused dup bug lives in this exact deployed path**, and the live config's static caps are weak against it: `max_contracts: 30` (per order), `max_portfolio_risk_pct: 60`, `max_risk_per_trade: 17%`. A repeat of the Apr-2 pattern at the Jul-3 order size (14 lots × 12 slots) is nominally a >$100k max-loss book on a $133k real account; where enforcement is per-order, cap arithmetic doesn't obviously stop cadence-stacking. Nobody should have to find out live.
3. **It has no event gate.** The live config lacks `entry_gate` entirely — deployed EXP-800-TRADIER would have entered the Jun-5 killer trade. Aug-7 NFP is five weeks away.
4. **Institutional momentum.** A live real-money deployment with a Carlos-approved 30-lot cap and +45% paper headline *wants* to be scaled. The evidence says the +45% was luck. Removing the deployment removes the temptation during the exact window when patience is the strategy.

What's preserved: the account, the executor wiring, the tier-3 halt fix (good work — it just belongs under a validated strategy), and all learnings from the round trip.

---

## 6 · Top 3 risks of my own proposal

1. **Winner's curse on EXP-1220.** I picked the best risk-adjusted account out of ten, post hoc — the same selection error the program made with EXP-800's +45%, just on a different metric. Its virtue rests on 21 trades in one regime; its Sharpe is 0.81; its stops have never faced an overnight gap through the strikes (stops don't bound gap losses — the −11.8% June DD happened *with* stops working); and its configured 10% breaker silently failed in June, so part of its "discipline" story is actually luck-of-restarts. **Mitigations:** all caps sized to full-width loss (assume stops fail); the flatten breaker at −15% is the true floor; allocation is 37% of the account; pre-registered criteria can still kill it.
2. **The validation window can't produce statistical proof — and someone may treat it as if it did.** ~9 weeks ≈ 8–10 Monday entries and n=2 NFP events. Passing §3 means "process verified, tails bounded, premium thesis intact," not "edge proven at 95% confidence." The dangerous failure mode is a good-looking September window triggering a fast scale-up — repeating the EXP-800 story one level up. **Mitigations:** scale review gated on *two more* NFP windows (Nov), leverage ceiling pre-committed at 2×, and this document on the record.
3. **Same-codebase operational risk.** EXP-1221 runs through the scanner/executor stack that produced a 12× duplicate entry, an orphaned −800-share naked short, weeks-stuck IBKR orders, and a fails-open breaker. My guards are new code with their own bug surface, and drills only cover anticipated failure modes; real-money Tradier multileg fills exercise paths paper never touched (partial fills, leg-outs, assignment timing). **Mitigations:** broker-layer enforcement independent of strategy code, 30-min reconciliation with fail-closed halt, the August 1-lot probe specifically to surface execution surprises at $470 stakes instead of $12.5k — but residual risk is genuinely nonzero and I won't pretend otherwise.

---

## 7 · Where I agree and disagree with the program review

**Agree:** no shortcut exists; nothing qualifies for GO today; the fundable ingredients are 1220's risk process and 3311's gate; EXP-800 must not scale; ~September is the earliest honest launch; leverage is capped ~2× by vol drag.

**Disagree, with reasons:**

1. **EXP-800 Tradier: stop vs freeze** (§5). One lot of a coin-flip model with a live un-fixed dup bug and no event gate buys zero information for nonzero tail risk.
2. **Historical twin parity should gate *scaling*, not *launch*.** The review makes "build the twin, verify trade-by-trade" a ~week-1 prerequisite for sizing real money. EXP-3570 showed the twin diverges for structural reasons (live VIX-percentile proxy vs real VIX/VIX3M in the engine, different entry cadence, breaker state paths). Retrofitting the backtester to bit-match the live scanner is a long tail of exactly the work this program has repeatedly gotten wrong, and a passing twin still wouldn't prove edge — it would prove self-consistency. Bounded loss must come from *engineering* (caps, breakers, flatten floor), not from backtest confidence; forward decision-logging + pre-registered live criteria deliver auditability sooner and more honestly. Twin parity remains the right bar for scaling past $50k/1×, where you need distributional claims.
3. **Launch the validated unit, not a new composite** (§1): "champion signal + 1220 sizing + 3311 gate" as a fresh assembly discards 1220's 10-week live track and re-introduces integration risk; adding only entry-blocking guards to verbatim 1220 keeps the track's evidential value.
4. **Add a real-money micro-probe in August.** The review sequences paper fully before any real order. A 1-lot probe (~$470 max loss) running the launch candidate converts "Tradier execution quality" from assumption to measurement six weeks earlier, at lottery-ticket cost.
5. **New this proposal:** the breaker no-fire has a probable *code* root cause (in-memory `_peak_equity`, fail-open exception path). This upgrades "add a real DD breaker" from a config line to a specific engineering fix with a drill that proves it on the broker record.

---

*Written independently per Carlos's instruction. No code, configs, or orders were modified; nothing committed. All numbers are from the three cited reports or direct read-only inspection of the repo noted in the header.*
