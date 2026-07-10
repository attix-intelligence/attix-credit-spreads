# CC3 Independent Proposal — Path to a Profitable Tradier Launch

**Author:** cc3 (independent; no coordination with other sessions)
**Date:** 2026-07-05
**Inputs read:** `reports/attix_program_review_2026-07-05.html`, `reports/PAPER_REVIEW_GOLIVE_RANKING.md` (rev 2), `experiments/EXP-3570-live-months-replay/CC_EDGE_VS_LUCK_REVERIFY.md`, `reports/EXP800_breaker_honest_backtest.md`, `configs/live_exp800_tradier.yaml`, `configs/paper_exp1220.yaml`, `configs/paper_exp3311.yaml`, `docs/DATA_ARCHITECTURE.md`, `experiments/registry.json`. Read-only; nothing modified, no orders placed.

---

## 0. Bottom line

**Halt the EXP-800 Tradier deployment today — fully, not "freeze at 1-lot."** Then launch a deliberately boring strategy: a **mechanical, signal-free SPY bull-put-spread premium harvest** built from EXP-1220's live-proven risk parameters, an expanded EXP-3311-style event gate, and — the structural fix this program actually needs — **one shared decision kernel that both the backtester and the live scanner execute verbatim**, so the backtest/live divergence class of problem cannot recur. Validate by falsification (a pre-registered 6-year real-quote backtest that the strategy must *survive*, not be *selected by*), then one fresh paper account through two NFP prints with 1-lot Tradier execution probes running in parallel, then a $25k real-money pilot in early October.

The honest expectation at launch sizing is **~10–20%/yr with a ≤12% max drawdown target** — not the +45% headlines this program has been chasing. If that number is not acceptable, the right decision is to not launch, because no larger number is currently supported by evidence.

---

## 1. Strategy choice: ATTIX-CORE-1 — mechanical VRP harvest, no direction calls

### 1.1 What the evidence actually supports

Three months of broker-verified paper trading and the EDGE-vs-LUCK reverification support exactly three claims:

1. **The premium is real; the signal is not.** The variance risk premium in SPY OTM puts is a documented, persistent market premium (and EXP-3300 found the SPY put-credit edge *strengthening* 2023→2025). Meanwhile the fleet's directional regime-calling scored 6/8 with p = 0.145 vs a coin flip — no evidence of skill. Both of EXP-800's outright wrong-direction losses (Mar-31, Apr-01) were **bear calls**. Every dollar the fleet reliably made came from selling put spreads into equity drift and collecting theta; every catastrophe came from process failures around that harvest.
2. **Risk process was the entire difference between accounts.** Same signal family: EXP-1220 (4–9% max-loss/trade, active stops, exit at 5 DTE) took −11.8% MaxDD; EXP-400 (100% NAV, hold to expiry) took −41.6%. The Jun-05 killer trade (742/730, −$16.2k, assigned at max loss) was a *2% OTM, 15-DTE, 12-wide spread held into expiry week* — the exact structure my proposal excludes.
3. **The event gate works and is nearly free.** EXP-3311's NFP gate mechanically dodged the fleet-killer (n=1, but the mechanism is calendar arithmetic, not statistics). Its cost is a few skipped entry days per month.

So the strategy is: **harvest the premium, delete the signal, industrialize the process.**

### 1.2 The rules (complete, pre-registered)

