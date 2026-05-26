# ORCHESTRATOR_PROPOSAL.md

**Project:** Live-Trading Orchestrator (mission-control layer)
**Author:** CC1
**Date:** 2026-05-22
**Status:** DRAFT — pending Carlos approval
**Repo path:** `pilotai-credit-spreads/compass/orchestrator/` (new package)

---

## 1. Executive Summary

Today the live pipeline is two pieces glued by a JSON file:

```
exp2690_signal_generators  ──json──▶  exp2830_paper_signal_generator  ──▶  alpaca_connector
   (per-stream intent)                  (daily 09:25 ET cron)              (broker glue)
```

The CC1 audit (2026-05-22) found that the **glue is thin and silently
permissive**: degenerate proxy signals (`cross_vol_signals` uses uniform
VIX/100 IV), parameter drift between backtest and production (e.g.
`exp1220_signals` emits Δ=0.30 while the EXP-1220 backtest targets
5%-OTM ≈ Δ-0.15 to -0.20), and a single-leg fallback in
`alpaca_connector.submit_spread` that can leave a naked short put live
if the broker rejects the multi-leg request.

The **orchestrator** is the deliberate seam between *intent* (signal
generators) and *execution* (broker). It owns three responsibilities:

1. **entry_gate** — filters intent against macro/regime/event blackouts
   that backtests assume.
2. **position_sizer** — turns intent into a sized order
   (risk-per-trade × portfolio-risk × correlation-adjusted).
3. **order_router** — composes broker-safe orders, enforces all-or-
   nothing semantics for spreads, and reconciles fills.

Everything between EXP-2690 and the Alpaca API funnels through these
three modules. There is no other path to the broker in live mode.

---

## 2. Problem Statement

### 2.1 The backtest → live gap

Each backtested sleeve assumes pre-conditions that the production loop
doesn't currently check:

| Sleeve | Backtest assumption | Currently enforced live? |
|--------|--------------------|--------------------------|
| EXP-1220 (SPY) | VIX≤40, no entry within 28d of expiry, 5%-OTM strike | VIX gate ✅ · strike ❌ (uses Δ=0.30) |
| EXP-2160 (XLF/XLI) | Δ-0.30 short / Δ-0.15 long | ❌ (uses Δ-0.20 / Δ-0.10) |
| EXP-2240 (QQQ) | 5%-OTM, $5-wide | ❌ (uses Δ-0.25) |
| EXP-1770 (GLD/SLV) | Futures execution (CL=F/NG=F/GC=F/SI=F) | ❌ Alpaca paper has no futures |
| EXP-2020 (cross-vol) | Per-ticker BS-inverted IV from IronVault | ❌ Uses VIX/100 uniform proxy |
| Crisis Alpha v5 | 13-asset weekly rebalance, stress-gated | Universe ambiguity; gate ✅ |

The orchestrator centralises **canonical parameters per sleeve** so the
live system trades the strategy that was actually validated.

### 2.2 Order-execution risk

`alpaca_connector.submit_spread` (alpaca_connector.py:497) falls back
to independent single-leg orders if `MultilegOrderRequest` is
unavailable. With no per-leg limit and no atomic guarantee, a partial
fill leaves a naked short put. Today this is logged at INFO. The
orchestrator's `order_router` makes the fallback **explicit, opt-in,
and bounded**: either submit as a true multi-leg, or refuse and
generate an exception, never legged.

### 2.3 Cross-cutting concerns

- **Event blackouts** (NFP, FOMC, CPI, OPEX) — backtests skip these
  via VIX/term-structure proxies; live should know the actual calendar.
- **Portfolio risk envelope** — each sleeve sizes itself in isolation;
  no enforcement of total-portfolio gross exposure or sleeve
  correlation.
- **Reconciliation** — `daily_pnl` silently understates anchors when
  the equity log is short (alpaca_connector.py:664).
- **Stream attribution** — `_STREAM_TICKER_MAP` collides on shared
  tickers (e.g. SPY appears in EXP-1220, cross-vol, v5_hedge).

---

## 3. Architecture

