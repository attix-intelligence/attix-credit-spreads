# CC1 — End-to-End Trade Execution Path Audit

**Audit Date:** 2026-05-24
**Auditor:** CC1 (Maximus)
**Target market open:** 2026-05-26 13:30 UTC (Monday)
**Branch audited:** `feature/experiment-manager-phase-6` (execution-path files identical to `main`; only `scheduler/jobs.py` differs)
**Scope:** signal → opportunity → order → fill → position → reconciliation

---

## 1. Execution path mapped (as deployed on Railway)

Railway service `compass-scheduler` runs `python -m scheduler.main` (per `deploy/compass-scheduler/railway.toml`). Long-running APScheduler + FastAPI `/health` on `$PORT`.

Per-experiment cron @ 09:25 ET Mon–Fri fires `job_run_experiment(exp_id, config, env_file)` (`scheduler/main.py:220-238`), which:

1. Builds env via `_get_experiment_env(exp_id)` (`scheduler/jobs.py:94`) — maps `ALPACA_API_KEY_EXP400`-style Railway vars → standard `ALPACA_API_KEY`/`ALPACA_API_SECRET` for the subprocess.
2. Spawns `python main.py scheduler --config <yaml> --env-file <file>` with **600 s timeout, `capture_output=True`** (`scheduler/jobs.py:592-600`).
3. `main.py` creates `AlpacaProvider` iff `alpaca.enabled=true` in YAML config (`main.py:147-164`), then `ExecutionEngine(alpaca_provider=...)` (`main.py:166-171`), wired into `AlertRouter(execution_engine=...)` (`main.py:174-181`).
4. `_generate_alerts` → `alert_router.route_opportunities(...)` (`main.py:585`) → `execution_engine.submit_opportunity(opp)`.
5. `ExecutionEngine.submit_opportunity` writes DB pending_open first, then calls one of:
   - bull-put / bear-call: `AlpacaProvider.submit_credit_spread` (MLEG, `strategy/alpaca_provider.py:343`)
   - iron condor: `ExecutionEngine._submit_iron_condor` → **two** sequential `submit_credit_spread` calls (`execution/execution_engine.py:542`)
   - straddle/strangle: `_submit_straddle` → two `submit_single_leg` calls (`execution_engine.py:605`)
6. `PositionMonitor._reconcile_pending_opens` (`execution/position_monitor.py:1363`) polls Alpaca for fills every 5 min during market hours.

**All 6 active experiment YAMLs verified to have `alpaca.enabled: true` with `${ALPACA_API_KEY}`/`${ALPACA_API_SECRET}` expansion.** ✓

---

## 2. Findings

### 🔴 CRITICAL

**C1 — Hardcoded Alpaca paper credentials for ALL 8 experiment accounts in `scripts/watchdog_external.py` (tracked in `main`).**

`scripts/watchdog_external.py:67-77` contains a dict `ALPACA_ACCOUNTS` with full plaintext key+secret pairs for every experiment account (EXP-400/401/503/600/800/1220/3309/3311). `git ls-tree main -- scripts/watchdog_external.py` confirms blob `4dddb1144c87...` is tracked.

- Blast radius: **all 8 paper accounts compromised** to anyone with repo read access — present or historical. Paper-only (no dollar loss) but trade history can be polluted by outside actors, breaking the live-vs-backtest comparison.
- Same goes for the `.env.*` files originally listed as H1 (now consolidated under this finding).

**Action required before Monday:**
1. Rotate all 8 paper API keys in Alpaca console — non-negotiable.
2. Delete the `ALPACA_ACCOUNTS` dict from `scripts/watchdog_external.py`; have it read from `shared/credentials.py` or env vars.
3. `git rm --cached scripts/watchdog_external.py .env.champion .env.exp036 .env.exp059 .env.exp154 .env.exp305 .env.exp400 .env.exp401 .env.sync` (then `git commit` after restoring the watchdog file with creds removed).
4. Update Railway env vars `ALPACA_API_KEY_EXP{400,401,503,600,800,1220,3309,3311}` (and secrets) to the new values.
5. If repo has any external visibility, `git filter-repo` history and force-push.

**This finding was missed in my initial pass** — agent ab6 surfaced it via grep. Severity upgraded from HIGH to CRITICAL because the watchdog file leaks all 8 accounts in one place (vs. 2 .env files leaking 2 accounts).

---

**C2 — Iron-condor leg-rollback uses single-attempt cancel; on failure the put wing stays open while DB records `failed_open`.**