Parameters are taken from **live evidence (EXP-1220's broker record), not from backtest search** — this matters, see §3.1.

| Component | Rule | Provenance |
|---|---|---|
| Underlying | SPY only | Only ticker with full IronVault coverage; deepest NBBO |
| Structure | Bull put vertical, $5 wide | EXP-1220 (5-wide kept losers at −$40…−$260 live) |
| Direction | **Long-flat only. Never bear calls, never iron condors.** When filters say "not bullish," skip — do not flip. | Direction-flipping is the p=0.145 coin flip; delete it |
| Cadence | Max 1 new entry per week (Monday scan), max 1 entry per day system-wide | EXP-1220 weekly cadence; kills stacking |
| DTE | Target 30 (window 21–45) | EXP-1220 |
| Short strike | 5% OTM **and** delta ≤ 0.15 (both must hold, from the real chain) | EXP-1220 + vol-regime normalization |
| Min credit | ≥ 6% of width ($0.30 on $5) | EXP-1220 |
| Trend filter | 20d MA > 50d MA, else skip | EXP-1220 |
| VIX band | Enter only 12 ≤ VIX ≤ 30 | Tightened from 1220's 10–35 |
| Event gate | No new entry within 2 trading days before **NFP, FOMC, or CPI** (BLS/Fed published dates, `configs/event_blacklist.json`, quarterly re-verified). No new position whose 21–45 DTE window can be avoided from expiring inside an event week. | EXP-3311, expanded beyond NFP |
| Profit exit | Close at 50% of credit | EXP-1220 |
| Stop | Close if loss ≥ 2× credit | EXP-1220 |
| Time exit | **Hard close at 5 DTE. Never hold expiry week. Never take assignment.** | EXP-1220's `manage_dte: 5`; the killer trades were all assignments |

### 1.3 Why this will be profitable (and how profitable, honestly)

- **The edge is the premium itself**, which does not require us to predict anything — only to collect it at acceptable cost and cut the left tail with defined-risk width, stops, time exits, and event gates. The fleet's own quarter — which *contained* the NFP crash — was net-positive for the one account that did this (+6.2% in ~10.5 weeks at up-to-9% risk/trade).
- **The losses the fleet took are all mechanically excluded here**: oversizing (hard caps, §2), event exposure (gate), assignment/gamma week (5-DTE exit), direction bets (deleted), ops bugs (idempotency + reconciliation, §2).
- **Honest magnitude:** at 5% max-loss per trade and ~4 entries/month, EXP-1220's live record is the best available estimator: roughly **10–20% annualized, MaxDD target ≤12%**, on the $133k account that is ~$13–27k/yr. The Phase-2 backtest replaces this guess with a real net-of-costs number before any money moves.
- **What would make it unprofitable:** the 0.10–0.15-delta premium net of spread-crossing and commissions is thin. That is precisely what the real-NBBO backtest (Phase 2) and the 1-lot Tradier probes (Phase 3) measure before the pilot. If net capture is negative, we stop — that is the honest outcome, and it is cheaper to learn it in Phase 2 than on Tradier.

### 1.4 The structural fix: one decision kernel

The program's single most damaging technical fact is EXP-3570's: the backtest twin and the live scanner are **different programs** (different regime signal, different structure choice, different sizing) — so 150 backtests validated software that was never deployed, and the deployed software was never validated. The review proposes making the backtester replicate the live compass/regime logic. **I disagree with the direction of that work**: it spends a week faithfully emulating a signal that was formally ruled indistinguishable from a coin flip.

Instead: extract one pure function — `decide(date, chain, underlying_state, account_state) → actions` — containing every rule in §1.2, and have **both** the backtester and the live scheduler call it. The backtest harness feeds it IronVault chains; the live harness feeds it Polygon/Tradier chains and broker state. Twin parity then holds **by construction**; the only remaining divergence surfaces are data and fills, which are exactly the things a pilot should measure. The rules above are simple enough that this kernel is ~300 lines. Simplify the strategy until the twin is trivial, rather than complicating the twin until it matches an unproven strategy.

---

## 2. Risk framework

Two layers, deliberately redundant: the **strategy** sizes positions; the **executor** enforces caps it cannot override. Everything below is checked against **broker-reported** state, not the internal DB — the fleet's worst incidents (12× dup, orphaned −800 SPY short) were internal-state/broker-state divergences.

### 2.1 Sizing (strategy layer)

- Per-trade max loss ≤ **5% of current NAV**: `contracts = floor(0.05 × NAV / (width×100 − credit))`.
- Book aggregate max loss ≤ **20% of NAV** (sum over open spreads of width×qty×100 − credit).
- Max **4 concurrent positions**, max 2 sharing an expiry.
- No leverage. No compounding of the risk fraction. The leverage study in the program review is conclusive: vol drag caps useful leverage at ~2× on the current edge, and the edge must grow before the multiplier does.

### 2.2 Hard caps (executor layer — cannot be raised by config drift)

The fleet's sizing failures were **config drift**, not code: `paper_exp3311.yaml` shipped with `max_risk_per_trade: 33.6` and `max_portfolio_risk_pct: 90`; EXP-800-Tradier's cap went 1→30 contracts in two phases. Executor-side invariants, independent of any strategy YAML:

| Invariant | Pilot value | Full value |
|---|---|---|
| Max contracts per order | 3 | 15 |
| Max new entry orders per day | 1 | 1 |
| Max book max-loss vs broker NAV | 10% | 20% |
| Order idempotency | Reject any order whose key `(experiment_id, entry_date, ticker, expiry, strikes, side)` already exists **broker-side** (order tag), not just DB-side | same |
| Reconciliation | Every scan begins by diffing broker positions vs internal book; **any mismatch → halt all entries + page** | same |
| Kill switch | Single env flag flattens and halts; tested in the drill (§3.3) | same |

Idempotency at the executor kills the entire Apr-02 12×-duplication class *structurally*, whatever the scheduler does. The dup bug still gets root-caused (it's in the plan), but safety must not depend on that hunt being complete.

### 2.3 Drawdown breaker — with the flatten this time

The honest-breaker backtest (`EXP800_breaker_honest_backtest.md`) established that the deployed halt-only tier-3 lets the open book bleed to −31% while "halted." My breaker:

- **−8% from HWM** → new-entry size × 0.5.
- **−12% from HWM** → halt new entries **and flatten all open positions** (defined, bounded cost; no MTM bleed ambiguity).
- Resume only when equity recovers above −6% from HWM **and** a human review has signed off.
- HWM never resets; evaluated daily against broker equity.
- **Live-fire requirement:** the breaker must be observed firing correctly on the broker record (forced-state drill in paper, §3.3) before any real money. No account in the fleet ever demonstrated a firing breaker — that is currently an untested airbag.

### 2.4 Event and regime gates

Calendar gates (NFP/FOMC/CPI) and the VIX band as in §1.2. One addition: **VIX > 35 at any time → close positions at next open** (don't just block entries while holding short vol through a spike).

---

## 3. Validation plan before real money

### 3.1 The multiplicity problem, addressed head-on

After ~150 backtests, *any* strategy chosen because its backtest looks good is suspect — the garden of forking paths guarantees some configuration looks elite by chance (v8a: backtest Sharpe 6.39, live −14.9%). My mitigations:

1. **Parameters are chosen from live broker evidence** (EXP-1220's record), not from backtest search.
2. **The backtest is used to falsify, not to select.** Acceptance thresholds are written down *before* the run (below). One shot. If it fails, the strategy is not tuned until it passes — we investigate, and any parameter change resets the paper clock and is disclosed as a new pre-registration.

### 3.2 Phase 2 — pre-registered falsification backtest (the kernel, 2020→2026)

- Data: IronVault real SPY option quotes, 2020-01 → 2026-06 (coverage verified: ~5.6M quotes + the EXP-3570 Apr–Jun 2026 backfill). Rule Zero throughout — no synthetic pricing anywhere.
- Fills: cross the real NBBO with a penalty (entry at mid − 40% of half-spread, exits at mid + 40%), $0.65/contract + fees. Pessimistic by design.
- Window includes COVID 2020, the 2022 bear, the Aug-2024 vol spike, and Apr–Jun 2026 — four distinct stress regimes the paper fleet never saw.
- **Pre-registered acceptance criteria (written now, before the run):**
  - Total net P&L positive over the full window;
  - No calendar year worse than **−10%**;
  - MaxDD ≤ **15%**;
  - 2022 (trend filter mostly out of market) loses no more than **−8%**;
  - ≥60% of profit from ≥3 different calendar years (no single lucky year carrying it).
- **If it fails, we do not launch this strategy** and we say so. That is a success of the process, not a failure of the program.

### 3.3 Phase 3 — one fresh paper account + Tradier execution probes

- **One** new Alpaca paper account (not ten) running the kernel, ~8 weeks, spanning **≥2 NFP prints (≈Aug-7, Sep-4), ≥1 FOMC (≈late Jul or mid-Sep), ≥2 CPI prints**.
- Pass criteria (all broker-record, all pre-registered):
  - **Twin parity:** the backtester, run over the same live window afterward, reproduces the paper trades (same entry dates, strikes within 1 step, exits within 1 day). This is the acceptance test of the shared kernel.
  - **Breaker drill:** force the HWM state to trigger tier-1 and tier-3 once each; verify size-halving and flatten on the broker record.
  - **Kill-switch drill** executed once.
  - Zero reconciliation anomalies, zero duplicate orders, zero orphaned legs.
  - P&L is *not* a pass criterion beyond "no rule violations" — 8 weeks of P&L is noise, and pretending otherwise is how EXP-800 got funded.
- **In parallel from week 1: 1-lot Tradier probes** of the *same kernel signals* on the real account (max loss ≈ $470/trade ≈ 0.35% of NAV). Purpose: measure real Tradier fill quality vs paper marks and vs the backtest fill model *before* the pilot. This replaces the review's "keep EXP-800 frozen at 1-lot" — probe the strategy we intend to run, not the one we've ruled luck.

### 3.4 Phase 4 — staged real-money pilot

- **Gate review with Carlos** (~Sep-28): Phases 2–3 results on the table; explicit GO/NO-GO.
- Pilot: **$25k allocation** of the Tradier account, executor caps at pilot values (3 contracts/order, 10% book), 4 weeks.
- Scale to full framework (5%/trade, 20% book, 15 contracts) only after 4 clean pilot weeks, slippage within the budget set in Phase 3, and a second sign-off. Any breaker fire or reconciliation halt during the pilot resets the 4-week clock.

---

## 4. Timeline

| Dates (2026) | Phase | Work |
|---|---|---|
| **Jul-6 (Mon)** | 0 — Disarm | Carlos: `live_submit: false`, cancel pending Tradier orders, registry → halted for EXP-800-TRADIER. Housekeeping: buy in EXP-503's −800 SPY orphan; set the dashboard password/secret (real security hole, flagged in the ranking report). |
| Jul-6 → Jul-17 | 1 — Build | Shared decision kernel; executor hard caps + broker-side idempotency + reconciliation halt; root-cause the Apr-02 dup path; retire the redundant paper clones (400/401/3303B/3309/503/V8A) — keep 1220 & 3311 running untouched as reference tracks. |
| Jul-13 → Jul-24 | 2 — Falsify | Pre-registered 2020→2026 IronVault backtest of the kernel. **NO-GO if acceptance criteria fail.** |
| Jul-27 → Sep-25 | 3 — Paper + probes | Fresh paper account through 2 NFPs / FOMC / CPIs; breaker + kill-switch drills; 1-lot Tradier probes; twin-parity check. |
| ~Sep-28 | Gate | GO/NO-GO review with Carlos. |
| Oct-5 → Oct-30 | 4 — Pilot | $25k, 3-contract cap, weekly review vs twin. |
| ~Nov-2 | Scale | Full framework sizing if pilot is clean. |

Total: **~13 weeks to full-size real money**, ~3 weeks slower than the review's path — the extra time is the falsification backtest and the drills, which are exactly the steps whose absence produced the current situation.

---

## 5. What to do with the current EXP-800 Tradier deployment

**Halt it entirely, today. Not "freeze at 1-lot" — halt.** This is my sharpest disagreement with the program review.

Current state (from `configs/live_exp800_tradier.yaml` and the reverification): `live_submit: true`, Phase-3 cap **30 contracts**, a 14-contract order submitted Jul-3, on a model whose paper P&L was 50% one un-root-caused 12×-duplication bug, whose direction calls are p=0.145 vs a coin flip, and whose breaker semantics were proven (honest-breaker backtest) to allow a −31% bleed while "halted." A 30-lot, 12-wide entry is ~$36k max loss ≈ **27% of NAV on a single trade** — authorized *right now* on real money.

- **Why not 1-lot freeze:** the marginal information from EXP-800 continuing at 1 lot is ~zero (we already have its fills since Jun-23; its signal is ruled luck), while the ops tail risk (the dup path is live and unexplained) is real money. Negative expected value, no learning. Close out whatever is open/pending.
- **Keep the account funded.** It becomes the venue for Phase-3's 1-lot kernel probes and the Phase-4 pilot — so the "real money presence" Carlos wants continues, but pointed at the strategy we intend to scale rather than the one we've formally disqualified.
- Concrete steps (all Carlos's to execute; I have touched nothing): cancel the 2 pending orders; flatten any open spread at market open Jul-6; set `live_submit: false`; registry `active → halted`; leave `TRADIER_PROD_TOKEN` wiring intact for the probes.

---

## 6. Top 3 risks of this proposal

1. **"Signal-free" may mean "SPY beta in a costume."** By deleting the direction-flip I also delete the June bear-call profits (+$16k Jun 8–12) that were real, and a long-flat put-seller's returns will correlate with the index. If the trend filter + event gate + stops aren't enough in a sustained bear market, Phase 2's 2022 segment will be ugly — and if it fails the pre-registered bar, this proposal terminates with *no launch* and the program has to confront the possibility that it has no deployable edge. I consider that outcome honest, but it is a real risk to the goal of "a profitable model on Tradier," and the temptation will be to weaken the criteria post-hoc. The mitigation is that the criteria are written down in §3.2 before the run.
2. **The kernel refactor is new code on the critical path.** Rebuilding the decision path (rather than reusing the battle-tested-ish scanner) can introduce fresh ops bugs of exactly the class that burned the fleet, and my 2-week estimate for kernel + executor caps + idempotency can slip, pushing the paper window past the Sep-4 NFP and the whole timeline toward November. Mitigations: the kernel is deliberately tiny (~300 lines of pure logic), the executor caps are defense-in-depth against kernel bugs, and the paper phase exists precisely to shake this out — but schedule risk is real.
3. **The validation is still thin where it matters most.** Even done perfectly: the event gate will have faced ~3 NFPs live (n=3); the 6-year backtest is dominated by one great short-vol regime (2023–2025); fill-quality is estimated from 1-lot probes that may not represent 13-lot fills; and a clean 4-week pilot can still be another lucky branch. The premium itself could be structurally thinner going forward (crowding into short-vol ETPs). Mitigations — small pilot, hard executor caps, flatten-at-tier-3, and refusing to treat pilot P&L as validation — bound the cost of being wrong at roughly the pilot's 10% book cap, but they do not eliminate the possibility that we launch a marginal strategy. The counterweight is the standing rule: **size only grows on evidence, never on returns.**

---

## 7. Where I agree and disagree with the program review (for the record)

**Agree:** fund nothing today; EXP-1220's risk process and EXP-3311's gate are the only live-proven components; the dup bug must be root-caused; 6–8 weeks paper spanning ≥2 NFPs is the minimum; go-live small and instrumented; all six housekeeping items (especially the dashboard password).

**Disagree:**
1. *EXP-800 Tradier:* review says freeze size; I say halt entirely and repurpose the account (§5).
2. *The twin:* review says make the backtester replicate the live compass/regime logic; I say delete the unproven logic and share one kernel between both harnesses (§1.4). Don't spend a week building a faithful emulator of a coin flip.
3. *The composite:* review's launch candidate keeps "the champion signal" (15 DTE, 2% OTM, 12-wide, regime direction-flipping) and adds 1220 sizing + 3311 gate. But the champion signal *is* the unproven part — its structure is the exact shape of the Jun-05 killer trade, and its direction calls are the p=0.145 coin flip. I keep 1220's structure (30 DTE, 5% OTM, 5-wide, 5-DTE exit) and drop direction-flipping entirely.
4. *Additions the review lacks:* pre-registered falsification backtest over 2020–2026 (anti-multiplicity), executor-level hard caps independent of config YAMLs (anti-config-drift), broker-side order idempotency (structural dup kill), breaker flatten + mandatory live-fire drill, 1-lot real-money probes during paper, and explicitly retiring the redundant paper clones.

---

*cc3 · 2026-07-05 · written independently; not committed per task instructions.*
