# CC4 AUDIT FINDINGS — Railway Deployment & Infrastructure

**Auditor:** CC4 (skeptical mode)
**Date:** 2026-05-24
**Target Cutoff:** Monday 2026-05-26 09:25 ET (vesper signal slot) / 13:30 UTC market open
**Method:** Static code audit. Live Railway API access NOT available in this sandbox (no `RAILWAY_API_TOKEN`, no `gh` CLI) — items requiring live verification are flagged **[LIVE-VERIFY]** below for Charles to execute.

---

## TL;DR — VERDICT

**🟡 PARTIALLY READY** — the deployment design is sound and recently hardened (PR #42, PR #43), but **two production-grade issues and one critical configuration ambiguity must be resolved before Monday**:

| # | Severity | Issue | Blocks Monday? |
|---|---|---|---|
| 1 | 🔴 **CRITICAL** | **Dual scheduling conflict** — Mac Studio LaunchAgents AND Railway APScheduler both target the same experiments (EXP-400/401/503/600/1220). One MUST be disabled or you risk double-firing trades. | **YES** |
| 2 | 🔴 **CRITICAL** | **Web service has no healthcheck path** (`railway.json` at repo root). Railway can't detect crashes → won't restart → undetected downtime. | YES (silent) |
| 3 | 🟠 HIGH | **No persistent volume confirmed in Dockerfile.scheduler.** Scheduler writes `/data/logs`, `/data/signals`, `/data/health.json` — if not mounted on a Railway volume, every restart wipes state. | YES |
| 4 | 🟠 HIGH | **No watchdog / dead-man's switch** outside the scheduler itself. If `scheduler.main` deadlocks but uvicorn still serves `/health`, nothing detects it. Heartbeat-on-Telegram fires every 4h but no one receives it on weekends. | Partial |
| 5 | 🟡 MEDIUM | **`get-logs.sh` via Railway GraphQL is the ONLY log access path** — no Railway CLI, no log forwarding. On Monday debugging requires `RAILWAY_API_TOKEN` in your shell. | If you need to debug, yes |
| 6 | 🟡 MEDIUM | Restart policy = `ON_FAILURE` with `maxRetries=3`. After 3 crashes Railway gives up; no escalation. | Edge case |

If you do nothing else before Monday: **resolve #1 and #2**.

---

## 1. Railway Config Inventory

### Files found

| Path | Purpose | Status |
|---|---|---|
| `railway.json` (root) | Web service (likely the `pilotai-credit-spreads-production` URL) | ⚠ Missing `healthcheckPath` |
| `Procfile` (root) | `web: uvicorn web_dashboard.app:app --host 0.0.0.0 --port $PORT` | OK, but used by which service? |
| `Dockerfile.old` | Legacy combined web+scheduler image (Next.js + Python). Includes `HEALTHCHECK` on `/api/health`. | Marked `.old` — presumably retired |
| `Dockerfile.scheduler` | Current scheduler image. `CMD python -m scheduler.main`. **No `HEALTHCHECK` directive.** | OK content but no in-image healthcheck |
| `deploy/compass-scheduler/railway.toml` | **The scheduler service's** real Railway config (built from `Dockerfile.scheduler`). `healthcheckPath = "/health"`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`. | ✅ Correct |
| `deploy/macro-api/` | Separate macro-api Railway service (out of scope here) | — |

**There is NO `railway.toml` at repo root.** Railway falls back to `railway.json` for the root service, which means:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "deploy": {
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

No `healthcheckPath`. No `startCommand` override. Railway will use Procfile (`web: uvicorn web_dashboard.app:app …`). **Crash detection depends entirely on the process exiting** — a deadlocked uvicorn that still binds the port will look healthy to Railway forever.

### Inferred Railway service map

There appear to be **3 services** (based on docs + configs):

| Service | Source | Process | Healthcheck | Volume |
|---|---|---|---|---|
| `web` (the dashboard) | repo root + Procfile | `uvicorn web_dashboard.app:app` | ❌ NONE | Reads `/app/data/pilotai.db` per RAILWAY_MIGRATION.md |
| `vesper` / `compass-scheduler` | `Dockerfile.scheduler` + `deploy/compass-scheduler/railway.toml` | `python -m scheduler.main` | ✅ `/health` | Writes `/data/...` — **volume mount unverified** |
| `sentinel-watchdog` | Inferred from PR #43 callout; source unknown to this audit | — | — | — |

**[LIVE-VERIFY]** Run `bash skills/railway/scripts/list-services.sh` (needs `RAILWAY_API_TOKEN`) to confirm the actual service list, their Docker source, and volume mounts.

---

## 2. CRITICAL #1 — Dual Scheduling Conflict (Mac Studio vs Railway)

This is the single biggest Monday-morning risk.

### Evidence on **Mac Studio** (`/Users/charles/pilotai/...`):

LaunchAgent plists in `deploy/`:
- `com.pilotai.exp1220.plist` — runs `scripts/run_exp1220.py` at **09:35 ET Mon-Fri**
- `com.pilotai.exp400.plist`
- `com.pilotai.exp401.plist`
- `com.pilotai.exp503.plist`
- `com.pilotai.exp600.plist`

Each LaunchAgent runs from `/Users/charles/pilotai/`, sources `.env`, executes the experiment scanner directly.

Additionally, `output/exp305_preflight_audit.md:544` documents a recommended crontab line:
```
*/30 9-15 * * 1-5 cd /Users/charlesbot/projects/pilotai-credit-spreads && bash scripts/scan-cron.sh
```

### Evidence on **Railway** (`scheduler/main.py:220-238`):

The vesper APScheduler registers **8 per-experiment scanners at 09:25 ET Mon-Fri**:

```python
_experiments = [
    ("EXP-400",  "configs/paper_champion.yaml",  ".env.exp400"),
    ("EXP-401",  "configs/paper_exp401.yaml",    ".env.exp401"),
    ("EXP-503",  "configs/paper_exp503.yaml",    None),
    ("EXP-600",  "configs/paper_exp600.yaml",    None),
    ("EXP-800",  "configs/paper_exp800.yaml",    None),
    ("EXP-1220", "configs/paper_exp1220.yaml",   None),
    ("EXP-3309", "configs/paper_exp3309.yaml",   ".env.exp3309"),
    ("EXP-3311", "configs/paper_exp3311.yaml",   ".env.exp3311"),
]
```

Each is launched via `job_run_experiment` as a `subprocess.run(...)` on `main.py scheduler --config <yaml>`.

### The conflict

For EXP-400/401/503/600/1220 there are scanners scheduled **on both machines**:
- Mac Studio LaunchAgents at 09:35 ET (or as configured)
- Railway vesper APScheduler at 09:25 ET

**Symptoms if both fire:**
- Double order submission to Alpaca (same paper account if keys match) → 2× position size, or 1× position + duplicate-order rejections
- Two competing entries to per-experiment SQLite/journal files if both write to shared paths
- Telegram spam from both sources

**[LIVE-VERIFY] Charles must answer the following before Monday:**
1. Which Mac Studio LaunchAgents are currently `Loaded` (`launchctl list | grep pilotai` on the Mac)?
2. Is Railway `vesper` the **source of truth** going forward, or is the Mac?
3. If Railway: `launchctl unload ~/Library/LaunchAgents/com.pilotai.exp*.plist` for each active plist BEFORE Monday market open.
4. If Mac Studio: disable the per-experiment jobs in `scheduler/main.py:218-238` and redeploy vesper.

**This is non-negotiable. Pick one. Document the choice.**

---

## 3. CRITICAL #2 — Web Service Has No Healthcheck

`railway.json` (the root config used by the web service):

```json
{ "deploy": { "restartPolicyType": "ON_FAILURE", "restartPolicyMaxRetries": 3 } }
```

No `healthcheckPath`. No `healthcheckTimeout`.

**What happens:**
- If `uvicorn web_dashboard.app:app` exits with nonzero status → Railway restarts (good, up to 3x).
- If it deadlocks but the TCP socket stays open → Railway shows ✅ "Active" forever. You'd only discover it when someone tries to load the dashboard.
- After 3 hard crashes in quick succession → Railway gives up. No auto-recovery, no Telegram alert, no email.

**Fix (add to `railway.json`):**
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "deploy": {
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "healthcheckPath": "/api/health",
    "healthcheckTimeout": 30
  }
}
```

**[LIVE-VERIFY]** Confirm `web_dashboard.app:app` actually serves `/api/health` (Dockerfile.old's `HEALTHCHECK` referenced `/api/health` — likely real).

Also: scheduler service has `maxRetries=3`. Consider bumping to 10 for the scheduler too; a 3-retry cap is too tight for a critical service.

---

## 4. HIGH #3 — Persistent Volume Not Confirmed for Scheduler

`Dockerfile.scheduler:33`:
```dockerfile
RUN mkdir -p /data/logs /data/signals
```

`scheduler/jobs.py:38-43`:
```python
DATA_DIR    = Path(os.environ.get("COMPASS_DATA_DIR", "/data"))
SIGNALS_DIR = Path(os.environ.get("COMPASS_SIGNALS_DIR", "/data/signals"))
LOGS_DIR    = Path(os.environ.get("COMPASS_LOGS_DIR", "/data/logs"))
HEALTH_JSON = Path(os.environ.get("HEALTH_JSON_PATH", "/data/health.json"))
```

`/data` is created **inside the image** but is NOT a `VOLUME` directive (intentionally — RAILWAY_MIGRATION.md notes that conflicts with Railway's volume manager).

**The scheduler service writes to `/data` continuously:**
- `health.json` (every 5 min during market hours)
- `signals/<date>.json` (daily)
- `logs/paper_signals_audit.jsonl`
- `logs/failed_alerts.jsonl` (Telegram fallback — alerts get permanently lost without the volume)
- `circuit_breaker.json`, `event_gate.json`

**[LIVE-VERIFY]** In Railway dashboard:
- Confirm there's a volume mounted to `/data` on the **vesper / compass-scheduler service**.
- If not, every container restart loses: failed Telegram alerts, signal history, audit logs, drawdown tracking continuity.

If no volume exists, Charles should mount one before Monday — even 1GB is enough.

---

## 5. HIGH #4 — No Independent Watchdog

The scheduler is its own watchdog:
- `job_heartbeat` (`scheduler/jobs.py`) fires every 4 hours → Telegram.
- `on_job_error` / `on_job_missed` listeners fire Telegram on failures.

**Gaps:**
1. **If `scheduler.main` itself crashes**, no Telegram fires — the listener can't run.  The 4-hour heartbeat is then silent. You might not notice until Monday 09:30 that nothing fired at 09:25.
2. **Weekend silence:** the next heartbeat after Friday afternoon is Saturday/Sunday/early-Monday. If Charles isn't watching Telegram those nights, a Saturday crash + 3 restart retries + Railway giving up = arrival at Monday open with no scheduler running.
3. **No external uptime monitor** (UptimeRobot, BetterStack, etc.) is configured against `https://<vesper-host>/health` in this repo.

**Recommended fix (15 min of work, pre-Monday):**
- Sign up for UptimeRobot free tier
- Add monitor on the vesper `/health` URL, 5-minute interval, Telegram/email alert
- This catches the case where APScheduler dies but uvicorn lives (and vice versa)

A robust alternative is `sentinel-watchdog` (referenced in PR #43 callout), but **its source is not visible to this audit** and PR #43 explicitly notes the sentinel cleanup is deferred — until then sentinel will fail when the dead generic key is removed from Railway. **Do not remove `ALPACA_API_KEY` from the sentinel-watchdog service until the follow-up sentinel PR is merged.**

---

## 6. Health Check Endpoint — Verified

`scheduler/api.py:25-28`:

```python
@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"})
```

✅ Endpoint exists, returns 200, lightweight, no DB dependency. Matches `deploy/compass-scheduler/railway.toml`'s `healthcheckPath = "/health"`.

**Caveat:** the endpoint is shallow — it returns 200 even if APScheduler died but uvicorn lives. For a "deeper" health check, consider:

```python
@app.get("/health")
def health():
    if _scheduler_ref is None or not _scheduler_ref.running:
        return JSONResponse({"status": "degraded", ...}, status_code=503)
    return JSONResponse({"status": "ok", ...})
```

Not blocking for Monday; nice-to-have.

`/status` endpoint also exists and returns the latest `health.json` + `circuit_breaker.json` — good for the dashboard.

---

## 7. Environment Variables — Static Audit

### Read by scheduler hot path (`grep os.environ scheduler/`)

| Var | Default | Required? | Notes |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `""` | Yes (alerts) | Silently writes to file if missing |
| `TELEGRAM_CHAT_ID` | `""` | Yes | Same |
| `ALPACA_API_KEY_EXP{ID}` × 8 | `""` | Yes per active exp | Hard-fail in `get_alpaca_client` |
| `ALPACA_API_SECRET_EXP{ID}` × 8 | `""` | Yes per active exp | Hard-fail |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | No | Default is paper |
| `ALPACA_PAPER` | `"true"` | No | |
| `POLYGON_API_KEY` | `""` | Yes (L1 data) | Warns and skips L1 |
| `POLYGON_INDICES_API_KEY` | `""` | Yes (indices) | New per PR #42 — VIX/VIX3M routing |
| `COMPASS_DATA_DIR` | `/data` | No | Volume mount path |
| `COMPASS_LOGS_DIR` | `/data/logs` | No | |
| `COMPASS_SIGNALS_DIR` | `/data/signals` | No | |
| `HEALTH_JSON_PATH` | `/data/health.json` | No | |
| `STARTING_CAPITAL` | `"100000"` | No | Used for DD% calc |
| `LOG_LEVEL` | `"INFO"` | No | |
| `PORT` | `"8080"` | No | Railway injects |
| `TZ` | `America/New_York` | Set in Dockerfile | |

**[LIVE-VERIFY]** Run on the vesper service (use `skills/railway/scripts/list-services.sh` to find the service ID, then Railway GraphQL `variables` query, or open the Railway dashboard):

Required keys checklist:
- [ ] `POLYGON_API_KEY` set
- [ ] `POLYGON_INDICES_API_KEY` set (added in PR #42 — verify it didn't get missed)
- [ ] `TELEGRAM_BOT_TOKEN` set
- [ ] `TELEGRAM_CHAT_ID` set
- [ ] `ALPACA_API_KEY_EXP400` + `ALPACA_API_SECRET_EXP400` set
- [ ] Same pair for EXP401, EXP503, EXP600, EXP800, EXP1220, EXP3309, EXP3311
- [ ] `ALPACA_API_KEY` (generic) — **AFTER** PR #43 merges, **remove this** from vesper and dashboard. Do NOT remove from sentinel-watchdog until follow-up PR.

The pre-market check at 08:00 ET will flag missing keys via Telegram — but that's after Sunday-night silence. **Verify in advance, don't wait for the 08:00 ET alarm.**

---

## 8. Hardcoded URLs / Localhost References

Searched all Python source for `localhost` and `127.0.0.1`:

```
api/macro_api.py:766:    logger.info("Swagger UI: http://localhost:%d/docs", args.port)
api/macro_api.py:767:    logger.info("ReDoc:      http://localhost:%d/redoc", args.port)
deploy/macro-api/api/macro_api.py:775:  (same)
deploy/macro-api/api/macro_api.py:776:  (same)
```

✅ Both are **log messages only** (developer ergonomics). Not used as actual targets. No hardcoded production URLs found in hot path.

The only production URL is `https://pilotai-credit-spreads-production.up.railway.app/...` in `RAILWAY_MIGRATION.md` — documentation only, not referenced from code.

---

## 9. Log Access & Retention

### Where logs go

| Sink | Source | Retention |
|---|---|---|
| `stdout` (visible to Railway logs) | All `LOG.info/warning/error` | Railway-managed (~7 days on hobby plan, more on pro) |
| `/data/logs/*.log` | None directly — but `job_log_rotate` (`scheduler/jobs.py:543`) expects them | Files older than 30 days → moved to `archive/`. **Never deleted** — disk grows forever. |
| `/data/logs/failed_alerts.jsonl` | `scheduler/alerts.py:61` Telegram fallback | Never rotated |
| `/data/logs/paper_signals_audit.jsonl` | per-experiment scanners | Never rotated |
| `/data/signals/<date>.json` | per-experiment scanners | Never deleted |

**Issues:**
- `job_log_rotate` moves but doesn't delete. On a 1GB Railway volume this is fine for months; on a 256MB volume it eventually fills.
- `failed_alerts.jsonl` is append-only with no rotation. If Telegram goes down for a week the file just grows.
- Logs are **not** forwarded to a third-party sink (Datadog, Logtail, BetterStack). To debug on Monday you need either Railway dashboard access or `RAILWAY_API_TOKEN` for `skills/railway/scripts/get-logs.sh`.

### How to access logs Monday morning

Three options:

1. **Browser:** Railway dashboard → vesper service → Logs tab. Fastest. Requires Railway login.
2. **CLI (recommended):**
   ```bash
   export RAILWAY_API_TOKEN=<token>
   bash /home/node/.openclaw/workspace/skills/railway/scripts/get-logs.sh <service-id> --tail 500
   ```
3. **GraphQL direct** via `skills/railway/scripts/railway-gql.sh`.

**[LIVE-VERIFY]** Confirm `RAILWAY_API_TOKEN` is available on Charles's local machine. If not, set it before Monday — the dashboard alone is fine, but the CLI is faster for grep'ing 09:25 ET errors.

---

## 10. Restart Policy Analysis

**Scheduler service (vesper / compass-scheduler):**
```toml
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

**Web service (root):**
```json
"restartPolicyType": "ON_FAILURE",
"restartPolicyMaxRetries": 3
```

`ON_FAILURE` semantics: restart only on **non-zero exit**. Crash → restart. Clean shutdown (e.g., from SIGTERM) → no restart.

`maxRetries: 3` semantics: after 3 consecutive failed restarts within Railway's window (~10 min), Railway stops trying.

**Failure scenarios:**

| Scenario | Recovers? |
|---|---|
| OOM kill (SIGKILL on memory limit) | ✅ Yes, exit code != 0 |
| Python uncaught exception bubbling out of `main()` | ✅ Yes |
| `uvicorn.run` returns normally (it doesn't, but defensively) | ❌ Treated as clean exit |
| `SIGTERM` from `_shutdown_handler` then `sys.exit(0)` | ❌ Clean exit, no restart |
| 4th consecutive crash inside 10 min | ❌ Railway gives up |
| Deadlock (process alive, scheduler thread hung) | ❌ Process doesn't exit |

**Recommendation:** raise `restartPolicyMaxRetries` to **10** on both services. There's no downside — a service that's been crash-looping all weekend deserves attempts to recover.

---

## 11. Crash-Recovery Audit

`scheduler/main.py:252-260`:

```python
def _shutdown_handler(signum, frame) -> None:
    LOG.info("Received signal %d — shutting down gracefully", signum)
    send_telegram(f"[VESPER] Service stopping (signal {signum}). ...")
    if _scheduler_ref is not None:
        _scheduler_ref.shutdown(wait=False)
    sys.exit(0)
```

✅ Handles SIGTERM (Railway's normal restart signal) and SIGINT cleanly.
⚠ But: `sys.exit(0)` means a Railway-initiated restart will be classified as a **clean exit** and `ON_FAILURE` will NOT restart it.

This is actually correct behavior — Railway sends SIGTERM precisely BECAUSE it's about to restart you for its own reasons (deploy, scaling, host migration). Railway handles the restart itself in that case, not via the restart policy. Verified pattern; no change needed.

**Telegram alert on shutdown:** the `[VESPER] Service stopping` message gives you a free audit trail of restarts. Good.

**Scheduler state on restart:** APScheduler with default `MemoryJobStore` means **all in-flight jobs and missed-fire history are lost on restart**. If vesper crashes at 09:24:50 ET and restarts at 09:25:30, the 09:25 cron entry has already fired (and missed). The `misfire_grace_time=300` per-experiment means: yes, the job WILL still fire within 5 min of its scheduled time after restart. ✅ OK for Monday.

But: if Railway gives up after 3 retries and you don't restart manually until 09:35, **no scanners fire that day**.

---

## 12. Build-Time Safety Check (👍)

`Dockerfile.scheduler:36-46`:

```dockerfile
RUN python -c "
import numpy, pandas, apscheduler, fastapi, uvicorn, pytz
import requests
try:
    import yfinance
except ImportError:
    print('WARNING: yfinance not available — L3 fallback will be disabled')
from alpaca.data.historical import StockHistoricalDataClient
from scheduler.main import build_scheduler
print('All imports OK')
"
```

✅ Excellent. Broken-dependency regressions are caught at build time, not at 09:25 ET. This is the kind of detail that pays for itself.

**Suggestion:** also import `scheduler.api` and `scheduler.jobs` explicitly. `build_scheduler` does pull `scheduler.jobs` transitively but an explicit `import scheduler.api` would also catch a broken FastAPI import.

---

## 13. The PR #43 Interaction (Active Risk Window)

PR #43 (just APPROVED but **not yet merged**) removes the generic `ALPACA_API_KEY` fallback from the vesper hot path. The PR description states:

> ⚠ sentinel-watchdog will fail until follow-up PR is merged — keep sentinel keys in Railway until then.

**For Monday:**
- If PR #43 lands but Charles also strips `ALPACA_API_KEY` / `ALPACA_API_SECRET` from `sentinel-watchdog` env, sentinel-watchdog will crash on startup. Whatever sentinel is doing (alerting? portfolio gates?) goes silent.
- Mitigation per the PR's own checklist: **remove generic ALPACA keys from vesper service only**, leave sentinel-watchdog vars in place until follow-up PR ships.
- **Do not merge PR #43 on Sunday night** without confirming this. The blast radius if sentinel goes silent + scanners misbehave is large.

Recommend: merge PR #43 **Monday after market close**, not before.

---

## 14. Concrete Pre-Monday Action List (Charles)

Ordered by criticality:

1. **🔴 Resolve dual-scheduling** — `launchctl list | grep pilotai` on Mac Studio. If any LaunchAgents are loaded for the same experiments vesper runs, unload them now:
   ```bash
   for plist in com.pilotai.exp400 com.pilotai.exp401 com.pilotai.exp503 com.pilotai.exp600 com.pilotai.exp1220; do
     launchctl unload ~/Library/LaunchAgents/${plist}.plist 2>/dev/null
   done
   ```
   Document the choice in `MASTERPLAN.md`.

2. **🔴 Add healthcheck to root `railway.json`:**
   ```json
   { "$schema": "https://railway.app/railway.schema.json",
     "deploy": { "restartPolicyType": "ON_FAILURE", "restartPolicyMaxRetries": 10,
                 "healthcheckPath": "/api/health", "healthcheckTimeout": 30 } }
   ```
   (Verify `web_dashboard/app.py` actually exposes `/api/health` first.)

3. **🟠 Verify Railway volume** mounted at `/data` on vesper service. Railway dashboard → Volumes tab.

4. **🟠 Verify env vars on Railway** vesper service — full checklist in §7 above. Especially `POLYGON_INDICES_API_KEY` (new in PR #42).

5. **🟠 Set up external uptime monitor** (UptimeRobot free) on vesper's `/health` URL. 5-min interval, Telegram alert.

6. **🟡 Do NOT merge PR #43 before Monday market close.** Merge Monday afternoon.

7. **🟡 Confirm `RAILWAY_API_TOKEN`** is in your local shell, for fast log access:
   ```bash
   bash skills/railway/scripts/get-logs.sh <vesper-service-id> --tail 500
   ```

8. **🟡 (Optional, nice-to-have)** Bump `restartPolicyMaxRetries` to 10 on both services.

---

## 15. What Works (don't break it)

- ✅ Scheduler exposes `/health` and `/status` endpoints. Both lightweight.
- ✅ Restart policy is `ON_FAILURE` (not `NEVER`).
- ✅ Build-time import check catches broken-dep regressions before deploy.
- ✅ Graceful shutdown via SIGTERM, sends Telegram on stop.
- ✅ APScheduler `misfire_grace_time` is set per-job — late firing is acceptable up to 5 min.
- ✅ Telegram retry + file-fallback (`scheduler/alerts.py`) — never silently loses alerts.
- ✅ Pre-market check at 08:00 ET (`job_pre_market_check`) probes every per-experiment Alpaca key, Polygon, market data, data dirs — gives you 85 min of warning before 09:25 ET.
- ✅ Per-experiment job listeners (`on_job_error`, `on_job_missed`) fire Telegram on any failure.
- ✅ `_get_experiment_env` correctly maps per-exp Railway env vars to the generic names that subprocesses expect (clean adapter pattern).
- ✅ Heartbeat every 4 hours so silence ≠ uncertainty.
- ✅ PR #42 already routed Polygon indices (`I:VIX`, etc.) to a dedicated key — recent infrastructure work is sound.

---

## 16. Items Beyond This Audit's Reach

These would require live access to confirm:

- Whether the Railway services are actually running right now
- Which commits are deployed on each service
- Whether the `/data` volume is mounted and how full it is
- Whether all required env vars are set
- Recent log content showing successful/failed runs
- Whether `sentinel-watchdog` service exists and what it runs
- LaunchAgent state on the Mac Studio (`launchctl list | grep pilotai`)
- Whether the dashboard at `pilotai-credit-spreads-production.up.railway.app` returns 200

**[LIVE-VERIFY] all the above before Monday.**

---

## Appendix A: Files Audited

```
railway.json                          (root config, web service)
Procfile                              (web: uvicorn web_dashboard.app:app)
Dockerfile.scheduler                  (vesper image)
Dockerfile.old                        (legacy combined image)
docker-entrypoint.sh                  (legacy entrypoint)
deploy/compass-scheduler/railway.toml (vesper Railway config)
scheduler/main.py                     (APScheduler bootstrap + uvicorn)
scheduler/api.py                      (FastAPI /health, /status)
scheduler/jobs.py                     (all cron job functions)
scheduler/alerts.py                   (Telegram + fallback)
scheduler/data_providers.py           (Polygon/yfinance/cache chain)
deploy/com.pilotai.exp*.plist         (Mac Studio LaunchAgents)
deploy/README_launchagent.md
RAILWAY_MIGRATION.md
CLEANUP_EXP2830_REPORT.md             (PR #43 context)
MIGRATION_NOTES.md                    (PR #42 context)
sentinel/README.md                    (sentinel module overview)
skills/railway/scripts/*.sh           (diagnostic tooling)
```

## Appendix B: Tools Available for [LIVE-VERIFY]

If `RAILWAY_API_TOKEN` is set:

```bash
# List all Railway services and their config
bash /home/node/.openclaw/workspace/skills/railway/scripts/list-services.sh

# Pull logs from a specific service
bash /home/node/.openclaw/workspace/skills/railway/scripts/get-logs.sh <service-id>

# Inspect env vars (use Railway dashboard for safety; tokens print to stdout)
bash /home/node/.openclaw/workspace/skills/railway/scripts/railway-gql.sh '...'
```

---

**End of CC4 audit.**
🤖 Generated with [Claude Code](https://claude.com/claude-code)
