# PR #49 — Final Verification (commit 548a70e)

**Auditor:** Maximus (CC5)
**Date:** 2026-05-24
**Commit under test:** `548a70ee53a42d91c5224a924f5b039591351d45` — "fix: add strategies/ to Dockerfile, harden smoke test, fix tests"
**Parent commit:** `c353c62178f63353081ee26d19c276936549e613`
**Base branch:** `main`

---

## Claim-by-claim verification

### ✅ Claim 1 — `strategies/` is NOW in `Dockerfile.scheduler`

**VERIFIED TRUE.** `Dockerfile.scheduler` at commit `548a70e` line 29:
```
COPY strategies/ ./strategies/
```
And the build-time smoke test now imports from it:
```
from strategies.base import MarketSnapshot, PositionAction
from strategies.credit_spread import CreditSpreadStrategy
from shared.strategy_factory import build_strategy
```
Diff vs parent shows `+COPY strategies/ ./strategies/` added between `strategy/` and `tracker/`. Without this, `from strategies.base import MarketSnapshot` at the top of `execution/position_monitor.py:39` would crash on first import inside the Railway scheduler container.

---

### ✅ Claim 2 — `execution/` WAS ALREADY there (at parent commit c353c62)

**VERIFIED TRUE** *(relative to commit 548a70e)*.

`Dockerfile.scheduler` at parent `c353c62` already contains:
```
COPY execution/ ./execution/
```
…and the smoke test already imports `from execution.execution_engine import ExecutionEngine`. So 548a70e correctly assumes `execution/` is present and adds only the missing `strategies/`.

⚠️ Important nuance: `execution/` is NOT on `main`. It was added by an earlier commit in PR #49 itself. On `main`, the COPY list jumps from `compass/` straight to `scheduler/`. So "already there" is true relative to **this PR**, not relative to main. The full Docker fix (execution/ + strategies/) only lands when PR #49 merges.

---

### ✅ Claim 3 — Lines 65-67 of `compass/alpaca_connector.py` are env-var NAME constants, not secrets

**VERIFIED TRUE.** At commit `548a70e`, lines 67-70 of `compass/alpaca_connector.py`:
```python
ENV_KEY = "ALPACA_API_KEY"
ENV_SECRET = "ALPACA_API_SECRET"
ENV_PAPER = "ALPACA_PAPER"
ENV_BASE_URL = "ALPACA_BASE_URL"
```
(Carlos quoted "65-67"; actual lines are 67-70 — likely a comment offset, but the substance is identical.)

These are **string literals that hold the NAMES of environment variables**, looked up later via `os.environ.get(ENV_KEY, "")` at `from_env()` (line ~235). They are not the secret values themselves. No credential is committed. Any static scanner that flags these is wrong.

---

### ✅ Claim 4 — Railway uses `Dockerfile.scheduler` CMD

**VERIFIED TRUE for the scheduler Railway service.**

`deploy/compass-scheduler/railway.toml`:
```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile.scheduler"

[deploy]
startCommand = "python -m scheduler.main"
healthcheckPath = "/health"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```
And `Dockerfile.scheduler` last line:
```
CMD ["python", "-m", "scheduler.main"]
```
The Railway compass-scheduler service builds from `Dockerfile.scheduler` and runs `python -m scheduler.main` (which is APScheduler-based `scheduler/main.py`, NOT `main.py scheduler`).

⚠️ Self-correction to my earlier `CC5_TRADE_READINESS.md`: I claimed "Railway is ONLY running dashboard UI" based on the repo-root `Procfile`. That was incomplete. Railway runs MULTIPLE services:
- Root `Procfile` → dashboard web service (`web: uvicorn web_dashboard.app:app`), plus declared `worker: python railway_worker.py` and `watchdog: python railway_watchdog.py`.
- `deploy/compass-scheduler/railway.toml` → separate "compass-scheduler" service using `Dockerfile.scheduler`.

The smoking-gun phrasing was overstated. The actual gap is that I cannot verify which Railway services are deployed/healthy from this environment — that needs Atlas / Railway CLI access.

---

### ✅ Claim 5 — Experiments use Railway env vars

**VERIFIED TRUE.** `scheduler/jobs.py`:

```python
def get_alpaca_client(exp_id: str):
    suffix = f"_{exp_id.upper().replace('-', '')}"
    api_key    = os.environ.get(f"ALPACA_API_KEY{suffix}", "")
    api_secret = os.environ.get(f"ALPACA_API_SECRET{suffix}", "")
    if not api_key or not api_secret:
        raise RuntimeError(f"Missing Alpaca keys for {exp_id} (looked for ALPACA_API_KEY{suffix})")
    ...
    return TradingClient(api_key=api_key, secret_key=api_secret, paper=paper)

def _get_experiment_env(exp_id: str) -> dict:
    suffix = exp_id.upper().replace("-", "")
    env = os.environ.copy()
    key    = os.environ.get(f"ALPACA_API_KEY_{suffix}", "")
    secret = os.environ.get(f"ALPACA_API_SECRET_{suffix}", "")
    if key:    env["ALPACA_API_KEY"] = key
    if secret: env["ALPACA_API_SECRET"] = secret
    env["ALPACA_BASE_URL"] = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    env["ALPACA_PAPER"]    = "true"
    polygon = os.environ.get("POLYGON_API_KEY", "")
    if polygon: env["POLYGON_API_KEY"] = polygon
    return env
```
Pattern is consistent and well-defined: each experiment reads `ALPACA_API_KEY_EXPXXX` / `ALPACA_API_SECRET_EXPXXX` from Railway env at runtime, then either instantiates a TradingClient directly or builds a per-experiment subprocess env. No generic fallback; raises explicitly if missing.

⚠️ Self-correction to my earlier `CC5_TRADE_READINESS.md`: I flagged "4 of 6 active experiments have no `.env.exp503/600/800/1220` files" as critical. That finding was correct for the **Mac Studio LaunchAgent path** (which sources `.env.expXXX` from disk), but NOT relevant for the **Railway scheduler path**, which gets keys from Railway env vars by experiment suffix. The two deployment surfaces have different credential models.

The remaining question (cannot verify from this environment): are the Railway env vars `ALPACA_API_KEY_EXP503` / `ALPACA_API_KEY_EXP600` / `ALPACA_API_KEY_EXP800` / `ALPACA_API_KEY_EXP1220` actually set on Railway? Atlas confirmed at session start that paper trading is blocked on Alpaca keys → very likely some of these are still missing on Railway too. Needs `railway variables --service compass-scheduler` to confirm.

---

## Overall verdict on commit 548a70e

✅ **APPROVE.** The hotfix is small, surgical, and correct:
1. Adds the missing `strategies/` COPY (single line; matches the existing pattern).
2. Hardens the build-time smoke test so this class of "module-missing-from-image" bug fails at `docker build` time instead of at 09:25 ET on a Monday.
3. Fixes two test fixtures to match the new "options require limit_price" invariant introduced earlier in the PR.

No regressions or scope creep. Merge.

---

## Corrections to earlier CC5 conclusions

This verification exposed that two earlier CC5 findings were partially wrong because I only inspected the dashboard surface and the Mac Studio surface, not the compass-scheduler Railway surface:

| Earlier CC5 claim | Correction |
|---|---|
| "Railway only runs dashboard UI — no scheduler" (CC5_TRADE_READINESS smoking gun) | Wrong. Railway also runs a `compass-scheduler` service via `Dockerfile.scheduler` configured by `deploy/compass-scheduler/railway.toml`. The repo-root Procfile is one of multiple Railway services. |
| "4 of 6 active experiments have no env files on disk → cannot trade" (CC5_TRADE_READINESS) | Partially wrong. Local `.env.expXXX` files are only required for the Mac Studio LaunchAgent path. The Railway scheduler path reads `ALPACA_API_KEY_EXPXXX` env vars directly. Whether those Railway vars are set is still unverified. |

The other CC5 critical findings stand unchanged:
- Risk: `PortfolioRiskMonitor` still not invoked anywhere in the live path (CC5_FINDINGS CRIT-1).
- Monitoring: `scripts/watchdog.py` still uses tmux on a LaunchAgent-only deployment (CC5_FAILURE_MODES CRIT-M1) — and that watchdog wouldn't apply to the Railway compass-scheduler service anyway, leaving that surface with no liveness watchdog at all.
- LaunchAgent inconsistencies (home-dir mismatch, missing EXP-800 plist) are still real for the Mac Studio fallback path.

---

## Next verifications worth doing before Monday

1. `railway variables --service compass-scheduler` — confirm `ALPACA_API_KEY_EXP400/401/503/600/800/1220` and matching `_SECRET` vars are all set.
2. `railway logs --service compass-scheduler -n 100` — confirm the service is actually running and the Dockerfile smoke test passed on last deploy.
3. `curl https://<compass-scheduler>.up.railway.app/health` — confirm healthcheck reachable.
4. Decide deployment model: Railway compass-scheduler OR Mac Studio LaunchAgents. **Do not run both** — they will fight over the same Alpaca account.
