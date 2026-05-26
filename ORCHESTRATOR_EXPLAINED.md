# ORCHESTRATOR_EXPLAINED.md

**Companion to:** `ORCHESTRATOR_PROPOSAL.md`
**Audience:** Carlos and anyone who wants the *why* and *what*, not the *how*.
**Style:** Conceptual. No code. Plain English.

---

## 1. What the Orchestrator Is

The orchestrator is the **mission-control layer** that sits between our strategy research and the live broker.

Right now, our system has three pieces that work in isolation:

1. **Strategies** (`exp1220`, `exp2160`, `exp2240`, `exp1770`, `exp2020`, `crisis_alpha_v5`) — they research the edge and tell us *what* to trade.
2. **Signal registry** (`exp2690`) — collects all strategies into one place and produces a daily list of intended trades.
3. **Broker connector** (`alpaca_connector`) — knows how to talk to Alpaca and submit orders.

What's missing is the piece in the middle that asks the hard questions every professional trading desk asks before money leaves the building:

- Should we trade *today*, given what's happening in the market?
- How large should each position actually be, given the rest of the book?
- In what order, at what time of day, and through which order type should these go to the broker?
- If something fails mid-execution, what do we do?

That's the orchestrator. It is the **single decision-maker that turns research signals into real, sized, risk-checked orders** — and the single source of truth for what the live book is supposed to look like at any moment.

> Analogy: the strategies are the analysts pitching ideas. The signal registry is the morning meeting where ideas get collected. The orchestrator is the **head trader** who decides which ideas actually get traded today, in what size, and at what time. The broker connector is the **execution trader** at the desk.

---

## 2. Why We Need It (The Backtest → Live Gap)

Every algorithmic trading shop discovers the same uncomfortable truth: **backtested edge is not the same as live edge**, and most of the gap lives in operational decisions that the backtest silently assumed away.

Here is the gap, concretely, for our system:

### 2.1 The backtest assumes we always trade

When EXP-1220 backtests SPY put credit spreads, it opens a new spread on the same day every month and never asks "is this a bad day to be opening short premium?" Live, we know the answer is sometimes *yes* — FOMC press conferences, NFP mornings, CPI surprises, government shutdowns. The backtest had no opinion. Live, we need one.

### 2.2 The backtest assumes parameters don't drift

EXP-1220 was backtested at a **5%-OTM strike**, but the live signal generator in EXP-2690 picks strikes by **0.30 delta**. Those are not the same trade. On a calm day they're close. On a high-vol day, a 0.30-delta strike can be 8% OTM and a different position entirely. The orchestrator is the place where we *freeze* the canonical parameter for each sleeve and refuse to send anything that drifted.

### 2.3 The backtest sizes positions independently

Each strategy backtest computes its own position size against its own capital allocation. But in the live book, EXP-1220, EXP-2160, EXP-2240, and EXP-2020 *all* have short-vega exposure to the broad market. If they all fire on the same day, our actual short-vega is roughly four times what any one backtest thinks. The orchestrator is the place where correlated risk gets netted and a single portfolio-level sizing decision happens.

### 2.4 The backtest doesn't have partial fills

Backtests assume both legs of a credit spread fill at the mid. Live, one leg fills and the other doesn't, and suddenly we are short a naked put. The current alpaca connector has a fallback path that submits the two legs as independent market orders if the multi-leg request fails — that's a critical risk we can never accept in production. The orchestrator is the place where the rule is enforced: **a spread fills as a spread, or it does not fill at all.**

### 2.5 The backtest has perfect data

The backtest reads option prices from IronVault's curated cache. Live, IronVault might be stale, the upstream feed might be late, or yfinance might return a NaN for SPY's spot. The orchestrator is the place where stale data blocks an order rather than allowing a bad fill.

### 2.6 Nobody owns the book

Today, if we ask "what positions does the system intend to be holding right now, and why?" we have to reconstruct the answer from JSON files, JSONL audit logs, and the broker's open positions. There is no canonical answer. The orchestrator is the place where the book has one owner and one ledger.