`execution_engine.py:582-596`: if the call wing of an IC fails to submit AFTER the put wing succeeded, the put-wing cancel is a bare `self.alpaca.cancel_order(put_order_id)` with no retry. A transient 5xx/429 leaves a **naked short-put position** in Alpaca while the DB records `failed_open`. Position monitor's orphan detection (every 30 min, `shared/reconciler.py:1130-1143`) will eventually catch it, but in the meantime the position is unhedged, undefined-risk, and unbeknown to the risk gate.

EXP-400 (regime-adaptive IC) and EXP-800 (iron condor) both trade this path. Two days of SPY downside between expiration cycles is a real loss.

**Action:** Replace `execution_engine.py:590` with `self._cancel_with_retry(put_order_id, context=...)` — same pattern as the straddle leg-rollback path (line 679). 5-line fix.

(This was rated MEDIUM/M1 in my first pass; agents a73 and aef both flagged it CRITICAL. They are correct — the dollar/risk impact of a leftover naked short put justifies blocking deployment until fixed.)

---

### 🟠 HIGH

**H1 — `scheduler/main.py:227-228` schedules EXP-3309 / EXP-3311 scanners that have no per-experiment Alpaca keys configured.**

```python
_experiments = [
    ("EXP-400",  ...),  ("EXP-401",  ...),
    ("EXP-503",  ...),  ("EXP-600",  ...),
    ("EXP-800",  ...),  ("EXP-1220", ...),
    ("EXP-3309", "configs/paper_exp3309.yaml",  ".env.exp3309"),  # ← scheduled
    ("EXP-3311", "configs/paper_exp3311.yaml",  ".env.exp3311"),  # ← scheduled
]
```

But neither `.env.exp3309` nor `.env.exp3311` exists locally, and `pre_market_check` (line 126) only probes `EXP400/401/503/600/800/1220/3309/3311`. If `ALPACA_API_KEY_EXP3309` is unset in Railway:
- `_get_experiment_env` silently returns the parent env (no key written) — subprocess inherits whatever generic vars are present.
- `main.py` calls `os.environ.get('ALPACA_API_KEY', '')` → empty → `AlpacaProvider` init *fails inside `try/except`* (`main.py:163-164`) → falls into **alert-only mode** with no Telegram alert.
- Scanner exits rc=0; no failure visible to ops.

**Failure mode:** EXP-3309/3311 silently submit zero orders on Monday and we don't know until end-of-day P&L review.