### 3.1 Component diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ DAILY CRON  (09:25 ET — pre-open)                                    │
│   compass/scripts/run_orchestrator.py  (replaces exp2830 driver)     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ EXP-2690  GENERATE_ALL_SIGNALS(date)                                 │
│   raw intent: [{stream, ticker, action, delta, dte, width, ...}, …]  │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ List[SignalIntent]
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR                                                         │
│   ┌────────────────┐  ┌─────────────────┐  ┌────────────────────┐   │
│   │ entry_gate     │─▶│ position_sizer  │─▶│ order_router       │   │
│   │ macro+regime+  │  │ risk-per-trade  │  │ broker-safe orders │   │
│   │ event blackout │  │ portfolio cap   │  │ atomic multi-leg   │   │
│   │ canonical-     │  │ correlation     │  │ idempotent         │   │
│   │ param check    │  │ scaling         │  │ reconcile          │   │
│   └────────────────┘  └─────────────────┘  └────────────────────┘   │
│           │                    │                     │              │
│           ▼                    ▼                     ▼              │
│        gated.jsonl         sized.jsonl           orders.jsonl       │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ List[SpreadOrder]
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ alpaca_connector.submit_spread()                                     │
│   (existing module — no changes to public surface)                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data flow contracts

The orchestrator never mutates the upstream signal dict — each stage
emits a **new** dataclass with a strict superset of fields:

```
SignalIntent       (from EXP-2690, unchanged)
   ├─ entry_gate ─▶  GatedSignal       (+ gate_status, gate_reasons[])
   ├─ position_sizer ─▶ SizedOrder     (+ contracts, dollar_risk, port_weight)
   └─ order_router ─▶  SpreadOrder     (+ legs[], net_credit, client_order_id)
```

This makes every stage diffable, testable in isolation, and replayable
from the JSONL audit logs.

### 3.3 Filesystem layout

```
compass/orchestrator/
├── __init__.py
├── types.py              # SignalIntent, GatedSignal, SizedOrder
├── entry_gate.py         # § 4.1
├── position_sizer.py     # § 4.2
├── order_router.py       # § 4.3
├── calendars.py          # FOMC / NFP / CPI / OPEX dates
├── canonical_params.py   # per-sleeve frozen parameters (the single source of truth)
├── portfolio_state.py    # current positions, sleeve weights, gross/net exposure
├── pipeline.py           # end-to-end orchestration; CLI entry
└── tests/
    ├── test_entry_gate.py
    ├── test_position_sizer.py
    ├── test_order_router.py
    └── test_pipeline_e2e.py

compass/scripts/
└── run_orchestrator.py   # cron entry; calls pipeline.run(date, mode)
```

---

## 4. The three modules

### 4.1 `entry_gate`

**Purpose:** every backtested precondition the live signal generator
doesn't (or can't) check.

**Inputs:**
- `List[SignalIntent]` from EXP-2690
- `PortfolioState` snapshot (open positions, last fill timestamps)
- Today's date (UTC + ET-localised)

**Output:**
- `List[GatedSignal]` — every intent gets a `gate_status` in
  `{ALLOW, BLOCK, DEGRADE}` and a list of human-readable reasons.

**Gates (in evaluation order):**

| # | Gate | Source of truth | Action |
|---|------|-----------------|--------|
| 1 | Market open today | Alpaca clock + holiday calendar | BLOCK if closed |
| 2 | Already open in this sleeve | PortfolioState | BLOCK new entry; allow HOLD/CLOSE |
| 3 | Canonical-param check | `canonical_params.py` | BLOCK if Δ/DTE/width drift from backtest > tolerance |
| 4 | FOMC blackout | Fed meeting calendar | BLOCK new entries on FOMC day + 1 |
| 5 | NFP blackout | BLS NFP release calendar | BLOCK new entries on first Friday of month |
| 6 | CPI blackout | BLS CPI release calendar | DEGRADE confidence × 0.5 |
| 7 | OPEX week | Third Friday of month | DEGRADE confidence × 0.7 for monthly cycles |
| 8 | VIX > 40 | Yahoo `^VIX` (cached) | BLOCK new entries (matches EXP-1220 backtest) |
| 9 | VIX term inversion | `^VIX` vs `^VIX3M` | BLOCK if `^VIX > ^VIX3M` (matches V+F overlay) |
| 10 | Sleeve correlation cap | `PortfolioState.correlation_matrix` | DEGRADE if adding sleeve would push port corr > 0.6 |
| 11 | Stale data | `signal.date` vs `now()` | BLOCK if older than 24h |
| 12 | Untradeable instrument | Broker capability table | BLOCK GLD/SLV calendar futures legs on Alpaca paper |

Gates 4–6 use a **vetted calendar** committed to the repo (not a live
API call), regenerated quarterly. Eliminates a live-dependency on a
flaky data source.

**Canonical-param check (gate 3) is the H1/M1 fix:**

