# CC5 — Risk Management & Position Limits Audit

**Date:** 2026-05-24
**Auditor:** Maximus (cc5 brief)
**Scope:** Portfolio-level risk, per-stream limits, margin requirements, kill switches
**Verdict:** 🔴 **NO-GO for unsupervised live trading.** Paper-mode-only is acceptable because Alpaca paper enforces its own boundaries — but the architecture has **no enforced central risk control**. Most documented safeguards are either disconnected dead code or "log-only" alerts. See CRITICAL #1, #2, #5 below.

---

## TL;DR

| Question (from brief) | Answer |
|---|---|
| Where is `pilots/risk_manager.py`? | **Does not exist.** `pilots/` directory doesn't exist either. |
| Is 12% vol target enforced? | **No.** Vol-targeting (target_vol=0.18, not 0.12) exists only in backtest experiments. Production uses a 20% gross-dollar-at-risk cap, not vol targeting. |
| Are per-stream position limits enforced? | **Partially.** `compass/orchestrator/canonical_params.yaml` defines per-sleeve caps and the orchestrator's `position_sizer` enforces them — but the legacy scanner path (`scripts/run_exp1220.py`) uses a different config and can drift. |
| Margin buffer? | **No.** Sizer caps dollar-at-risk but never queries Alpaca for available margin before submitting. |
| Emergency stop mechanism? | **Per-experiment only.** To halt all 6 active experiments you must edit `sentinel_state.json` six times. No single kill-switch. |

---

## Findings

### 🚨 CRITICAL

#### CRIT-1 — `PortfolioRiskMonitor` is wired to nothing in live trading
**Files:** `shared/portfolio_risk.py`, all consumers
**Evidence:** `grep -rn "PortfolioRiskMonitor\|get_monitor\|from shared.portfolio_risk" --include='*.py'` returns **zero** live call sites. Only references are:
- The module itself defining the class (`shared/portfolio_risk.py`)
- Tests (`tests/test_portfolio_risk.py`, `tests/test_robustness_edge_cases.py`)

**Impact:** The 4-level drawdown circuit breaker documented at the top of `shared/portfolio_risk.py` (NORMAL → YELLOW @ −8% → RED @ −10% → HARD_STOP @ −12%) **never runs**. Nothing calls `monitor.check()`. Nothing calls `monitor.allow_entry()` before placing an order. The combined-account HWM database is initialised but no production code updates it.

PR #44 (just merged today) made the monitor's account-discovery robust (live() instead of active()), but that fix is on a module that no production code path imports.

**Fix:** wire `get_monitor().allow_entry(exp_id)` into:
- `compass/orchestrator/entry_gate.py` as a top-level gate (returns BLOCK on RED/HARD_STOP), or
- `compass/orchestrator/order_router.py` as a pre-submit check, or
- `sentinel/guards.py:pre_scan_check` so scanners abort when drawdown is over the threshold.

Until then the documented portfolio-level safety net does not exist.

---

#### CRIT-2 — `execute_hard_stop()` is documented as "Paper mode — LOG ONLY"
**File:** `shared/portfolio_risk.py:229-261`
**Evidence:**
```python
def execute_hard_stop(self) -> None:
    """Handle HARD_STOP event.

    Paper mode: LOG ONLY — does not submit real close orders.
    Sends a Telegram alert.
    """
```
Even if CRIT-1 were fixed, hitting the −12% threshold only writes a log line and a Telegram message ("Would flatten N positions"). It does NOT close any positions. Combined with CRIT-1, the documented "hard stop" is a notification, not an action.

