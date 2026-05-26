# CC4 FAILURE MODES — Order Execution

**Auditor:** CC4 (skeptical mode, assume total failure)
**Date:** 2026-05-24
**Scope:** From "scanner has decided to trade X" → "order is in Alpaca and DB"
**Method:** Static code audit of `compass/alpaca_connector.py`, `strategy/alpaca_provider.py`, `execution/execution_engine.py`, `compass/orchestrator/*`, call sites in `scripts/run_exp1220.py`.
**Tone:** Brutal. Every red flag enumerated. Severity is unflinching.

---

## TL;DR — Critical Pre-Monday Findings

| # | Severity | Title | Where |
|---|---|---|---|
| F-01 | 🔴 CRITICAL | **`AlpacaConnector` reads wrong env var (`ALPACA_SECRET_KEY` ≠ `ALPACA_API_SECRET`)** — silent auth failure on the orchestrator path | `compass/alpaca_connector.py:67` |
| F-02 | 🔴 CRITICAL | **MLEG fallback in `AlpacaConnector` submits independent single-leg orders** — leaves naked option exposure on partial submission | `compass/alpaca_connector.py:497-510` |
| F-03 | 🔴 CRITICAL | **Iron-condor non-atomic** — submitted as 2 separate 2-leg MLEGs; if 2nd wing fails and cancel of 1st wing fails → naked short put or short call | `execution/execution_engine.py:560-597` |
| F-04 | 🔴 CRITICAL | **Straddle non-atomic** — two single-leg orders; same naked-exposure pattern, no MLEG protection | `execution/execution_engine.py:641-700` |
| F-05 | 🔴 CRITICAL | **`limit_price=None` → MARKET ORDER on options** — both code paths silently fall through to market on illiquid 0DTE-style chains | `strategy/alpaca_provider.py:327-334`, `compass/alpaca_connector.py:525` |
| F-06 | 🟠 HIGH | **Clock-check fails open** — if Alpaca's `/v2/clock` errors, `is_open=None` and orders submit anyway. Sunday-evening misfire = real orders | `execution/execution_engine.py:390` |
| F-07 | 🟠 HIGH | **`find_option_symbol` silently substitutes nearest expiration** — a 0DTE intent becomes a different DTE if target is missing | `strategy/alpaca_provider.py:251-281` |
| F-08 | 🟠 HIGH | **Cancel-after-partial-IC failure is logged but not Telegrammed** — naked half-IC requires "manual intervention" but no escalation alert | `execution/execution_engine.py:593-596` |
| F-09 | 🟠 HIGH | **Circuit breaker opens after 5 fails / blocks 60s** — one bad request stream kills all orders in window; 09:25 ET window is only ~5 min wide before 09:30 open | `strategy/alpaca_provider.py:148`, `_NO_RETRY` |
| F-10 | 🟠 HIGH | **Two competing connector implementations live in the repo** with different submission semantics (`compass/alpaca_connector.py` vs `strategy/alpaca_provider.py`). Active scanners differ in which they use. | repo-wide |
| F-11 | 🟡 MEDIUM | **IC wing limit_price = credit/2 (naive 50/50 split)** — real-world wing credits are asymmetric; submitted limits won't match net credit | `execution/execution_engine.py:557-558` |
| F-12 | 🟡 MEDIUM | **Straddle per-leg limit = abs(credit/2)** — assumes equal-priced legs; for delta-asymmetric event straddles this prices both legs wrong | `execution/execution_engine.py:630` |
| F-13 | 🟡 MEDIUM | **Retry policy `max_retries=2, base_delay=1.0`** — outage > 7 seconds exhausts retries entirely | `strategy/alpaca_provider.py:342, 441, 499` |
| F-14 | 🟡 MEDIUM | **Stale-pending recovery window = 60 min** — a crashed submission blocks retries for an hour. 09:25 + 60-min lock = 10:25 unlock, past peak entry window | `execution/execution_engine.py:241` |
| F-15 | 🟡 MEDIUM | **`CircuitOpenError` in `_NO_RETRY` AND on `_submit_mleg_order`** — once any 5 submissions fail, every subsequent order in the same scanner-run also fails with no retry | `strategy/alpaca_provider.py:37, 336` |
| F-16 | 🟡 MEDIUM | **`client_order_id` timestamp collision in `AlpacaConnector`** — default `f"{stream}-{strategy}-{YYYYMMDDHHMMSS}"` (1-sec resolution) collides if two scanners hit submit simultaneously | `compass/alpaca_connector.py:460` |
| F-17 | 🟢 LOW | **Drawdown CB uses closed-trade P&L, not live equity** — lags actual drawdown by however long it takes a position to close | `execution/execution_engine.py:502-540` |
| F-18 | 🟢 LOW | **OCC symbol root NOT padded to 6 chars in `AlpacaConnector`** but IS padded in `AlpacaProvider`. Alpaca tolerates both but inconsistency is a trip hazard | `compass/alpaca_connector.py:165` vs `strategy/alpaca_provider.py:222` |

