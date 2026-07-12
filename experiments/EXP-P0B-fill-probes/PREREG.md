# EXP-P0B · Tradier Fill-Quality Probes — PRE-REGISTRATION

**Date:** 2026-07-12 · **Author:** cc3 · **Status:** committed BEFORE any probe order is placed.
**Authority:** Carlos GO 2026-07-12 (profitability program approved, **including P0B probe commissions** — decision item 2 of `research/PROFITABILITY_PROGRAM.md` §4). Design per program doc §2 · EXP-P0B.
**Integrity rule:** this document is committed to git before the first live probe. Any change to the schedule, price-level definitions, metrics, or pass/kill criteria after the first probe voids the run (ops-parameter fixes — e.g., a timeout constant — are allowed only with a committed amendment note and never retroactively).
**Governance position:** mechanism = **forward live measurement** — always admissible under `reports/honest_fills_fleet/EXPECTANCY_SEARCH_GOVERNANCE_DECISION.md` (one-way door: measured execution facts). This experiment selects no strategy, touches no historical window, and its P&L is excluded from any expectancy claim. Friction ledger cited per program rule: `research/FRICTION_LEDGER.md` (P0A).
**Live-order gate:** the probe schedule ships **disabled** (`enabled: false`). The first live order requires Maximus's explicit go after reviewing the system + dry-run preview. This prereg does not itself authorize order flow.

---

## 1 · Hypothesis (measurement, not strategy)

Real Tradier fill rates, time-to-fill, and effective slippage for 1-lot option vertical spreads placed at **mid**, **mid−1¢**, and **marketable** limits differ measurably from the FIX #3 backtest fill model, and inside-NBBO posting captures part of the quoted spread (the P1D premise). P0A found the engine's friction model ~15–20% optimistic even on near-ATM SPY and could only bound non-SPY spreads from below (trade-based estimator); P0B replaces those bounds with live ground truth.

## 2 · Design

### 2.1 Underliers — SPY + XLI (and why XLI, not XLF)

- **SPY**: the program's primary underlier; calibrates the fill model where all Phase-1/2 backtests run.
- **XLI**: the program spec says "SPY + one sector ETF." P0A **killed every XLF vertical class outright** (median credit below friction) — probing a dead underlier informs no pending decision. XLI is the sector ETF with surviving-but-marginal classes (iron condors at 28% min-edge; calendars at 18%) whose remnant prereg decision *explicitly waits on P0B spread reality* (`FRICTION_LEDGER.md` §Program implications, P1A/P1F rows). XLI probes therefore carry direct decision value; XLF probes carry none.

### 2.2 Probe instrument

One probe = one **1-lot, 2-leg defined-risk put credit vertical**, opened and closed the same day:

- Expiry: nearest to 30 DTE within 21–45.
- Short strike: nearest listed strike to 2% OTM below spot (the ledger's reference class). Long strike: SPY = short − $5; XLI = short − $2 (nearest listed).
- Entry: **sell-to-open at a fixed limit** (level per §2.3). Never a market order; never modified/repriced (**no-chase rule** — an entry order is placed once and either fills or is canceled at the cutoff; any entry modification is a kill-criterion breach, per P1D's "probes chase price → halt").
- Exit: **buy-to-close** any filled probe starting 15:30 ET at the marketable limit; if unfilled after 5 minutes, reprice 1¢ through the NBBO every 2 minutes until filled (closing orders MAY chase — flatness is guaranteed, and close-side repricing is recorded as its own measurement). **All probes flat by 15:45 ET.**
- Unfilled entries are canceled at **15:15 ET** and recorded as unfilled observations (the rest window ≥ 90 minutes for the latest slot is part of the measured quantity: "fill probability within the trading day at this level").

A probe is execution measurement on the audited order path, not a strategy trade. The structure (SPY put vertical) belongs to the closed strategy family precisely so that no one can mistake probe P&L for strategy evidence; max risk per probe is capped by structure (≤ width × 100 ≈ $500 SPY / $200 XLI) and in practice by same-day flatness to a few dollars of spread cost plus intraday drift.

### 2.3 Price levels (the treatment variable)

Computed from per-leg NBBO snapshots taken at placement time (recorded raw in the state DB):

| Level | Limit credit for the vertical |
|---|---|
| **mid** | (short-leg mid − long-leg mid), rounded to the tick toward the natural |
| **mid−1¢** | mid − $0.01 (one cent more aggressive) |
| **marketable** | natural: (short-leg bid − long-leg ask) — crosses the book, still a limit |

### 2.4 Schedule and rotation — fixed, NOT strategy signals

- **2 probes per trading day**: Slot A at 10:15 ET, Slot B at 13:45 ET.
- Cell assignment (underlier × level, 6 cells) follows a **deterministic 3-day Latin rotation keyed to the trading-day index** — balanced cells, zero discretion, auditable in code (`scripts/p0b_probe_scheduler.py::rotation_cell`). No quote-conditional or signal-conditional entry: a slot fires unless a skip rule (§2.5) applies.
- Duration: ~4 weeks → **n ≥ 40** probes (≥ 6 per cell, ≥ 13 per level pooled). **Pre-authorized extension** (no re-registration): continue to a maximum of n = 60 (~6 weeks) if the §4 CI bar is unmet at n = 40. Beyond 60, stop regardless; report what was learned.

### 2.5 Skip rules (fixed in advance)

Skip a slot only when: market closed / scheduled half-day; the halt flag is set (§6); underlier NBBO unavailable or crossed at placement; or a same-tag order already exists (idempotency). Skips are logged with reason; they are not failures.

## 3 · Measurements recorded per probe (state DB `data/p0b_probes/probes.db`, append-only)

Placement timestamp; per-leg NBBO (bid/ask/sizes) and underlier quote at placement; computed mid/natural/limit; order id + tag; fill timestamp(s) and price(s) or cancel timestamp; per-leg NBBO at fill; time-to-fill; effective credit vs mid-at-placement (slippage); underlier move placement→fill (adverse-selection check); close-side order chain (prices, repricings, fill); commissions/fees from broker records; realized P&L. Broker record is authoritative; the DB is reconciled to it daily (§6).

## 4 · Deliverable and pass criterion

**Deliverable:** committed calibration table `experiments/EXP-P0B-fill-probes/CALIBRATION.md`:

1. **Fill probability by level** (pooled across underliers = primary; per underlier = secondary), Wilson 95% CIs.
2. **Time-to-fill** distribution per level (Kaplan–Meier, censored at cancel).
3. **Effective spread capture per level**: capture_ℓ = (eff_credit_ℓ − eff_credit_mkt) / QS, where QS = quoted spread of the vertical (natural-to-natural width), eff_credit_ℓ = p_ℓ·E[credit | filled at ℓ] + (1−p_ℓ)·E[credit at marketable] (unfilled probes imputed at the same-underlier marketable-cell mean — the "re-cross after failing to fill" assumption, stated here in advance). Percentile-bootstrap 95% CIs, 10,000 resamples.
4. Model comparison: measured marketable slippage vs the engine model ($0.05 entry/$0.10 exit per spread) and vs P0A's Roll estimate.

**PASS** = at n ≤ 60: the bootstrap 95% CI of capture_ℓ has **total width ≤ 0.30** (units: fraction of quoted spread) for both inside levels, pooled — i.e., CIs tight enough to bound the P1D uplift estimate within ±30% as required by the program doc. FAIL = bar unmet at n = 60; deliver the table anyway, graded "calibration-insufficient," and P1D stays blocked.

**Consequence rule (fixed now):** if measured marketable slippage is *worse* than the engine model, every Phase-1 result is re-haircut with the measured numbers before any holdout spend (program doc §2 P0B kill criteria).

## 5 · Safety invariants (enforced in config AND code, independently)

1. **1-lot HARD CAP**: `max_contracts: 1` in `configs/probe_p0b_tradier.yaml`; the scheduler independently asserts `qty == 1` on every leg of every payload before submit; the sink call is wrapped in a final assertion. Any order > 1 lot ever submitted → immediate halt + incident report.
2. Whitelist: underliers ∈ {SPY, XLI}; structure = 2-leg vertical; sell-to-open entries + buy-to-close exits only.
3. Order-count caps per day: ≤ 2 entry orders, ≤ 12 total submissions (entries + cancels + close chain).
4. Every order tagged `probe_P0B_<YYYYMMDD>_<slot>` — the reconciliation key. Orders without the tag are never touched by probe code; probe code never touches non-probe positions (the account may carry unrelated residue, e.g. EXP-800 drain — strictly out of scope).
5. Idempotency: state-DB + broker open-order check for the tag before any submission.
6. Master gate `enabled: false` until Maximus's explicit go; kill-switch env/flag checked before every submission.

## 6 · Kill criteria (any → probes halt; resume only after root-cause + Maximus ack)

1. **Any probe unfilled-and-unflattened at EOD** (broker-verified, 16:15 ET check) — the program-specified kill. Halt + same-day manual flatten instruction issued.
2. Any entry-order modification/repricing observed (chase) — halt (P1D ops kill).
3. Any order with qty ≠ 1, wrong underlier, or missing tag — halt.
4. Daily reconciliation mismatch (DB↔broker: phantom orders, missing fills, orphan legs, position after 15:45) — halt.
5. Cumulative measured friction cost (commissions + effective spread paid) > **$750**, or cumulative realized probe P&L < **−$1,500** — halt (budget guard; approved budget is "low hundreds").
6. Tradier API error rate preventing the 15:45 flatten guarantee on any day — halt at next open.

## 7 · Reconciliation protocol (daily, after close)

`scripts/p0b_reconcile.py`: pulls Tradier orders/positions/account history (same account APIs used in the broker-verified fleet review), filters tag prefix `probe_`, and diffs against the state DB: every DB probe must map to broker orders with matching tag/qty/status/fills; every probe-tagged broker order must exist in the DB; no probe-tagged open position may exist after 15:45 ET; commissions ingested from broker records. Output: `experiments/EXP-P0B-fill-probes/reconciliation/<date>.json` + one-line daily verdict appended to `RECON_LOG.md`. Any mismatch sets the halt flag the scheduler checks before every submission (kill #4).

## 8 · Budget

n ≤ 60 round trips × 2 contracts: commissions ≈ $2.60/probe (engine's $0.65/contract/side; actual Tradier schedule ingested from broker records and reported); marketable-cell spread cost, ledger-bounded ≈ $4–20/probe (XLI wider than SPY — measuring exactly that is the point). Expected total ≤ ~$600; hard stop per kill #5. No leverage, no overnight risk, max structural loss per probe ≤ $500 (SPY) / $200 (XLI).

## 9 · Amendments (ops-parameter fixes only, per the integrity rule — all dated BEFORE the first live probe)

**A1 · 2026-07-12 — NBBO transport.** Per-leg NBBO is fetched via the executor REST service's quotes route (`GET /v1/portfolio/quotes/{OCC-symbol}`, per-account Tradier session) instead of a direct `TradierProvider` client. Reason: `TRADIER_PROD_TOKEN` is provisioned only inside the executor service; the executor's chain endpoint is broken (never forwards `expiration`), but its quotes route serves per-leg venue NBBO for OCC symbols (verified read-only 2026-07-12). The measured quantity is unchanged — Tradier venue NBBO at placement — and the transport is the same audited service that carries the orders. Consequence: expiration selection enumerates Friday candidates in the 21–45 DTE window nearest 30 DTE and verifies listedness by quoting the actual contracts (a zero/absent quote = skip, never a guess). No design, schedule, level, metric, or criteria change.

**A2 · 2026-07-12 — one-day live-quotes dry run (Maximus GO).** `enabled: true` for the 2026-07-13 session with `live_submit: false`: quotes and gates exercise end-to-end; entries log `[DRY RUN — live_submit=false]`; no order reaches the executor. Dry-run results go to Maximus for review before any arming decision. This amendment does not authorize live orders.

**A3 · 2026-07-12 — TLT added to the probe schedule (Carlos instruction; BEFORE any live probe).** EXP-P1F (`reports/profitability_program/EXP-P1F.md`, commit `18e9c89`) ended **no-pass/no-kill, sample-starved**: the day-limit fill model rejected ~99% of TLT entry attempts, and only live probes can distinguish fill-model artifact from genuine capacity limit — the exact dependency the P0A ledger pre-stated for TLT ("prereg only if P0B shows real TLT spreads no worse than modeled"). Changes, all schedule-side and made before the first live probe (the integrity rule voids changes only *after* the first probe):

- Underlier whitelist → {SPY, XLI, TLT} (config + both code enforcement points). TLT probe instrument: same §2.2 structure, width **$4** (the P1F-prereg / ledger `dte30_wide3_2pctOTM` class), max structural loss $400/probe — inside the existing SPY $500 bound.
- Rotation generalized from 6 to **9 cells** (3 underliers × 3 levels), same deterministic trading-day-index key; the 2-underlier assignments are unchanged by the generalization (`rotation_cell` reduces to the old formula at N=2). With 9 cells, the ≥6-per-cell floor is reached at n = 54, inside the pre-authorized maximum n = 60 — the TLT addition **consumes the pre-authorized extension headroom rather than expanding it**.
- **Unchanged:** n ≤ 60 hard stop; 2 probes/day; slots; levels; skip rules; all §5 safety invariants (1-lot cap, tag discipline, order-count caps); all §6 kill criteria including the $750 friction / −$1,500 P&L budget guards (approved envelope not expanded); §4 deliverable and PASS bar (pooled-level CIs — TLT enters the pooled estimate and gets its own secondary per-underlier table). Trade-off stated honestly: per-cell precision for SPY/XLI drops (~10 → ~6–7 obs/cell); accepted because TLT fill reality is currently the program's binding unknown.
- **Gates untouched:** `enabled: true` remains scoped to A2's one-day dry run; `live_submit: false` stands. Arming live orders still requires the explicit go after arm review — this amendment does not authorize order flow.

## 10 · What this prereg does NOT do

No strategy inference from probe P&L; no holdout touch (forward data only); no sizing authority beyond 1 lot; no new strategy family opened (SPY verticals remain closed; the probe structure is an execution instrument); no schedule activation — that requires Maximus's explicit go, and the first live order will not be placed before it.
