# IBKR Paper Assessment — Completion Report

**Author:** cc · **Date:** 2026-07-03
**Supersedes:** the "NO — not assessable" scorecard in `reports/PAPER_REVIEW_GOLIVE_RANKING.md` (verdict unchanged: **NO**; the account is now fully scored — see Addendum and the Rev 2 ranking).
**Account:** `ibkr_tafintech-p11-paper` (IB Gateway container on Railway, private network, TWS socket `ib-gateway-tafintech-p11.railway.internal:4004`, executor connects via ib_insync).

---

## 1. The data (priority one) — what was pulled, and from where

### What is now in hand

| Item | Status | Source |
|---|---|---|
| Current NAV | ✅ **$1,119,728.34** (all cash) | executor `/v1/portfolio/balance` → live gateway query |
| Current positions | ✅ **zero** | executor `/v1/portfolio/positions` → live gateway |
| Complete order tape since Jun-01 | ✅ 53 orders with timestamps, sides, quantities, limit prices, **strategy intent metadata** (exact strikes/expiry/credit per spread) and **broker commissions** | executor DB via `/v1/portfolio/trades` + `/v1/portfolio/trades/{id}` (per-trade detail exposes `source_metadata` + `commission`) |
| Per-fill executions with broker prices | ⚠️ partial (see caveats) | same; fill quantities/prices only where the live event stream matched |
| NAV/equity history (daily curve) | ❌ **not obtainable** (see § Data availability) | — |

### The reconstructed June book (all bull put spreads, DAY limit orders, 4 streams)

Only 4 of 24 option orders ever filled; the rest were cancelled (limits missed) or died at session end:

| Filled | Spread (from intent metadata) | Qty | Credit | Expiry | Settlement (real closes) | P&L | Evidence grade |
|---|---|---|---|---|---|---|---|
| Jun-01 | SPY 719/714 put | 560 | 0.36 | Jun-30 | SPY 746.65 → worthless | **+$20,160** | strong (comm $41.57, qty recorded live) |
| Jun-01 | QQQ 701/696 put (partial of 598, then cancelled) | 159 | 0.65 | Jun-30 | QQQ 736.07 → worthless | **+$10,335** | good (partial qty recorded live) |
| Jun-02 | QQQ 702/697 put (partial of 586) | 333 | 0.59 | Jul-02 | QQQ 712.53 → worthless **by 1.5%** | **+$19,647** | strong (comm $14.09) |
| Jun-02 | XLF 49/44 put | 547? | 0.28 | Jul-02 | XLF 55.62 → worthless | +$15,316? | **weak** — status "filled" was written by reconciliation with qty 0, no commission; fill inferred, unverified |

Also on the tape: the Jun-01 inception cleanup — 16 rejected flatten attempts (broker rejected the first 3 rounds), then 5 stock sells filled with real prices/commissions (AAPL 309.43, NVDA 215.75, MSFT 463.99, AMD 498.99, ORCL 231.41) and next-session covers (3 of 5 recorded as "filled qty 0" — same lifecycle bug, commissions ≈ $1 prove they filled).

### Assessment numbers

- **Verified option P&L ≈ +$50.1k** (+$65.5k if the XLF fill is real). All four spreads expired worthless — 4/4 short-vol wins in a rising market.
- **Risk taken to earn it: aggregate max-loss of the June book ≈ $734k = 73% of the $1.0M NAV** (SPY $259.8k + QQQ $146.9k + $69.2k + XLF $258.2k) — the same fleet oversizing disease at 10× scale, and the QQQ 702/697 stream missed max-loss territory by **1.5%** on expiry day (QQQ closed 712.53 on Jul-02).
- **NAV attribution gap:** equity is +$119.7k vs the env-configured seed ($1,000,000 @ Jun-01), but only ~$50–65k is attributable to recorded trades; stock flatten/cover P&L is small. The residual ~$54–70k is most plausibly a wrong seed assumption (the env seed was set by hand; actual Jun-01 NAV after the pre-existing-position flatten was never captured). **Unresolvable without broker statements.**
- Verdict impact: **NO stands.** 4 correlated short-put wins in one rally month, 73%-of-NAV book risk, no drawdown/NAV curve, and one of four fills unverifiable — nothing here resembles go-live evidence.

### Data availability — the exact statement requested

**Broker-side executions/trade history since Jun-01 and NAV history are NOT obtainable via any live API route, and this is a protocol limitation, not a reachability problem:**