```text
canonical_params["exp1220"] = {
    "structure": "put_credit_spread",
    "otm_pct": 0.05,          # 5% OTM short
    "width": 5.0,
    "dte_target": 28,
    "profit_target": 0.50,
    "stop_mult": 2.0,
    "min_spacing_days": 10,
    "risk_per_trade_pct": 0.03,
    "max_contracts": 4,
    "vix_block": 40.0,
}
```

If `signal.delta` or `signal.dte` deviates from this canonical record
by more than configured tolerance, the gate emits BLOCK with reason
`"param_drift: signal.delta=0.30 ≠ canonical otm_pct→0.18"`. This
forces upstream EXP-2690 fixes rather than silently trading the wrong
strike.

### 4.2 `position_sizer`

**Purpose:** turn a gated *intent* into a *number of contracts* that
respects per-sleeve risk, portfolio risk envelope, and correlation
adjustments.

**Inputs:**
- `List[GatedSignal]` (only those with `gate_status=ALLOW` or `DEGRADE`)
- `PortfolioState` (current equity, cash, existing dollar-at-risk)
- Live option chain snapshot from `alpaca_connector.get_chain(...)`
  for the candidate expiration

**Output:**
- `List[SizedOrder]` with `contracts`, `short_strike`, `long_strike`,
  `expected_credit`, `max_loss_dollars`, `port_weight_consumed`

**Sizing rules (applied in order):**

1. **Per-sleeve risk-per-trade**:
   `risk_$ = equity × sleeve.risk_per_trade_pct × confidence`
2. **Contracts from max-loss**:
   `contracts = floor(risk_$ / (max_loss_per_spread × 100))`
3. **Per-sleeve contract cap**:
   `contracts = min(contracts, sleeve.max_contracts)`
4. **Liquidity cap**: `contracts ≤ 0.05 × min(short_oi, long_oi)`
5. **Portfolio gross cap**:
   `total_dollar_risk ≤ equity × PORT_RISK_CAP_PCT (default 0.20)`
6. **Correlation scale**:
   If new sleeve's expected correlation to existing book > 0.5,
   scale `contracts × correlation_penalty(ρ)` per Markowitz haircut.
7. **Minimum size floor**: if final contracts < 1, drop the order.

The sizer **never** picks strikes — it consumes the strikes that
EXP-2690 expressed as intent (delta or OTM-pct target), looks them up
on the live chain, and reports back the actual strikes/credits.

**Why we need this layer at all:** today each sleeve sizes itself in
isolation. Two correlated sleeves can both fully load risk-per-trade
on the same day, doubling exposure. Position sizer enforces the
portfolio-level invariant.

### 4.3 `order_router`

**Purpose:** convert `SizedOrder` → broker-safe `SpreadOrder`,
submit, monitor, reconcile.

**Inputs:** `List[SizedOrder]`, `AlpacaConnector` handle
**Output:** `List[SpreadOrder]` with broker IDs + final status

**Responsibilities:**

1. **OCC symbol construction** — already in
   `alpaca_connector.build_occ_symbol`; orchestrator just wires it.
2. **Multi-leg atomicity** — *prefer* `MultilegOrderRequest`. If
   unavailable, refuse the order with status `REJECTED_NO_MLEG`.
   **Never** silently leg into the spread. (H2 fix.)
3. **Limit-price construction** — convert sleeve's
   `expected_credit` into a net-credit limit at
   `max(0.05, expected_credit × 0.90)` (10% slippage tolerance) to
   avoid market orders entirely.
4. **Idempotency** — every order gets a `client_order_id` of
   `{date}-{stream}-{ticker}-{exp}-{short_K}-{long_K}` so a re-run
   on the same calendar day is a no-op.
5. **TIF**: `DAY` by default. Cancelled at 15:55 ET by a paired
   `cleanup_orders` invocation.
6. **Submission window** — orchestrator refuses to send between
   09:30:00 and 09:32:00 ET (opening-rotation noise) and between
   15:58:00 and 16:00:00 ET (closing imbalance). Configurable.
7. **Reconciliation** — after submission, call
   `alpaca_connector.reconcile(intended)` and emit a structured
   diff. Discrepancies (`MISSING`, `ORPHAN`, `UNDER`, `OVER`) are
   surfaced to the operator log; nothing auto-heals.

**Equity execution path** (Crisis Alpha v5):
The v5 sleeve outputs per-ticker weights, not options. The router
has a parallel path that produces `MarketOrderRequest` /
`LimitOrderRequest` for equities, sized to a target dollar weight.