**Verdict:** Orders will likely submit Monday IF (a) only `strategy/alpaca_provider.py` path is exercised and (b) market data is clean. But the failure modes around F-02/F-03/F-04 mean a single bad fill can leave naked option positions, and F-01 means anything routing through `AlpacaConnector` will not authenticate at all.

---

## F-01 (CRITICAL) — Env Var Name Mismatch Will Silently Break Auth

### Scenario
The orchestrator pipeline (`compass/orchestrator/pipeline.py:397-398`) imports and calls:
```python
from compass.alpaca_connector import AlpacaConnector
return AlpacaConnector.from_env()
```
`from_env()` reads:
```python
ENV_KEY    = "ALPACA_API_KEY"
ENV_SECRET = "ALPACA_SECRET_KEY"   # ← wrong name
secret = os.environ.get(ENV_SECRET, "")
```

### What breaks
Railway env vars are named `ALPACA_API_SECRET` / `ALPACA_API_SECRET_EXP400` (verified across `scheduler/jobs.py`, `shared/credentials.py`, `sentinel/*`, `.env.exp*` files, `scripts/*`). The orchestrator path reads `ALPACA_SECRET_KEY`, gets the empty string, then logs a warning at line 234:
```
"Alpaca credentials missing (ALPACA_API_KEY / ALPACA_SECRET_KEY unset)"
```
And then continues in **offline mode** (`self._sdk = "none"`, line 242). Every `submit_spread()` call returns `status="REJECTED"` with reason "no SDK" (line 452-456).

### Safety net
None. The orchestrator pipeline does not validate `health_check().ok` before submitting orders in all paths.

### Recovery
**Fix in code**: change line 67 to `ENV_SECRET = "ALPACA_API_SECRET"` (matching every other component in the repo) and bump the docstring at lines 24-29 accordingly.