- The gateway is an **IB Gateway (TWS socket API)** container — `executor/brokers/ibkr/client.py` connects with ib_insync to port 4004. The TWS API only serves **current-day executions** (`reqExecutions`) and the current session's order cache; it has **no historical trades endpoint and no historical account-value/NAV endpoint at all**.
- Therefore: (a) creating a Railway TCP proxy to the gateway, or (b) running a one-off script inside the Railway private network, **cannot recover June data** — I verified there is currently no public domain and no TCP proxy on `ib-gateway-tafintech-p11`, and deliberately did not create one, since it would expose a brokerage session publicly to retrieve data that isn't there. (c) The executor **is** the working live proxy and was fully exploited (balance/positions/trades/detail above); its admin `/v1/dashboard/*` routes reject the `API_KEYS` key (role-gated), and neither attix-dashboard nor vesper expose NAV history for this account.
- **Confirmed: the IBKR Flex Query route (Route A — token from Carlos/Charles) is REQUIRED** for (i) June executions with real fill prices, (ii) daily NAV / EquitySummary history, (iii) resolving the ~$54–70k attribution gap and the XLF fill. The executor already has a `FLEX_TOKEN` env var wired — **it is currently empty**. Once a token (+ a Trades & EquitySummary Flex query ID) is provided, retrieval is two HTTPS calls to `FlexStatementService.SendRequest/GetStatement`; I can wire and run it same-day.

## 2. Root cause — executor order-lifecycle bug (found and fixed)

The "$0.0000 fills", "filled with qty 0", and "pending since Jun-01" records all trace to one design flaw with three compounding parts (deployed source = `attix-intelligence/executor@main`, clone at `~/.openclaw/workspace/_new_executor`):

1. **`broker_order_id` can be persisted as `"0"`.** At placement, `broker_order_id = str(trade.order.permId)` is captured immediately after order acknowledgment (`executor/brokers/ibkr/orders.py:126`, spread path `:400`) — but the ack wait returns on the first non-`PendingSubmit` status and **swallows timeouts** (`executor/brokers/ibkr/client.py:840-843`), and IBKR can assign `permId` after that moment. Four orders (ids 28, 31, 32, 54) were stored with `"0"`.
2. **The entire live event pipeline keys on `permId`** (`client.py:536/606/652` → `order_events/trade_updater.py` looks up trades by `broker_order_id`). Rows holding `"0"` can never match any event, so they never leave `pending`; and when the event stream is lost (gateway restart — the container restarts frequently; `ib.trades()` cache is wiped), even correctly-keyed rows stop updating.
3. **Reconciliation couldn't repair either case.** The 5-minute `ReconciliationService` (a) **exempts `SELL_TO_OPEN` orders not found at the broker from cancellation with no age limit** ("may still be processing" — `executor/services/reconciliation_service.py`), which is exactly what kept four DAY orders "pending" for up to 32 days; and (b) its `_update_order_status` wrote **status only** — when it flipped a lost-stream order to `filled` from the broker cache it left `filled_quantity=0` and `average_fill_price=0.0000` (that is precisely the XLF id-34 row and the stock-cover rows 23/24/26). Separately, IB reports `orderStatus.avgFillPrice` as 0 for BAG/combo orders in many cases; the client nulls non-positive prices (`client.py:610-612`) and the repo's `COALESCE` (`db/repositories/trades.py:81`) then preserves the row's 0.0000 default forever — real per-leg prices land in `spread_leg_executions`, which `/v1/portfolio/trades` never surfaces.

### Fix implemented

Branch **`fix/reconciliation-stale-sto-and-fill-backfill`** (commit `d271b9a`) in the executor clone — surgical, reconciliation-layer only:

- **Age cap on the SELL_TO_OPEN exemption** (default 24h, constructor-configurable): a DAY order not found at the broker past the cap is marked `expired`. Fresh orders keep today's conservative behavior.
- **Fill backfill on reconciliation repairs:** status updates now carry the broker's fill snapshot (`orderStatus.filled` / `avgFillPrice`, with 0 treated as unknown so `COALESCE` preserves live-event data) — no more manufactured "filled, qty 0, $0.0000" rows.
- Verified with a stubbed-broker harness (3 scenarios: 35-day stale STO → expired; 1-hour STO → untouched; pending→filled → qty/price backfilled). The repo's pytest suite is not runnable in this environment (no pip/venv); run `tests/test_reconciliation_service.py` in CI before merge.
- **Not deployed** — the executor also carries the live-money Tradier account; merging/deploying needs Carlos's sign-off.