**Untradeable instruments** (GLD/SLV futures legs):
The router consults the broker-capability table. Futures legs on
Alpaca paper resolve to BLOCKED with reason
`broker_unsupported: GC=F not tradable on Alpaca paper`. This makes
the M4 issue visible instead of silent.

---

## 5. Integration with existing code

### 5.1 What we change

| File | Change |
|------|--------|
| `compass/orchestrator/` | **NEW** package, all logic lives here |
| `compass/scripts/run_orchestrator.py` | **NEW** cron entry |
| `compass/exp2830_paper_signal_generator.py` | **DEPRECATED** — kept for one release as `--legacy` mode for diff comparison; deleted in v2 |
| `compass/exp2690_signal_generators.py` | **READ-ONLY** — orchestrator consumes its output verbatim |
| `compass/alpaca_connector.py` | **READ-ONLY** for v1 — fixes H2 (no silent legging) ride in the router, not the connector. Connector cleanups (L8/L9/L11) ship as a separate PR. |
| `main.py` | **UNCHANGED** — legacy `CreditSpreadSystem` (alerts path) is orthogonal. Orchestrator is a new code path opted in via cron. |
| `compass/risk_gate.py` | **AUDITED** — anything we can reuse, we import; do not duplicate logic. |

### 5.2 What we read from upstream

The orchestrator imports:

- `compass.exp2690_signal_generators.generate_all_signals(date)`
  → `List[Dict]` (the schema documented in EXP-2690 header)
- `compass.alpaca_connector.AlpacaConnector` (no subclassing — pure
  composition)
- `compass.exp2600_north_star_v8.PORTFOLIO_WEIGHTS` for the sleeve
  weights baseline

### 5.3 What we don't touch

- No changes to any `exp2160`, `exp2240`, `exp1770`, `exp2020`,
  `crisis_alpha_v5` business logic. They keep emitting their current
  intent through EXP-2690.
- `IronVault` and `data/options_cache.db` are read-only inputs.
- Rule Zero is preserved end-to-end: no synthetic chain, no
  fabricated quote. Every IV lookup goes through Alpaca's live
  chain endpoint at execution time.

---

## 6. Daily run lifecycle

### 6.1 Pre-market (09:25 ET)

```
1. cron triggers run_orchestrator.py --mode=paper
2. pipeline.run(date=today, mode="paper"):
   a. signals = exp2690.generate_all_signals(today)
   b. portfolio = PortfolioState.load(alpaca_connector)
   c. gated  = entry_gate.evaluate(signals, portfolio, today)
   d. sized  = position_sizer.size(gated, portfolio, chain_fetcher)
   e. orders = order_router.submit(sized, alpaca_connector)
   f. write JSONL audit for each stage
   g. emit summary to operator log (and Telegram if configured)
3. Exit 0 if all stages completed (regardless of business outcome)
4. Exit non-zero ONLY on hard failure (auth, network, schema)
```

### 6.2 Intra-day

The orchestrator is **not** a daemon. It runs once at 09:25 ET. A
separate, smaller cron at 15:55 ET runs
`run_orchestrator.py --mode=cleanup` which:
- Cancels unfilled DAY orders.
- Snapshots Alpaca positions to the equity log.
- Computes daily P&L via `alpaca_connector.daily_pnl`.

Optional: a 12:00 ET `--mode=reconcile` checks for orphan positions
mid-day.

### 6.3 Modes

| Mode | Effect |
|------|--------|
| `paper` | Submits to Alpaca paper (default) |
| `live` | Submits to Alpaca live — requires `--confirm-live` flag *and* `ALPACA_PAPER=false` *and* an operator-signed config token |
| `dry-run` | Runs the pipeline; writes JSONL audit; never calls `submit_spread` |
| `replay` | Reads a historical JSONL audit and re-evaluates without broker calls (for regression tests) |
| `cleanup` | EOD: cancel + snapshot equity |
| `reconcile` | Diff intended vs broker; alert on mismatch |

---

## 7. Dependencies

### 7.1 New runtime dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `pandas_market_calendars` | NYSE holiday calendar | ≥ 4.0 |
| `python-dateutil` | Already present | ≥ 2.8 |

Everything else (Alpaca, yfinance, scipy, pandas, numpy) is already
in the environment.