**Summary:** without an orchestrator, every strategy is implicitly assuming a competent human trader sits behind it making all the operational calls. We do not have that human at 09:25 ET five days a week. We need the orchestrator to *be* that human.

---

## 3. How It Works (Conceptual Flow)

The orchestrator runs as a pipeline with four stages. Each stage takes the output of the previous one and adds information or filters things out.

### Stage 1 — Intent

The signal registry (EXP-2690) hands the orchestrator a list of **intents**: "I, EXP-1220, want to open a SPY put credit spread expiring 2026-06-19, short the 540 strike, long the 535 strike, 1 contract." Each intent is tagged with its sleeve name and its canonical parameters.

The orchestrator does not yet care whether the trade is a good idea today. It just collects the wish list.

### Stage 2 — Entry Gate (Filtering)

The entry gate runs each intent through a series of **filters**. Each filter has the power to **block** an intent, with a reason. Blocked intents are logged but not sent forward.

The filters answer the operational questions a human trader would ask:

- **Market open?** Don't trade if it's a holiday, an early close that we've already passed, or outside RTH.
- **Sleeve already on?** If EXP-1220 already has its SPY spread on for the month, don't open another.
- **Did the parameters drift?** If the intent says "0.30 delta" but the canonical parameter is "5% OTM," block it. We trade what we backtested.
- **Macro event today?** FOMC announcement at 14:00? Block short-premium openings the morning of. CPI release at 08:30? Don't open at 09:25.
- **Earnings event?** For single-name strategies, block if the underlying reports today.
- **Vol regime?** VIX > 40, or the VIX term structure inverted? Most of our short-premium sleeves stand down.
- **Correlation?** If the proposed trade would push our portfolio short-vega beyond a budget, block the lowest-priority intent.
- **Data fresh?** If the option chain we'd price against is more than N minutes stale, block.
- **Underlying tradeable?** If IronVault has zero contracts for the underlying (the historical issue with IWM and IBIT), block early with a clear reason rather than failing at the broker.

What survives the gate is a **gated signal**: an intent the orchestrator has affirmatively said "yes, today, for this sleeve" to.

### Stage 3 — Position Sizing

The sizer takes each gated signal and answers: **how many contracts?**

It does this in three steps:

1. **Per-trade risk** — what dollar loss are we willing to take on this single spread if it goes to max loss? That's a fraction of equity, sized by the sleeve's allocation.
2. **Portfolio overlay** — given everything else already in the book (and everything else *about* to enter the book today), do we need to scale down? Two sleeves both want short-vega; the second gets a smaller fill.
3. **Correlation cap** — if adding this position would push a correlated exposure over its budget (e.g. total short-vega notional, total notional in financials, total margin used), the size shrinks until it fits.

The output is a **sized order**: same trade idea, but with a final contract count that respects portfolio-level reality.

### Stage 4 — Order Routing

The router takes the sized orders and decides **when** and **how** to send them.

- **When:** spread openings go in shortly after the open once liquidity has settled (typically a configurable delay past 09:30 ET, default 09:35–09:45). Closings and rolls go in a pre-close window (default 15:30–15:45 ET) to avoid the last-minute liquidity cliff.
- **How:** every multi-leg trade goes as a **single atomic multi-leg order**. If Alpaca rejects it, the router does **not** fall back to legging in. It logs the rejection, marks the order failed, and moves on. We accept missing a trade; we do not accept being naked on a leg.
- **Reconciliation:** after every send, the router waits for fill confirmation and updates the portfolio ledger. If fills don't reconcile against intent, the system halts new sends and flags for review.

### Stage 5 — Audit

Every stage writes a JSONL line: the intent received, the filters passed/blocked, the size decided, the order submitted, the fill received. The audit log is the **single replayable record** of what happened and why. If a trade looks wrong tomorrow, we can reconstruct exactly which gate let it through and which sizer decision produced the contract count.

---

## 4. Examples — How This Looks in Practice