**Impact:** A −12% drawdown can deepen to −50% with the system happily continuing to take new entries (because YELLOW/RED gates aren't wired either — see CRIT-1).

**Fix:** implement actual position-closing in `execute_hard_stop()` (e.g., `client.close_all_positions()` per account), and add an integration test. Or keep paper-only and clearly label this an alerting subsystem, not a circuit breaker.

---

#### CRIT-3 — Three conflicting "max portfolio risk" thresholds across modules
**Evidence (grep):**
- `strategies/base.py:190`: `max_portfolio_risk_pct: float = 0.40` (40%)
- `compass/orchestrator/canonical_params.yaml:portfolio.port_risk_cap_pct: 0.20` (20%)
- `sentinel/gates_account.py:89`: `DEFAULT_MAX_PORTFOLIO_RISK_PCT = 0.50` (50%)
- `shared/portfolio_risk.py`: HARD_STOP at drawdown ≤ −12%
- `scheduler/jobs.py:297`: `DD_HALT_PCT = 13.0` (13%) — used by `job_circuit_breaker_check`

These are five different "tolerable risk" numbers in five different files. No comment explains which is canonical. Each is enforced (or not) by a different layer that may or may not run.

**Impact:** A reader cannot determine what the actual portfolio risk ceiling is. A reviewer cannot confirm the live ceiling matches the backtest (the brief's explicit success criterion).

**Fix:** pick one canonical value (the brief says 12% vol target / 12% DD ceiling — that matches `_HARD_STOP_THRESHOLD = -12.0` if we treat it as drawdown rather than gross notional). Reference it from one constants module. Delete or align the others.

---

#### CRIT-4 — 12% portfolio vol target is NOT enforced in production
**Evidence (grep):**
- The phrase "12% vol target" appears only in audit/research docs, not in any module under `compass/`, `sentinel/`, `scheduler/`, `execution/`, `shared/`, `alerts/`, `strategies/`.
- Real vol-targeting code (`compass/exp3150_post2020_retest.py`, `compass/exp3230_rolling_walkforward.py`) uses `target_vol = 0.18` and runs in **backtest only**.
- Live sizing in `compass/orchestrator/position_sizer.py` uses gross-dollar-at-risk caps (per-sleeve `risk_per_trade_pct` × `equity` × `effective_confidence`, then `port_risk_cap_pct` over the batch). No vol estimate, no covariance, no Ledoit–Wolf, no risk-parity weights — none of the backtest's vol-targeting machinery is in the live path.

**Impact:** The live portfolio's realised vol is whatever the sleeve weights and confidence-scaling produce — it is **not** held to 12% (or 18%, or any explicit number). If realised vol is 25% and equity is $500K, every drawdown realisation will be larger than backtest assumes.

**Fix:** either (a) port the vol-targeting block from `exp3230_rolling_walkforward.py` (Ledoit–Wolf cov + risk-parity weights + `target_vol / train_vol` scaling) into a live `position_sizer` post-step, or (b) update all backtest comparisons and the LP deck to state that production uses a **20% gross-dollar-at-risk cap**, not vol targeting. Both are defensible, but the docs must match.

---

#### CRIT-5 — No central kill switch
**Evidence:** halt enforcement lives in `sentinel/guards.py:pre_scan_check(exp_id)` which `sys.exit(1)`s if the experiment's status in `sentinel_state.json` is `"halted"`. To halt ALL trading you must:
1. Edit `sentinel_state.json`, change `status` to `"halted"` for **every** of the 6 active experiments (EXP-400, 401, 503, 600, 800, 1220) individually.
2. Wait until each scanner's next invocation. There is no signal to running scanners; if a scanner is already inside its scan loop, the halt does not stop it.
3. Watch for `scripts/run_sentinel.py --approve` to be the only documented un-halt path.

`scheduler/jobs.py:job_circuit_breaker_check` writes alerts to `circuit_breaker.json` and Telegram — but **no production code reads `circuit_breaker.json`**. `grep -rn "circuit_breaker.json" --include='*.py'` shows only the writer (`jobs.py`) and the dashboard read-only API (`scheduler/api.py`).

**Impact:** In a panic (Carlos sees something wrong) there is no `kill-all` button. Six file edits, then wait for scanner cycles. During an event like an Alpaca outage or runaway order loop this is too slow.

**Fix:** add a single `data/trading_disabled.flag` (or DB row) that:
- `pre_scan_check` reads and `sys.exit(1)`s on
- `order_router.submit_order` reads and refuses to submit on
- `job_circuit_breaker_check` can write to when DD or VIX exceeds thresholds
- has a CLI (`scripts/kill_all.py` / `scripts/resume_all.py`)

---

### 🔴 HIGH

#### HIGH-1 — VIX circuit breaker is alert-only
**File:** `scheduler/jobs.py:293-343`
The `job_circuit_breaker_check` job runs every 30 min during market hours. It computes thresholds:
- `VIX_CRISIS_BLOCK = 35.0` ("block new entries")
- `VIX_EMERGENCY_EXIT = 45.0` ("EXIT ALL POSITIONS")
- `DD_HALT_PCT = 13.0` ("HALT")

But the function only appends strings to `alerts[]`, writes them to `circuit_breaker.json`, and sends Telegram. No scanner, no order router, and no entry gate consults that file. **The "block new entries" alert blocks nothing.**

**Fix:** either (a) flip the kill switch from HIGH-5 on threshold breach, or (b) wire `circuit_breaker.json` into `pre_scan_check` and `order_router`.

#### HIGH-2 — No margin-availability check before order submit
**File:** `compass/orchestrator/position_sizer.py`, `compass/orchestrator/order_router.py`, `compass/alpaca_connector.py`
The sizer enforces dollar-at-risk caps but never asks Alpaca "do I have enough buying power / option_buying_power to place this spread?" before `submit_order()`. On a margin-constrained account, a sized order will reject at the broker — and there's no retry-with-smaller-size logic.

**Fix:** before submit, fetch `client.get_account()`; require `options_buying_power >= total_max_loss`. Skip the order with a logged reason if not.

#### HIGH-3 — Legacy scanner path bypasses canonical_params.yaml
**File:** `scripts/run_exp1220.py:691-693`
```python
max_portfolio_risk = config["sizing"]["max_portfolio_risk_pct"]
if total_risk_pct > max_portfolio_risk:
    log.info(f"SKIP: Total risk {total_risk_pct:.1f}% > max {max_portfolio_risk}%")
```
`run_exp1220.py` (and presumably the other per-experiment `run_*.py` scripts called by tmux session scanners) reads its own `config` dict — not `compass/orchestrator/canonical_params.yaml`. So the per-stream `max_contracts`, `risk_per_trade_pct`, and portfolio cap can drift between the orchestrator and the legacy scanners.

**Impact:** the brief's success criterion "experiments match their respective backtesting environment EXACTLY" is at risk because two parallel sources of truth exist. Whichever scanner actually runs on Monday will use its own config.

**Fix:** confirm which path is the production one (orchestrator pipeline vs. per-exp runner scripts). If both run, route both through `canonical_params.yaml`.

#### HIGH-4 — `DD_HALT_PCT = 13.0` in scheduler vs `_HARD_STOP_THRESHOLD = -12.0` in portfolio_risk
Off-by-one configuration. The scheduler alerts at 13% drawdown; the portfolio_risk module's hard-stop is 12%. Even if both were wired, they'd fire in the wrong order.

**Fix:** align values, ideally pull from one constants module.

---

### ⚠️ MEDIUM

#### MED-1 — `sentinel/gates_account.py` portfolio gate is `DEFAULT_MAX_PORTFOLIO_RISK_PCT = 0.50` (50%)
This is a sentinel monitoring gate, not a sizing gate, but 50% of equity at risk is generous for a strategy with a 12% target DD.

#### MED-2 — HARD_STOP message reports "0 accounts" if no env files
`shared/portfolio_risk.py:240-246` computes `accounts = {... if e.get('env_file')}`. If no env files are present for active experiments, the hard-stop alert reports "would flatten N positions across 0 accounts". Cosmetic but misleading.

#### MED-3 — `_count_open_positions` filters by OCC symbol length > 6
`shared/portfolio_risk.py:413` uses `len(p.symbol) > 6` to identify option positions. OCC symbols are typically 21 chars; equity symbols are 1–5. The threshold is too loose — any symbol ≥7 chars (e.g., a future symbol) is mis-counted. Low likelihood on Alpaca paper, but the test isn't structural.

#### MED-4 — Singleton race on `PortfolioRiskMonitor`
`shared/portfolio_risk.py:432-439` double-checked-locking around `_monitor_instance`. The class itself does have an internal `threading.Lock` on `check()`, but with concurrent first-callers a second instance could open another sqlite connection to the same DB file. WAL mode + busy_timeout mitigate it but the race is real. Low impact in practice.

---

### 💡 LOW / OBSERVATIONS

- **OBS-1 — `pilots/` directory does not exist.** The audit brief references `pilots/risk_manager.py`, `pilots/alpaca_driver.py`, `pilots/order_manager.py`, `pilots/reconciler.py`, `pilots/data_manager.py`, `pilots/ironvault_client.py`. None of these exist. The actual structure: `execution/`, `compass/`, `scheduler/`, `sentinel/`, `shared/`. The brief may be stale relative to the May 2026 codebase.
- **OBS-2 — Per-sleeve `max_contracts` ranges 1–5** in `canonical_params.yaml`. With current $100K starting capital and per-trade `risk_per_trade_pct` 2–3%, this gives a max single-trade dollar loss of ~$2,000–$3,000 even before the 5%-of-OI liquidity cap. Reasonable.
- **OBS-3 — `port_risk_cap_pct = 0.20` (20% gross at risk)** is roughly 1.5–2× a 12% portfolio vol target, which is consistent with dollar-at-risk being a fatter cap than realised-vol targeting. Defensible if documented.

---

## Verification commands

```bash
# CRIT-1: prove PortfolioRiskMonitor is unwired
grep -rn "PortfolioRiskMonitor\|get_monitor\|allow_entry" --include='*.py' \
  | grep -v __pycache__ | grep -v /archive/ | grep -v /tests/

# CRIT-3: list all max-portfolio-risk constants
grep -rn "max_portfolio_risk\|port_risk_cap\|MAX_PORTFOLIO_RISK\|DD_HALT_PCT\|HARD_STOP_THRESHOLD" \
  --include='*.py' --include='*.yaml' | grep -v __pycache__ | grep -v /archive/

# CRIT-4: prove no production vol-target enforcement
grep -rn "target_vol\|vol_target" --include='*.py' compass/orchestrator/ shared/ scheduler/ execution/ sentinel/ strategies/

# CRIT-5: prove no kill-switch consumer
grep -rn "trading_disabled\|kill_switch\|TRADING_DISABLED" --include='*.py'
grep -rn "circuit_breaker.json" --include='*.py'

# HIGH-2: prove no margin check before submit
grep -n "buying_power\|options_buying_power\|margin" compass/orchestrator/order_router.py compass/alpaca_connector.py
```

---

## What's good

- **`compass/orchestrator/position_sizer.py` IS solid** — per-sleeve risk-per-trade, max_contracts cap, 5% liquidity cap, portfolio gross cap, correlation haircut, dollar-at-risk accounting across the batch. Documented step-by-step. Pure function, testable.
- **`canonical_params.yaml` is a single source of truth** for per-sleeve parameters — if everything routed through it, drift between backtest and live would be impossible.
- **`sentinel/guards.py:pre_scan_check`** is the right pattern for halt enforcement: fail-closed (`sys.exit(1)`), runs at scanner startup, sub-second.
- **PR #44 (today)** correctly switched `PortfolioRiskMonitor` from `.active()` to `.live()` so paused experiments are still monitored. That fix was right — it just doesn't matter yet because the monitor itself is unconnected (CRIT-1).

---

## GO/NO-GO

🔴 **NO-GO for unsupervised live trading on Monday.**

🟡 **CONDITIONAL GO for supervised paper trading** (Alpaca paper has its own boundaries; worst case is alerts and a paper-account loss).

### Minimum required before any GO
1. Wire `PortfolioRiskMonitor.allow_entry()` into `entry_gate` OR `order_router` (CRIT-1).
2. Replace `execute_hard_stop` "LOG ONLY" with actual `close_all_positions()` per account, or rename it `alert_hard_stop` and stop calling it a circuit breaker (CRIT-2).
3. Add a single kill-switch file/flag honored by both `pre_scan_check` and `order_router` (CRIT-5).
4. Pick one canonical portfolio-risk threshold and delete the other four (CRIT-3).
5. Either implement live vol-targeting or update docs to say the production limit is the 20% gross-dollar-at-risk cap (CRIT-4).

Items 1–3 are blocking. Items 4–5 are documentation/architecture but should land in the same sprint to prevent recurrence.

---

**Files audited:** `shared/portfolio_risk.py`, `compass/orchestrator/position_sizer.py`, `compass/orchestrator/entry_gate.py`, `compass/orchestrator/order_router.py`, `compass/orchestrator/canonical_params.yaml`, `compass/alpaca_connector.py`, `compass/portfolio_risk_manager.py`, `sentinel/guards.py`, `sentinel/gates_account.py`, `sentinel/state.py`, `sentinel/runtime.py`, `scheduler/jobs.py`, `scheduler/api.py`, `scripts/run_exp1220.py`, `strategies/base.py`, `tests/test_portfolio_risk.py`.

**Maximus — CC5 audit complete 2026-05-24.**