### 7.2 New environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `ORCHESTRATOR_MODE` | `paper` | Default mode if `--mode` unset |
| `ORCHESTRATOR_PORT_RISK_CAP_PCT` | `0.20` | Global dollar-at-risk cap |
| `ORCHESTRATOR_AUDIT_DIR` | `compass/logs/orchestrator/` | JSONL output |
| `ORCHESTRATOR_CONFIRM_LIVE_TOKEN` | unset | Required for `--mode=live` |

Existing Alpaca / IronVault credentials are unchanged.

### 7.3 API requirements

- **Alpaca paper API** (existing) — multi-leg options endpoint:
  `POST /v2/orders` with `order_class=mleg`. Already used by
  `alpaca_connector.submit_spread`.
- **Alpaca chain endpoint** — `GET /v1beta1/options/snapshots/{ticker}`
  for live strike → bid/ask. Currently unused; we'll add a thin
  wrapper in `alpaca_connector.get_chain(ticker, expiration)` as a
  side-PR (kept ≤ 50 LOC, no behaviour change to existing methods).
- **Yahoo** (existing) — `^VIX`, `^VIX3M`, ticker spot. Read-only.

### 7.4 Configuration files

- `compass/orchestrator/canonical_params.yaml` — frozen sleeve
  parameters. PR review required to change.
- `compass/orchestrator/calendars/fomc_2026.csv`,
  `nfp_2026.csv`, `cpi_2026.csv` — vetted event dates.
- `compass/orchestrator/broker_capability.yaml` — what each broker
  can trade.

---

## 8. Testing plan

### 8.1 Unit tests (mandatory, 100% line coverage on `entry_gate`, `position_sizer`)

- **entry_gate**: one test per gate. Property-based tests for the
  param-drift comparator (Hypothesis).
- **position_sizer**: golden-master tests against hand-computed
  contract counts for each of the 8 sleeves at $50k / $100k / $1M
  capital tiers, with and without correlation penalty.
- **order_router**: mock `AlpacaConnector`. Tests for:
  - MLEG present → submits MLEG.
  - MLEG ImportError → returns `REJECTED_NO_MLEG`, no legged orders.
  - Duplicate `client_order_id` → no double-submit.
  - Submission outside the trading window → REJECTED.

### 8.2 Integration tests

- Replay one full backtested day (e.g. 2024-03-15) through the
  pipeline against a sandboxed `AlpacaConnector` that records calls.
  Assert that emitted `SpreadOrder` set matches a golden manifest.
- Run the EXP-1220 backtest in `replay` mode for 2020–2025 and
  confirm the orchestrator's gated signal count matches what the
  backtest accepted, within a documented tolerance (events that
  exist in the live calendar but not in the backtest's heuristic
  proxies).

### 8.3 Soak test

- 5 trading days against Alpaca **paper** in `paper` mode with the
  audit log + reconciliation diff inspected manually each morning.
- Acceptance: zero orphan positions, zero MLEG fallback events, all
  intended sizes match within ±1 contract.

### 8.4 Failure-mode tests

- Kill broker mid-submission → no half-spreads in audit log.
- Inject `^VIX` data outage → orchestrator BLOCKs all VIX-gated
  sleeves, doesn't crash.
- Empty calendar file → fail closed (BLOCK everything, alert).

---

## 9. Rollout phases

### Phase 0 — Specification freeze (current)

- This document accepted by Carlos.
- `canonical_params.yaml` reviewed against each sleeve's backtest.
- CC1 audit issues mapped to either "fixed by orchestrator" or
  "deferred / separate PR".

### Phase 1 — Skeleton + unit tests

- Land `compass/orchestrator/` package with empty modules and full
  type signatures.
- Land `canonical_params.yaml` and the calendar CSVs.
- All unit tests written, all gates implemented as pure functions.
- `--mode=dry-run` runs end-to-end against a recorded EXP-2690
  output. No broker calls.

### Phase 2 — Paper integration

- `--mode=paper` enabled. Cron at 09:25 ET runs the orchestrator
  alongside the legacy `exp2830` driver (parallel mode).
- A nightly diff script compares the two outputs; discrepancies
  surface as warnings, not failures.
- `exp2830` remains the source of truth for actual order
  submission during this phase.

### Phase 3 — Cutover

- After two consecutive weeks of zero unexplained diffs, flip the
  cron to call `run_orchestrator.py` instead of `exp2830`.
- `exp2830` is renamed `exp2830_legacy.py` and retained for one
  release as a replay benchmark.

### Phase 4 — Live (paper → real money) — *Carlos approval required*