### Blast radius
Any experiment routing through the orchestrator (EXP-2830 was the canonical user; per PR #43 that's now removed from vesper, but `compass/dollar_notional_sizer.py:411` still calls `connector.submit_spread()` so this codepath remains reachable from non-scheduler entrypoints — e.g., manual reruns, smoke tests).

### Reproduction
```bash
unset ALPACA_SECRET_KEY
export ALPACA_API_KEY=test ALPACA_API_SECRET=test
python3 -c "from compass.alpaca_connector import AlpacaConnector; c=AlpacaConnector.from_env(); print('SDK:', c._sdk)"
# Expected: SDK: none
```

---

## F-02 (CRITICAL) — `AlpacaConnector.submit_spread` Fallback Submits Independent Legs

### Scenario
`compass/alpaca_connector.py:442-510`:

```python
try:
    from alpaca.trading.requests import OptionLegRequest, MultilegOrderRequest
    ...
    resp = self._trading_client.submit_order(order_data=req)
    return order
except ImportError:
    LOG.info("MLEG not available in alpaca-py; falling back to single-leg")

# Fallback: submit each leg as an independent order
for i, leg in enumerate(order.legs):
    try:
        leg_id = self._submit_single_leg(leg, f"{order.client_order_id}-L{i}")
        if leg_id and not first_id:
            first_id = leg_id
            submitted_any = True
    except Exception as e:
        LOG.error("leg %d submission failed: %s", i, e)
order.status = "SUBMITTED" if submitted_any else "REJECTED"
```

### What breaks
For a bull-put-spread (SELL short put + BUY long put):
- Leg 0 (sell short put) submits successfully → live short option in account.
- Leg 1 (buy long put) raises (rate limit, malformed symbol, network blip) → caught and logged.
- `submitted_any = True`, status returned as `"SUBMITTED"`.
- Trade is now a **naked short put**, with full undefined-risk exposure on a paper account that may not have the buying power.

### Safety net
None. Status `"SUBMITTED"` is indistinguishable from success at the call site. The caller has no signal that one leg failed.

### Why this fires
The `ImportError` path is taken when `alpaca-py` is installed but at an older version that lacks `OptionLegRequest`/`MultilegOrderRequest`. `requirements-scheduler.txt` should pin alpaca-py ≥ 0.43; **[LIVE-VERIFY]** the actual installed version on Railway.

### Recovery
- **Best fix:** if MLEG import fails, **REJECT the order** rather than fall back to independent legs. Raise an exception, fail loud.
- **Or:** wrap the fallback in `try/finally` that cancels submitted legs if any subsequent leg fails.
- **Or:** depend on the broker's broker-side bracket — but Alpaca does not offer atomic multi-leg via single-leg orders.

### Reproduction
Mock `alpaca-py` to raise `ImportError` on `MultilegOrderRequest`, then call `submit_spread` with a 2-leg `SpreadOrder` where the second leg's symbol is invalid. Observe naked first leg.

---

## F-03 (CRITICAL) — Iron Condors Are NOT Atomic at Alpaca

### Scenario
`execution/execution_engine.py:560-597`. An iron condor is submitted as **two separate `submit_credit_spread` calls** (put wing, then call wing):

```python
put_result = self.alpaca.submit_credit_spread(spread_type="bull_put", ...)
if put_result.get("status") != "submitted":
    return {"status": "partial_error", ...}

call_result = self.alpaca.submit_credit_spread(spread_type="bear_call", ...)
if call_result.get("status") != "submitted":
    # Put wing is live — attempt to cancel
    try:
        self.alpaca.cancel_order(put_order_id)
    except Exception as cancel_err:
        logger.error("CRITICAL — put wing cancel FAILED ... Manual intervention required.")
```

### What breaks
The put wing executes the MLEG correctly (atomic, 2 legs filled together). But between put-wing submission and call-wing submission you have a **bull-put spread on its own** — defined-risk, but not the intended iron condor risk profile.

If the call wing submission then fails (rate limit, drawdown CB tripped between the two calls, network blip), the code tries to cancel the put wing. If that cancel **also** fails (Alpaca returns 5xx, the order already filled, or network), you are left holding **only the bull-put spread**, with intended hedging that never landed.

### Safety net
- Logger error at line 593-596 — **but no Telegram or Sentinel alert wired in here**.
- `partial_error` status is returned to the caller but the caller (`submit_opportunity`) treats it the same as other failures and marks the DB row `failed_open`. **The DB row says failed_open but Alpaca holds a live position.**

### Why this fires
Most likely trigger: drawdown CB tripping between the two `submit_credit_spread` calls (each does its own `_check_drawdown_cb` indirectly via fresh `get_account` queries). Less likely but possible: Alpaca rate limit on the call wing.

### Recovery
Submit the iron condor as a **single 4-leg MLEG order**. Alpaca supports 4-leg MLEG since 2024. The current 2-wing decomposition is a defensive simplification that introduces more failure modes than it removes.

Until that fix lands: when `cancel_order` fails, **Telegram-CRITICAL** the operator with the exact symbol, side, qty, and DB row ID.

---

## F-04 (CRITICAL) — Straddle Submission Has Same Non-Atomic Problem

### Scenario
`execution/execution_engine.py:641-700`. Same pattern: call leg first, put leg second, cancel-on-failure of the first if the second fails.

### What breaks
For a short strangle, if the call leg fills (sell-to-open) but the put leg fails to submit and the cancel of the call leg also fails → **naked short call**, undefined upside risk.

For a long straddle (debit), if the call leg buys but put leg fails — at worst you over-pay for a directional bet rather than the volatility bet that was intended. Less severe than the short case but still wrong.

### Safety net
Same as F-03: logger.error only.

### Recovery
Same: use 2-leg MLEG with `OrderClass.MLEG`. The strategy/alpaca_provider.py already supports MLEG for credit spreads — extend it to straddles.

---

## F-05 (CRITICAL) — `limit_price=None` → Market Order on Options

### Scenario
Both code paths fall through to MARKET orders when `limit_price` is `None`:

`strategy/alpaca_provider.py:326-334`:
```python
else:
    from alpaca.trading.requests import MarketOrderRequest
    order_req = MarketOrderRequest(
        qty=contracts,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        legs=legs,
        ...
    )
```

`compass/alpaca_connector.py:525-528`:
```python
else:
    req = MarketOrderRequest(
        symbol=occ, qty=leg.quantity, side=side,
        time_in_force=TimeInForce.DAY, client_order_id=client_id,
    )
```

### What breaks
Market orders on illiquid options chains (0DTE far-OTM strikes, weeklies on low-volume names) routinely fill **dollars** away from mid. A market order on a $0.50 mid-quoted option can fill at $1.20 or $0.05.

For a credit-spread strategy, this completely destroys the trade thesis — you may pay a debit when you intended to collect a credit.

### What triggers `limit_price=None`?
In `execution_engine.py:417`: `limit_price=credit if credit > 0 else None`. So whenever `credit` is 0 or negative — i.e., for **any debit trade or any scan that computed credit=0 due to data issues** — the code submits a market order with no price discipline.

This is exactly the failure mode you would NOT want. A scanner that returns `credit=0` because IronVault returned an empty option chain produces a MARKET order. Combined with F-03 the consequences cascade.

### Safety net
None at the submission layer. There is no "minimum credit" floor in `submit_credit_spread`.

### Recovery
- Reject orders where `limit_price is None` entirely, unless explicitly opted in via a `allow_market_orders=True` flag.
- Or: compute a sensible limit (e.g., last-known mid ± 5%) and refuse to submit otherwise.

---

## F-06 (HIGH) — Clock Check Fail-Open Lets Sunday Orders Through

`execution/execution_engine.py:372-390`:

```python
clock = self.alpaca.get_market_clock()
is_open = clock.get("is_open")
if is_open is False:
    self._mark_pending_failed(client_id, f"market_closed: next_open={next_open}")
    return {"status": "market_closed", ...}
# is_open=None means clock check failed — fail open (don't block)
```

### What breaks
If `get_market_clock` raises or returns `{}` (network error, Alpaca outage, throttle), `is_open=None`, and the order **submits anyway**. If this happens overnight on a holiday or weekend due to a missed-fire restart, real orders go in.

Compounding: Railway misfire grace times in `scheduler/main.py` allow up to 5 min late firing. If a Sunday-evening restart triggers a missed Friday 09:25 cron, the scanners run on Sunday at restart time. If Alpaca clock check then fails…

### Recovery
Default to **fail-closed**: if `is_open is None`, refuse to submit and Telegram an alert. The few minutes of false blocks during Alpaca outages are far cheaper than one Sunday-evening misfire.

---

## F-07 (HIGH) — Option Symbol Resolver Silently Substitutes Expiration

`strategy/alpaca_provider.py:251-281`:

```python
# 2. Exact expiration not available — find nearest available expiration >= 1 DTE
...
best = min(contracts2, key=lambda c: abs((dt - target_date).days))
actual_exp = str(best.expiration_date)
logger.warning("expiration substituted...")
return best.symbol
```

### What breaks
A 0DTE strategy intending to enter SPY 0DTE puts on Monday is given a Tuesday expiration if the 0DTE chain isn't yet listed (option contracts list at varying times during the day). Position holding period and pricing are completely different from backtest.

There IS an `actual_expiration` field returned and `execution_engine.py:427-442` updates the DB row to match — so the DB reflects what happened — but the strategy intent is silently corrupted.

### Safety net
Logger warning. DB update of the actual expiration. **No "are you sure?" gate.**

### Recovery
- Add a strategy-level flag `allow_expiration_substitution: bool` in each experiment config. Default False for 0DTE strategies, True only where the strategy explicitly tolerates it.
- Or: in `find_option_symbol`, raise unless caller explicitly opts in.

---

## F-08 (HIGH) — Cancel-After-Partial Failure Has No Operator Alert

`execution/execution_engine.py:593-596`:

```python
except Exception as cancel_err:
    logger.error(
        "ExecutionEngine: CRITICAL — put wing cancel FAILED for order_id=%s: %s. Manual intervention required.",
        put_order_id, cancel_err,
    )
```

### What breaks
The word "CRITICAL" appears in the log line, but **logger.error → Railway log stream**. Nothing automatically pages a human. The `[ORDER FAIL]` Telegram pattern (used elsewhere for order rejections) is missing here.

### Safety net
The next `job_monitor_poll` at the 5-minute interval *might* surface the orphan position via reconciliation — but the iron-condor was supposed to be present as 4 legs; reconciliation would flag missing legs, not orphan.

### Recovery
Wrap the cancel-failure branch with `send_telegram(f"[CRITICAL] IC half-leg orphan: order_id={put_order_id} ...")`.

---

## F-09 (HIGH) — Circuit Breaker Blocks Whole Submission Window

`strategy/alpaca_provider.py:148`:
```python
self._circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60)
```

`_NO_RETRY = (ValueError, TypeError, CircuitOpenError)`

### What breaks
5 consecutive submission failures (e.g., 5 invalid OCC symbols due to a bad data source) open the breaker. For the next **60 seconds**, every `submit_order` call raises `CircuitOpenError`. Since `CircuitOpenError` is in `_NO_RETRY`, the retry decorator does nothing — the order is dead.

The per-experiment scanner job has a `misfire_grace_time=300` (5 min) but no internal retry beyond `max_retries=2`. If the scanner picks 8 opportunities and the first 5 fail consecutively, the remaining 3 are dead.

### Safety net
None. The breaker is per-`AlpacaProvider` instance, and instances are scanner-scoped, so the next scanner run (next day) starts fresh.

### Recovery
- Lower `failure_threshold` won't help (it makes it worse).
- Better: add scenarios where breaker resets early on successful health check.
- Or: per-symbol breakers rather than global.

---

## F-10 (HIGH) — Two Competing Connector Implementations Exist

This repo has TWO Alpaca-submission implementations with **different semantics**:

| | `strategy/alpaca_provider.py` (`AlpacaProvider`) | `compass/alpaca_connector.py` (`AlpacaConnector`) |
|---|---|---|
| Env vars | `ALPACA_API_KEY`/`ALPACA_API_SECRET` (set externally) | `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (F-01 bug) |
| MLEG | Always uses MLEG via `LimitOrderRequest(legs=...)` | Uses MLEG when import works; **falls back to independent legs** (F-02) |
| Retries | 2× with backoff, 429 → Retry-After respected | None — single attempt |
| Circuit breaker | Yes (5/60s) | No |
| OCC root padding | Padded to 6 (`f"{ticker:<6}"`) | Not padded |
| Used by | `execution/execution_engine.py` (per-experiment scanners) | `compass/orchestrator/*` (EXP-2830 was; removed in PR #43) |
| Status | Production hot path | Now mostly dormant after PR #43, but still imported by `compass/dollar_notional_sizer.py`, smoke tests, and orchestrator pipeline |

### What breaks
Bug fixes applied to one don't propagate to the other. Charles must remember which connector is used by which experiment. New experiments may pick the wrong one — or worse, mix them.

### Recovery
Delete `compass/alpaca_connector.py` (PR #43's follow-up) once orchestrator path is fully retired. **Or** unify both behind a single interface. **Or** explicitly mark one as `# DEPRECATED — do not use` at module-top.

---

## F-11 (MEDIUM) — Iron Condor Wing Limit Price is Naive 50/50

`execution/execution_engine.py:557-558`:
```python
put_credit = credit / 2 if credit > 0 else None
call_credit = credit / 2 if credit > 0 else None
```

### What breaks
For an asymmetric IC (SPY 5450/5440 put wing collects $0.40 credit; SPY 5650/5660 call wing collects $0.10 credit), the actual wing limits should be 0.40 and 0.10, not 0.25 each. Submitting at 0.25 means:
- The put wing is more aggressively priced than intended (lower limit) → more likely to fill but at less than expected
- The call wing is set higher than market mid → unlikely to fill → orphan put wing exposed

### Safety net
None.

### Recovery
Pass per-wing credit explicitly through the opportunity dict (`opp["put_credit"]`, `opp["call_credit"]`) from the strategy layer.

---

## F-12 (MEDIUM) — Straddle Per-Leg Price Assumes Symmetric Legs

`execution/execution_engine.py:630`:
```python
per_leg_limit = round(abs(credit / 2), 2) if credit else None
```

Same as F-11: assumes call price ≈ put price. For event straddles where the underlying is far from ATM, the price asymmetry can be 2-3×.

---

## F-13 (MEDIUM) — Retry Policy Maxes at ~7 Seconds

`@_retry_with_backoff(max_retries=2, base_delay=1.0)`:
- Attempt 1
- Backoff: 1s + jitter ≈ 1-2s
- Attempt 2
- Backoff: 2s + jitter ≈ 2-3s
- Attempt 3 (last)
- Raise

Total: ~3 attempts over ≤7 seconds. An Alpaca outage longer than that exhausts retries entirely. The 09:25 ET window is only 4 minutes before market open at 09:30.

### Recovery
Bump `max_retries` to 4 (gives ~30s of cumulative retry runway, still well within the 5-min scheduler window).

---

## F-14 (MEDIUM) — Stale-Pending Recovery Window is 60 Minutes

`execution/execution_engine.py:241`: `PENDING_STALE_MINUTES = 60`

### What breaks
If the scheduler crashes mid-submission (DB row written as `pending_open`, but Alpaca call never made), the same opportunity is blocked from retry for 60 minutes. For 09:25 ET signals, that locks out the entire 09:25-10:25 entry window.

### Recovery
Drop to 10 minutes. The duplicate-check still prevents real duplicates because submission completes synchronously; if it didn't complete in 10 min, the previous attempt is genuinely dead.

---

## F-15 (MEDIUM) — Once Circuit Opens, Every Submission in Batch Dies

See F-09 + the placement of `_circuit_breaker.call` around every `submit_order` call. Once open, the breaker stays open for 60s and `CircuitOpenError` is non-retryable. A single Alpaca 5xx burst can take out the entire scanner's batch.

---

## F-16 (MEDIUM) — Client Order ID Timestamp Collision in `AlpacaConnector`

`compass/alpaca_connector.py:460`:
```python
order.client_order_id = f"{order.stream}-{order.strategy}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
```

1-second resolution. If two scanners on the same vesper APScheduler tick submit for the same `(stream, strategy)` within the same second, the IDs collide. Alpaca rejects the second with HTTP 409 (correctly classified `_is_non_retryable` upstream), but the upstream caller treats it the same as a real rejection — bad signal.

(Note: `strategy/alpaca_provider.py:402` uses `uuid4().hex[:8]` which is collision-resistant. Only the `AlpacaConnector` path is affected.)

---

## F-17 (LOW) — Drawdown CB Uses Closed-Trade P&L, Not Live Equity

`execution/execution_engine.py:502-540`. The CB sums `pnl` from `closed_profit` + `closed_loss` DB rows. It does NOT pull current equity from Alpaca. So intraday drawdown (mark-to-market on open positions) is invisible to the CB.

### What breaks
A 30% MTM drawdown on a giant short-vol position would NOT trip the 40% CB until the position closes and books the loss. By then it's too late.

### Recovery
Mix in `self.alpaca.get_account().equity` as the live equity number. Already available; just unused.

---

## F-18 (LOW) — OCC Root Padding Inconsistency

`compass/alpaca_connector.py:165`:
```python
return f"{ticker.upper()}{yy}{mm}{dd}{cp}{strike_int:08d}"   # SPY → SPY260524P00500000  (18 chars)
```

`strategy/alpaca_provider.py:222`:
```python
return f"{ticker.upper():<6}{date_str}{cp}{strike_int:08d}".replace(" ", "")   # SPY → SPY260524P00500000 (also 18 chars after .replace)
```

Both produce 18-char strings for 3-letter tickers. Alpaca's docs accept both 18-char and 21-char (space-padded) forms. **In practice the two implementations agree** — but the second one's `.replace(" ", "")` defeats the `:<6` padding entirely, suggesting unclear intent. If a future change drops the `.replace`, the symbols diverge silently.

---

## Code Path Map (for context)

```
Per-experiment scanner (09:25 ET on vesper):
  scheduler.jobs.job_run_experiment
    └─ subprocess: main.py scheduler --config <yaml>
         └─ execution.execution_engine.ExecutionEngine.submit_opportunity
              ├─ duplicate check (DB)             [F-14]
              ├─ drawdown CB                     [F-17]
              ├─ clock check (fail-open)         [F-06]
              ├─ DB write pending_open
              └─ strategy.alpaca_provider.AlpacaProvider
                   └─ submit_credit_spread / _submit_iron_condor / _submit_straddle
                        ├─ find_option_symbol (substitutes exp silently) [F-07]
                        ├─ _submit_mleg_order
                        │    ├─ LimitOrder if limit_price else MarketOrder [F-05]
                        │    └─ _circuit_breaker.call(submit_order)        [F-09, F-15]
                        ├─ _retry_with_backoff (max=2)                     [F-13]
                        └─ for IC: 2× separate MLEGs                       [F-03]
                          for straddle: 2× single-leg                       [F-04]

Dormant orchestrator path (post PR #43):
  compass.orchestrator.pipeline → compass.alpaca_connector.AlpacaConnector
    ├─ from_env() reads ALPACA_SECRET_KEY                                  [F-01]
    └─ submit_spread()
         ├─ try MLEG via MultilegOrderRequest
         └─ except ImportError: independent legs                            [F-02]
```

---

## What Actually Works (the 5%)

To balance the brutality:

- ✅ **DB-first pattern** (`upsert_trade` before Alpaca call) means a crash mid-submission leaves a `pending_open` row, recoverable on next scanner run after staleness window.
- ✅ **Duplicate check** correctly handles the common "scanner re-emits the same opportunity" case.
- ✅ **Drawdown CB exists** at all (F-17 caveat aside).
- ✅ **Non-retryable HTTP statuses are correctly enumerated** (400/401/403/404/409/422); 429 with Retry-After is properly handled.
- ✅ **Circuit breaker pattern** is the right primitive; thresholds need tuning.
- ✅ **`trade_legs` table populated** for orphan-leg reconciliation by `PositionMonitor`.
- ✅ **`alpaca_client_id` separated from `client_id`** (DB-stable hash vs Alpaca-unique submission ID) so failed orders can be retried without 409 conflicts.
- ✅ **Feature logger** records entry features for future ML training (non-fatal if it breaks).
- ✅ **Strategy/alpaca_provider uses proper MLEG with `OrderClass.MLEG`** for credit spreads — this is the right path; just needs to be the only path.

---

## Recommended Pre-Monday Actions (Ordered)

1. **🔴 F-01:** Patch `compass/alpaca_connector.py:67` — `ENV_SECRET = "ALPACA_API_SECRET"`. One-line fix. Even if the path is dormant, smoke tests will fail otherwise.

2. **🔴 F-05:** Add a `if limit_price is None: reject` guard in `submit_credit_spread`. This kills the market-order-on-options time bomb.

3. **🔴 F-06:** Change `is_open=None` to fail-closed. Add Telegram on clock-check failure.

4. **🟠 F-08:** Wire `send_telegram` into the cancel-failure branches in `_submit_iron_condor` and `_submit_straddle`. Operator MUST be paged if a half-leg orphans.

5. **🟠 F-09 + F-15:** Either disable the circuit breaker for `_submit_mleg_order` (keep it on account/positions) OR drop `CircuitOpenError` from `_NO_RETRY` so the retry decorator at least waits and retries.

6. **🟠 F-13:** Bump retry from `max_retries=2` to `max_retries=4`. Trivial, safe.

7. **🟡 F-14:** Drop `PENDING_STALE_MINUTES` from 60 to 10.

8. **🟡 F-07:** Add `allow_expiration_substitution=False` default in `find_option_symbol`; opt-in only.

9. **(Not blocking)** F-03 + F-04 (atomic 4-leg MLEG for ICs and atomic 2-leg MLEG for straddles): worthy refactor but bigger surface area than is wise pre-Monday. Land the alerting fix (F-08) first.

10. **(Verification)** **[LIVE-VERIFY]** the installed `alpaca-py` version on Railway pins `>= 0.43`. If it doesn't, F-02 becomes immediately reachable.

---

## Tests That Would Have Caught Each Bug

| Failure | Test that should exist |
|---|---|
| F-01 | `tests/test_alpaca_connector.py::test_from_env_uses_correct_secret_var` |
| F-02 | `tests/test_alpaca_connector.py::test_mleg_fallback_does_not_leave_naked_leg` |
| F-03 | `tests/test_execution_engine.py::test_ic_partial_then_cancel_failure_alerts_operator` |
| F-05 | `tests/test_alpaca_provider.py::test_none_limit_rejected_for_options` |
| F-06 | `tests/test_execution_engine.py::test_clock_check_failure_fails_closed` |
| F-07 | `tests/test_alpaca_provider.py::test_expiration_substitution_requires_opt_in` |
| F-09 | `tests/test_alpaca_provider.py::test_circuit_breaker_does_not_kill_unrelated_orders` |
| F-16 | `tests/test_alpaca_connector.py::test_default_client_order_id_is_collision_resistant` |

---

## Items I Could NOT Verify From Code Alone (require Charles)

- Actual `alpaca-py` version on Railway (F-02 / F-04 reachability)
- Whether `compass/orchestrator/pipeline.py` is invoked Monday morning by any active config
- Whether `_check_drawdown_cb`'s closed-only assumption matches Carlos's risk policy
- Whether `find_option_symbol`'s substitution behavior has been seen in past live runs (look for "expiration substituted" log lines in Railway logs over the last 2 weeks)
- The wing-credit split policy intended for ICs (F-11) — is the current 50/50 a known approximation?

---

**End of CC4 audit. The deployment will trade Monday IF F-01, F-05, F-06, F-08 are addressed and IF the orchestrator path is confirmed dormant. The rest are real-world risks that will eventually fire — but probably not in the next 48 hours.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