Below are three concrete scenarios using strategies that already exist in our system.

### Example 1 — NFP Morning Blackout (EXP-1220)

It's the first Friday of the month. NFP prints at 08:30 ET. The actual print is +60K vs. consensus +180K — a big miss. SPY gaps down 1.2% pre-market. VIX jumps from 15 to 22.

At 09:25 ET, EXP-1220 generates its intent: "open SPY put credit spread, expiry 30 DTE, short 5%-OTM." On a normal day this is exactly what we'd run with.

The entry gate fires:

- **NFP filter:** today is an NFP Friday. Short-premium openings are blocked in the 09:25–10:30 ET window. The gate writes a `blocked: nfp_morning_blackout` line to the audit log.
- The intent never reaches the sizer or router.

At 10:30 ET (or whenever the post-NFP cooling window expires, depending on configuration), the orchestrator can re-evaluate. If the desk's rule says "NFP days are skipped entirely for EXP-1220," the intent stays blocked for the day and we wait for next month.

**Why this matters:** the backtest opens this trade on NFP day and pretends it's fine. Live, that's a coin flip on a gap. The orchestrator enforces what the backtest didn't model.

### Example 2 — VIX Regime Gate (EXP-2160 + EXP-2020)

It's a Tuesday in late October. The market has been selling off for two weeks. VIX closes at 38 and opens at 41. The VIX term structure is inverted (front month above back month).

EXP-2160 wants to open XLF and XLI put credit spreads. EXP-2020 wants to open a cross-vol arb pair (long SPY vol vs. short XLF vol).

The entry gate fires:

- **VIX > 40 filter:** all short-premium openings blocked. EXP-2160's two intents drop out.
- **Term-structure filter:** with the curve inverted, EXP-2020's "long-vol" leg is now structurally cheap and the "short-vol" leg is structurally expensive — the arb's edge inverts. The gate has a sleeve-specific rule: EXP-2020 stands down when the term structure inverts. Both legs drop.
- **Existing positions:** the orchestrator does **not** automatically close existing positions just because the regime changed. That's a different decision (managed by stop rules at the strategy level). The gate only governs *new openings*.

**Why this matters:** the orchestrator is the single place where regime is consulted. Without it, three different strategies would each separately decide (or fail to decide) whether to trade. With it, the regime rule is uniform, auditable, and lives in one place.

### Example 3 — Pre-Close Cleanup (EXP-2240)

It's a Thursday. EXP-2240's QQQ put credit spread, opened 28 days ago at 28 DTE, expires tomorrow. It has decayed to near-zero. Strategy rules say: close on T-1.

The signal registry generates a **closing intent** at 09:25 ET: "close QQQ put credit spread, expiry tomorrow, 1 contract, buy-to-close."

The entry gate processes this differently than an opening:

- **Macro/event filters:** mostly skipped — closing a near-worthless spread is operationally cheaper than carrying it through expiry, regardless of macro.
- **Stale data filter:** still applies. We won't close into a frozen book.

The order router now decides timing:

- **Closings go in the pre-close window**, not at open. Default routing: hold the closing intent, fire it at 15:30 ET when liquidity has returned. (Configurable per-sleeve.)
- The order goes as a single multi-leg buy-to-close. If it doesn't fill by 15:55 ET, the router escalates: log the failure, flag for review, do **not** leave one leg open and one closed.

**Why this matters:** closing at 09:30 ET when the book is thin and the spread is worth $0.05 mid is a great way to pay $0.15 in slippage. Closing at 15:30 ET costs less. The orchestrator owns this timing decision so each strategy doesn't have to.

---

## 5. General Technical Picture (No Code)

### 5.1 Where it lives

The orchestrator is a new Python package alongside the existing strategy code. It does not modify the strategies. It does not modify the alpaca connector. It sits *between* them and replaces the thin glue (`exp2830_paper_signal_generator.py`) that currently does almost none of this work.

### 5.2 How it runs

Two modes:

- **Cron mode** — runs once per trading day at 09:25 ET (pre-market). Generates the day's plan, gates it, sizes it, and queues the orders.
- **Live mode** — a long-running process during market hours that submits the queued orders at their scheduled times, listens for fills, and updates the portfolio ledger.

Both modes share the same code and the same audit log.

### 5.3 What it depends on

- **IronVault** for option pricing (Rule Zero — no synthetic data, ever).
- **yfinance** for spot prices (already used).
- **A calendar service** for macro events (FOMC, NFP, CPI, OPEX, holidays). This is new — currently a CSV maintained by us, with the option to swap in an automated feed later.
- **The Alpaca paper API** for order submission and fills (already used).

No new external services. No new vendors. The orchestrator is mostly a careful re-organization of decision logic that already lives ad-hoc across the codebase, plus a small set of new filters.

### 5.4 What it produces

- **Order submissions** to Alpaca paper (later: live).
- **A daily plan file** showing every intent received, every block, every sizing decision, every order submitted, every fill — in one place, one timestamp-sorted log.
- **A portfolio state file** showing what the system thinks the book looks like, refreshed after every fill, reconciled against the broker on a schedule.

### 5.5 How it gets safer over time

The orchestrator's gates are **conservative by default**. The first version will block more than necessary — that's intentional. As we accumulate live experience and audit data, we tune the gates downward. The audit log is what makes that tuning possible: every block is logged with its reason, so we can ask "of all the trades the FOMC filter blocked in 2026, how many would have been profitable?" and decide whether the filter is too tight.

### 5.6 What it explicitly does *not* do

- It does not generate signals. Strategies do that.
- It does not invent prices. IronVault does that.
- It does not make discretionary calls. Every decision is rule-based and parametrized.
- It does not bypass the broker's risk checks. It adds checks; it never removes them.
- It does not silently leg into multi-leg orders. If atomic submission fails, the trade fails. Period.

---

## 6. Rollout in Plain English

We will not flip a switch and route real signals through this on day one. The rollout has five phases:

1. **Skeleton + tests.** Build the package, write the filters, sizer, router, calendars. Test against synthetic and historical scenarios. No paper trades flow through it yet.

2. **Parallel paper run.** Run the orchestrator alongside the existing paper signal generator for a full month. Both produce daily plans. We compare them line by line. Where they disagree, we ask whether the orchestrator's block was correct.

3. **Cutover.** The orchestrator becomes the source of truth for paper. The old `exp2830_paper_signal_generator.py` is deprecated and removed.

4. **Live with ramp.** Switch from paper to live with a small fraction of intended size (e.g. 25%). Watch for two to four weeks. Ramp up if everything looks clean.

5. **Steady state.** Full size. Gates tuned based on accumulated data. New strategies (and new gates) are added through the same framework.

At every phase, the audit log is the receipt. If a regulator, an auditor, or Carlos asks "why did we make trade X on day Y?", the JSONL audit answers it deterministically.

---

## 7. The One-Sentence Version

> The orchestrator is the head trader the system doesn't have yet: it takes the strategies' wish list, asks "is today a good day, in the right size, with the right execution?", and refuses to leave a leg naked.

---

## 8. What We Need From Carlos to Start Building

Five decisions, no more:

1. **Macro blackout policy** — which events (FOMC / NFP / CPI / OPEX) block which sleeves, and for what window? Default proposal in `ORCHESTRATOR_PROPOSAL.md` §6.
2. **VIX regime thresholds** — what VIX level fully blocks short-premium openings? Default proposal: 40.
3. **Correlation budgets** — what total short-vega notional are we willing to carry? Default proposal: scaled to current EXP-2600 v8a allocation.
4. **Closing window** — pre-close cutoff for rolls and closes? Default proposal: 15:30 ET.
5. **Live ramp size** — fraction of intended size at first live trade? Default proposal: 25%.

Approve those (or amend them) and the build can start.

---

**End of explanation. Technical spec lives in `ORCHESTRATOR_PROPOSAL.md`.**