**Action:**
- Either remove EXP-3309/3311 from `scheduler/main.py:220-228` (they're not in registry as `active`) — OR
- Add corresponding `ALPACA_API_KEY_EXP3309`/`ALPACA_API_SECRET_EXP3309` vars to Railway and verify with `pre_market_check`.

---

**H3 — Partial-fill detection adjusts size silently.**

`position_monitor.py:1718-1731`:
```python
if "filled" in order_status:
    filled_qty = int(float(filled_qty_str))
    if filled_qty != expected_contracts:
        # Adjusting contracts to filled qty.
        pos["contracts"] = filled_qty
```

A partial fill (`filled_qty < expected`) is logged at WARN but **no Telegram alert** is emitted. Risk: portfolio risk gate computed earlier (against `expected_contracts`) no longer matches the live position; the next scan may take a second order under the same risk budget, double-counting.

**Action:** Add Telegram alert when `filled_qty != expected_contracts` so ops can intervene the same day.

---

**H4 — `capture_output=True` on a 600 s subprocess can deadlock before timeout.**

`scheduler/jobs.py:593-600` runs each experiment's scanner with `subprocess.run(..., capture_output=True, timeout=600)`. `capture_output` buffers stdout/stderr in memory. If a scanner produces > ~64 KB of output (e.g. verbose DEBUG logs, traceback floods on a transient failure), the pipe fills and the **child blocks on write** before the 10-min timeout can fire — the timer is enforced by the parent, but the child is stuck and silent.

Symptom: experiment scanner appears "hung", no log lines emitted past the buffer-full point, watchdog won't detect because the *parent* is still waiting on the child.

**Action:** Either stream stdout/stderr to a logfile (`stdout=open(logfile, 'w')`) or use `subprocess.Popen` with non-blocking reads. Current setup is a known footgun.

---

### 🟡 MEDIUM

**M1 — Drawdown CB fails open on equity fetch failure.**

`execution_engine.py:160-166`:
```python
except Exception as e:
    logger.warning("drawdown CB — failed to fetch account equity: %s. Failing open (not blocking entry).", e)
    return None
```

Explicit design: if Alpaca `/v2/account` is 500ing but `/v2/orders` POST is still working, we lose the drawdown CB. Acceptable trade-off given the rarity of split availability, but **document this** so ops aren't surprised. Probably fine for Monday.

---

**M3 — `_check_drawdown_cb()` called twice per submission.**

`submit_opportunity` calls it at line 281 (returns early if tripped) and again at line 393 (post-DB-write). Second call duplicates the SQLite `load_scanner_state("peak_equity")` round-trip and the Alpaca `/v2/account` call. Equity could move between the two calls (unlikely matters but inconsistent). Not a blocker.

---

**M4 — `submit_credit_spread` accepts `expiration` that doesn't exist; relies on Alpaca substituting.**

`alpaca_provider.py:374-378` resolves the OCC symbol via `find_option_symbol(ticker, expiration, ...)`. If the requested expiration has no listed contract, the substitution shows up at `execution_engine.py:427-441` (`actual_expiration != requested → update DB`). This is logged at WARN — good. But there's **no validation that the substituted expiration is still within the strategy's intended DTE window**. E.g. a Friday entry asking for 0DTE could be substituted to next-Monday by `find_option_symbol` heuristics, and we'd hold a 3-day position thinking it's intraday.

**Action:** After `actual_expiration` update at line 427, sanity-check `(parse(actual_expiration) - today).days <= max_dte + N` and reject if out of band.

---

**M5 — Two separate Alpaca driver implementations (`AlpacaProvider` and `AlpacaConnector`).**

`strategy/alpaca_provider.py` (used by ExecutionEngine, the production path) and `compass/alpaca_connector.py` (used by `compass/orchestrator/order_router.py` and `scripts/run_exp1220.py`) are independent implementations with **different error handling, different retry semantics, different OCC symbol building, and different ENV var reads** (`AlpacaConnector.from_env` reads `ENV_KEY` constants which I haven't verified match `ALPACA_API_KEY`).

If EXP-1220 is genuinely using `scripts/run_exp1220.py` directly (not via `main.py scheduler`), then EXP-1220's order path is entirely different from EXP-400/401/503/600/800. Worth a follow-up audit; for Monday it just means EXP-1220 will not benefit from the ExecutionEngine's drawdown CB or stale-pending recovery.

**Action:** Confirm with Carlos which path EXP-1220 uses on Railway (vs Mac LaunchAgents at `deploy/com.pilotai.exp1220.plist`).

---

### 🟢 LOW

- **L1**: `client_order_id` for `submit_credit_spread` uses `uuid.uuid4()[:8]` when not provided (`alpaca_provider.py:402`). 32-bit collision space — fine because ExecutionEngine always supplies an `alpaca_client_id`, but the default would be a problem if anyone called it directly.
- **L2**: `_normalize_order_status` (`alpaca_provider.py:49`) handles SDK enum variance — good defensive code, but indicates the SDK contract has shifted before. Pin `alpaca-py` version in `requirements.txt`.
- **L3**: `_NON_RETRYABLE_HTTP_PREFIXES` includes `"401"` — meaning a transient auth blip won't be retried. Acceptable; usually 401 is config-not-network.

---

## 3. Answers to the brief's critical questions

| Question | Answer |
|---|---|
| **Will orders execute on Monday?** | YES, for EXP-400/401/503/600/800/1220 assuming Railway env vars `ALPACA_API_KEY_EXP{400,401,503,600,800,1220}` + secrets are set. EXP-3309/3311 are scheduled but likely will run in silent alert-only mode (H2). |
| **Order rejection (non-retryable 4xx)?** | `_is_non_retryable` (`alpaca_provider.py:64`) catches 400/401/403/404/409/422 — re-raised immediately, ExecutionEngine catches at line 466, marks `failed_open`, returns to caller. DB consistent. ✓ |
| **Partial fill?** | Detected at `position_monitor.py:1718` but **silent** — no Telegram alert (H3). Position size silently adjusted to filled qty. |
| **Reconciliation failure?** | `_reconcile_pending_opens` (`position_monitor.py:1363`) polls Alpaca; on Alpaca exception logs WARN and tries again next 5-min cycle. Stale pending_open > 60 min auto-marked `failed_open` (`execution_engine.py:241-266`). ✓ |
| **Mid-day API outage?** | `submit_credit_spread` has `@_retry_with_backoff(max_retries=2)` for 429 + 5xx + network. Three attempts total with exponential backoff + jitter. After exhaustion → error returned → `failed_open` in DB. ExecutionEngine never retries above this layer. **Drawdown CB fails open on account-fetch failure** (M2) — could submit orders during outage if account endpoint is down but order endpoint is up. |
| **Connection loss during fill?** | DB written `pending_open` BEFORE Alpaca call (`execution_engine.py:294-324`) — order_id captured if submit returns; if connection dies mid-submit, record stays `pending_open` and is recovered after 60 min (`PENDING_STALE_MINUTES`). No orphan trades. ✓ |

---

## 4. Verification I ran

```bash
git ls-tree main -- .env.exp400 .env.exp401 .env.exp503 .env.exp600 .env.exp800 .env.exp1220
# → only .env.exp400 and .env.exp401 are tracked
git show main:.env.exp400 | head
# → confirms real paper API key + secret embedded in tracked file
grep -A5 "^alpaca:" configs/paper_*.yaml
# → all 6 active configs have enabled: true with ${ALPACA_API_KEY} expansion
python3 -c "from experiments.manager import get_manager; print([e['id'] for e in get_manager().live()])"
# → confirms 6 active experiments, no EXP-3309/3311
```

---

## 5. Cross-reference: parallel agent findings

Three Explore agents independently audited execution_engine, position_monitor/reconciler, and credentials. Key cross-validation:

**Agreed CRITICAL:**
- **Hardcoded keys in `scripts/watchdog_external.py`** (agent ab6) — verified, blob in main. **Was missed in my first pass.** Promoted to C1.
- **IC leg-rollback fragility** (agents a73 and aef) — verified. Promoted from M1 to C2.

**Agent claims I reviewed and DISAGREED with:**
- *"`CircuitOpenError` in drawdown CB is uncaught → process crash"* (agent a73 CRITICAL-1) — **False**. `execution_engine.py:158-166` wraps `get_account()` in `try/except Exception` which catches `CircuitOpenError`. The branch returns `None` (fails open). Not a blocker.
- *"Non-atomic stale-pending recovery → concurrent scanners double-submit"* (agent a73 CRITICAL-2) — **Mitigated**. `main.py:1018-1032` acquires a per-experiment `fcntl.flock` before scanning; same-experiment concurrent runs cannot occur. The race only exists if a third party invokes `submit_opportunity` outside the scanner lock, which is not done in production.
- *"5-minute phantom detection window"* (agent aef HIGH) — **Acceptable**. Without webhooks, polling at 60s/5-min cadence is the unavoidable contract; this is a known limitation, not a regression.

**Agent claims I integrated:**
- Partial-fill leg-cancellation gap on multi-leg spreads (aef CRITICAL-2): now part of C2.
- `needs_investigation` state has no timeout (aef HIGH-7a): worth tracking but not a Monday blocker.
- Pre-submission validation missing (a73 HIGH): noted as M4 / future work.

---

## 6. Verification I ran

```bash
git ls-tree main -- scripts/watchdog_external.py .env.exp400 .env.exp401 .env.champion .env.exp036 .env.exp059 .env.exp154 .env.exp305 .env.sync
# → all 9 tracked (including the watchdog with the 8-key dict)
git show main:scripts/watchdog_external.py | sed -n '67,77p'
# → confirms ALPACA_ACCOUNTS dict with PK*/secret pairs for all 8 experiments
grep -A5 "^alpaca:" configs/paper_*.yaml
# → all 6 active configs have enabled: true with ${ALPACA_API_KEY} expansion
python3 -c "import json; r=json.load(open('experiments/registry.json')); print([k for k,v in r['experiments'].items() if v.get('status')=='active'])"
# → ['EXP-400','EXP-401','EXP-503','EXP-600','EXP-800','EXP-1220']  (no 3309/3311)
```

---

## 7. Verdict

### **NO-GO until C1 + C2 are fixed.**

The execution path is wired correctly and orders will fire — but two CRITICAL issues must be resolved before Monday 13:30 UTC:

**Hard blockers (must fix Sunday):**

1. **C1** — rotate all 8 Alpaca paper keys, delete the `ALPACA_ACCOUNTS` dict from `scripts/watchdog_external.py`, untrack the 8 `.env.*` files, update Railway env vars. **Without this, anyone with repo access can pollute every experiment's paper account between now and the open.**
2. **C2** — change IC put-wing cancel to `_cancel_with_retry`. **Without this, a single transient Alpaca cancel failure can leave a naked short put on EXP-400/EXP-800.**

**Should-fix this week (not blockers, but real risks):**

3. **H1** — decide on EXP-3309/EXP-3311: remove from `scheduler/main.py:227-228` or wire up Railway env vars + `.env.expNNNN` files. Without action they appear to run successfully but submit zero orders.
4. **H2** — Telegram alert on partial fills (currently silent size-down).
5. **H3** — change `subprocess.run(capture_output=True)` to stream to logfile to avoid pipe-buffer deadlock at 600s.

**Open questions for Carlos:**

- M3 — is EXP-1220 trading via `main.py scheduler` (ExecutionEngine path) or `scripts/run_exp1220.py` (AlpacaConnector path)? Two different code paths reach Alpaca and they don't share safety features.
- Did Railway env vars survive the EXP-2830 cleanup on 2026-05-23? Recommend running `job_pre_market_check` manually before Monday to confirm all `ALPACA_API_KEY_EXP*` vars are present and authenticate.

---

**End of CC1 findings.**