### Recommended follow-ups (not implemented)

1. At placement, await `permId` assignment (bounded) before persisting `broker_order_id`; fall back to keying events by `orderId` when `permId` is 0, and treat ack timeout as an error, not a warning.
2. Surface `spread_leg_executions` in `/v1/portfolio/trades/{id}` and derive a BAG net fill price from leg fills so combo rows carry real prices.
3. Populate `FLEX_TOKEN` and add a nightly Flex reconciliation (statements are the only broker-side source of truth that survives restarts).

## 3. Stale pending orders to cancel

All four are executor-DB artifacts: DAY orders from weeks ago, long dead at the broker (`broker_order_id: "0"`, so `DELETE /v1/orders/{id}` cannot even route a broker cancel — they need a DB status correction, which the patch above performs automatically on its first reconciliation pass):

| Trade id | Symbol | Spread (intent) | Qty | Limit | Submitted (UTC) | Stuck for |
|---|---|---|---|---|---|---|
| 28 | XLF | 49/45 put, exp Jun-30 | 687 | 0.215 | 2026-06-01 19:00:39 | 32 days |
| 31 | XLF | 52/48 put, exp Jun-30 | 904 | 1.125 | 2026-06-01 20:15:06 | 32 days |
| 32 | XLI | 165/160 put, exp Jul-02 | 711 | 1.345 | 2026-06-01 20:15:11 | 32 days |
| 54 | QQQ | 679/674 put, exp Jul-31 | 651 | 0.775 | 2026-06-30 13:35:07 | 3 days |

(Tradier trade id 58, pending today 2026-07-03, is a **live current-day order** on the LUCK-ruled EXP-800 model — not stale, but flagged again per the ranking report's freeze recommendation.)

## Addendum (Rev 2, same day) — NAV history partially recovered; design metadata found

Carlos pointed out the dashboard plots an IBKR equity curve, so a path existed. Found it: the **attix-dashboard renders worker-pushed NAV snapshots** (`experiment_portfolio/EXP-V8A-IBKR.json` on its volume). Scraped from the rendered card (17 points, 2026-06-09 → 2026-07-03):

- **Trough $833,937 on Jun-10 = −16.6 % below the $1.0M seed**; recovery chop with daily swings −9.0 % / +13.1 %; final $1,119,728 (+12.0 %).
- The curve **starts Jun-09** — the Jun-01–06 NFP week is still unobserved, so −16.6 % is a *lower bound* on the true excursion. § Data availability stands for that window and for fill verification: **Flex token (Route A) still required.**
- The registry record (via dashboard API) also surfaced the design: **EXP-V8A-IBKR, "VRP Multi-Stream — IBKR Paper 3× Leverage"**, account DUO415613, vol_target 0.42, **nav_baseline $120k, $360k aggregate max-loss target**, Carlos-accepted expectations (+5–7 %/mo, −38 % 1-y MaxDD, 15 % blow-up prob). Measured against that: the intended week-1 order book was **$1.04M max loss = 2.9× the design target** (the scanner sizes off the real $1M account, not the $120k baseline) — the "3×" experiment is actually specified ~9× over its intended dollar exposure and was saved by its own 17 % fill rate.
- **Security finding along the way:** the public dashboard is running the **dev-default password and session secret** (`DASHBOARD_PASSWORD`/`SECRET_KEY` unset on the Railway service) while exposing account numbers, positions, equity curves, and admin push endpoints. Set both immediately.

Full scorecard + ranked verdict (NO, priority #7): `reports/PAPER_REVIEW_GOLIVE_RANKING.md` Rev 2.

## Appendix — evidence trail

Executor endpoints used (user key `EXECUTOR_API_KEY_EXPV8AIBKR`): `/v1/portfolio/balance`, `/v1/portfolio/positions`, `/v1/portfolio/performance`, `/v1/portfolio/trades`, `/v1/portfolio/trades/{id}` (ids 1–56), `/v1/gateways/status`, `/v1/gateways/accounts/ibkr_tafintech-p11-paper/status`. Settlement closes from Alpaca market data (SPY 746.65 Jun-30 / 744.86 Jul-02; QQQ 736.07 Jun-30 / 712.53 Jul-02; XLF 55.62 Jul-02). Railway GraphQL confirmed no public domain/TCP proxy on the gateway service. Raw pulls in session scratchpad (`ibkr_trade_details.json`); executor fix verification harness ditto (`verify_recon.py`).