- `--mode=live` enabled only after Phase 3 has logged ≥ 60 days
  of clean paper runs.
- Live cutover starts at 10% of the model-portfolio sizing.
- Sizing ramp is governed by a `LIVE_RAMP_PCT` env var that
  starts at 0.10 and increases on a weekly review cadence.

### Phase 5 — Steady state

- `exp2830_legacy.py` deleted.
- Audit logs retained 5 years.
- Quarterly review of canonical parameters and calendars.

---

## 10. Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------:|-------:|------------|
| MLEG endpoint quietly changes | Low | High | Health check on connector startup; refuse fallback (H2 fix) |
| Calendar CSV stale (missed FOMC) | Med | High | Quarterly regen; gate fails closed if file > 100 days old |
| Live chain endpoint outage | Med | Med | Sizer falls back to last cached chain ≤ 60 min old; else BLOCK |
| Idempotent `client_order_id` collision | Low | Med | Include expiry + strikes; entropy nonce on collision |
| Orchestrator clock skew | Low | Med | NTP check at startup; abort if drift > 5s |
| Over-fitted canonical params | Med | Low | Params are frozen *snapshots* of the backtest; changes require PR + Carlos signoff |
| Operator runs `--mode=live` by mistake | Low | High | Requires three conditions: flag + env var + signed token |

---

## 11. Open questions for Carlos

1. **Portfolio-risk cap** — is 20% gross dollar-at-risk the right
   default, or do we want it equity-tier-dependent (e.g. 30% under
   $250k, 15% above)?
2. **Live ramp** — start at 10% and weekly review, or smaller initial
   tranche?
3. **Correlation scaling** — should we use realised correlation from
   the prior 60 trading days, or the static backtest correlation
   matrix from EXP-2600 (north_star_v8)?
4. **Calendar source** — committed CSVs (cheap, manual quarterly
   refresh) or a paid FRED/Bloomberg calendar API (live, costs)?
5. **`generate_today_signals` upstream fixes** — the orchestrator
   *catches* the param-drift problem but doesn't *fix* the upstream
   generator. Do we want a parallel PR to align EXP-2690 with
   `canonical_params.yaml`, or accept that the orchestrator is the
   source of truth and EXP-2690 becomes purely advisory?

---

## 12. Appendix A — Interface schemas

```python
# compass/orchestrator/types.py

@dataclass(frozen=True)
class SignalIntent:
    stream: str
    date: str            # YYYY-MM-DD
    ticker: str
    action: Literal["OPEN", "HOLD", "BLOCKED", "NONE", "ERROR"]
    direction: Optional[str]
    delta: Optional[float]
    dte: Optional[int]
    width: Optional[float]
    weight: float
    confidence: float
    notes: str
    legs: Optional[List[Dict]] = None

@dataclass(frozen=True)
class GatedSignal:
    intent: SignalIntent
    gate_status: Literal["ALLOW", "BLOCK", "DEGRADE"]
    gate_reasons: List[str]
    confidence_adj: float           # multiplier applied by DEGRADE gates

@dataclass(frozen=True)
class SizedOrder:
    gated: GatedSignal
    contracts: int
    short_strike: float
    long_strike: float
    expected_credit: float
    max_loss_dollars: float
    port_weight_consumed: float
    expiration: str

# alpaca_connector.SpreadOrder already exists; we re-use it.
```

## 13. Appendix B — Audit JSONL schema

Each pipeline stage appends one JSON object per signal to its log:

```
compass/logs/orchestrator/2026-05-22/
├── 01_intent.jsonl       # raw EXP-2690 output
├── 02_gated.jsonl        # post-entry_gate
├── 03_sized.jsonl        # post-position_sizer
├── 04_orders.jsonl       # post-router (broker IDs attached)
└── 05_reconcile.jsonl    # post-fill diff
```

Each line is the corresponding dataclass serialised with
`dataclasses.asdict()` + ISO timestamps. The JSONL format makes
replay and diff trivial.

---

## 14. Approval

- [ ] Carlos — proposal approved as written
- [ ] Carlos — Section 11 open questions answered
- [ ] CC1 — Phase 1 skeleton + tests landed
- [ ] CC1 — Phase 2 parallel paper run started
- [ ] Carlos — Phase 3 cutover authorised
- [ ] Carlos — Phase 4 live cutover authorised (separate signoff)

---

*End of proposal. Companion document: `ORCHESTRATOR_EXPLAINED.md`
(conceptual, non-technical reader).*
