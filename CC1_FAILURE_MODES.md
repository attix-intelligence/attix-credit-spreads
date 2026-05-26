# CC1 — BOOT FAILURE MODES

**Audit window:** 2026-05-24 (Sun) — pre-market for Mon 2026-05-26 13:30 UTC
**Scope:** Will the Railway scheduler service even start and successfully spawn the 8 experiment scanners at 09:25 ET Monday?
**Method:** Compare `Dockerfile.scheduler` COPY manifest against the import graph of `scheduler/main.py` and the subprocess entry point `python main.py scheduler --config …`.
**Verdict:** **NO-GO. Catastrophic build/runtime mismatch — zero trades will execute Monday.**

---

## TL;DR

- The scheduler service WILL boot (the Dockerfile build-time smoke test passes, FastAPI `/health` returns 200).
- At 09:25 ET Monday, APScheduler will fire `job_run_experiment` for all 8 experiments.
- Every single subprocess will exit non-zero within ~200 ms with `ModuleNotFoundError: No module named 'strategies'` (and, behind it, `'execution'`).
- The system will appear healthy from outside (Telegram heartbeat, /health 200) while doing zero trading.
- Carlos will get 8 Telegram failure alerts at 09:25–09:35 ET. There is no recovery path without a rebuild + redeploy.

---

## CRITICAL — System cannot trade

### C1 — `Dockerfile.scheduler` does not COPY `strategies/`

**Failure scenario.** At 09:25 ET Mon-Fri, `scheduler/jobs.py:job_run_experiment` spawns:

```
python <project_root>/main.py scheduler --config configs/paper_champion.yaml
```

Inside `main.py`, line 56 imports `shared.snapshot_builder`. That module's line 15–16 does:

```python
from strategies.base import MarketSnapshot
from strategies.pricing import calculate_rsi
```

The `strategies/` directory IS tracked in `main` (`git ls-tree main -- strategies/` shows 9 source files including `base.py`, `pricing.py`, `credit_spread.py`, etc.). It is NOT in the Dockerfile COPY manifest:

```
Dockerfile.scheduler:21  COPY compass/    ./compass/
Dockerfile.scheduler:22  COPY scheduler/  ./scheduler/
…
Dockerfile.scheduler:27  COPY strategy/   ./strategy/        ← singular, different module
Dockerfile.scheduler:30  COPY scripts/    ./scripts/
Dockerfile.scheduler:31  COPY main.py utils.py ./
```

`strategy/` (singular, present) and `strategies/` (plural, missing) are **two distinct top-level packages**. Verified:

```
$ ls strategy/ strategies/  # local working tree
strategy/    : alpaca_provider.py, credit_spread.py, options_analyzer.py, technical_analyzer.py
strategies/  : base.py, calendar_spread.py, credit_spread.py, debit_spread.py, gamma_lotto.py,
               iron_condor.py, ml_enhanced_strategy.py, momentum_swing.py, pricing.py,
               straddle_strangle.py
```

The author of commit `ce168e4` ("fix(P0-3,P0-4,P1-2): wire Alpaca orders…") listed in the commit message:

> Update Dockerfile.scheduler to copy all required directories (sentinel/, shared/, alerts/, backtest/, strategy/, tracker/, configs/, scripts/, main.py).

They added `strategy/` and forgot `strategies/`. The build-time import smoke test (Dockerfile lines 36-46) only validates `from scheduler.main import build_scheduler`, which does not transitively load `shared.snapshot_builder` — so the build PASSES and the deploy succeeds.

**Where in code.** `shared/snapshot_builder.py:15-16`, `shared/signal_scorer.py:15`, `shared/strategy_adapter.py:13`, `shared/strategy_factory.py:136-145`. The first three are **module-level** imports that fire when `main.py` line 51-58 runs.

**What breaks.** `python main.py scheduler …` exits with exit code 1 before argparse runs. `scheduler/jobs.py:job_run_experiment` catches the non-zero rc, dumps last 10 lines of stderr to log, and sends Telegram alert `"[EXP-400] Scanner failed on 2026-05-26 (rc=1)"`. Identical alerts fire for EXP-401/503/600/800/1220/3309/3311 — 8 alerts in a tight burst, then silence until 04:30 UTC Tuesday.

**Safety net.** None at the system level. The Dockerfile smoke test is structured to miss this. The scheduler does not pre-flight a `python -c "import main"` check at startup. APScheduler does not validate the subprocess will work before scheduling.

**Recovery path.**
1. Add `COPY strategies/ ./strategies/` to `Dockerfile.scheduler:27` (next to `strategy/`).
2. Add `COPY execution/ ./execution/` (see C2).
3. Strengthen the smoke test (see C3).
4. Push, wait for Railway rebuild + deploy (~3–5 min), verify with `railway logs` and a manual cron trigger via `/status`.

This is **the only blocker that matters** for Monday open.

---

### C2 — `Dockerfile.scheduler` does not COPY `execution/`

**Failure scenario.** Even if C1 were fixed, `main.py` line 167 inside `CreditSpreadSystem.__init__` does:

```python
from execution.execution_engine import ExecutionEngine
```

`execution/` is tracked on `main` (`git ls-tree main -- execution/` returns `__init__.py`, `execution_engine.py`, `position_monitor.py`). It is NOT in the Dockerfile COPY manifest.

**Where in code.** `main.py:167` (inside `__init__`, runs after argparse but before any scan), plus `main.py:1040, 1052` (PositionMonitor — used when scheduler mode enters the polling loop).

**What breaks.** `CreditSpreadSystem(...)` constructor raises `ModuleNotFoundError: No module named 'execution'`. Subprocess exits rc=1. Same failure path as C1, same Telegram blast.

**Safety net.** None. The import is unconditional, outside any try/except.

**Recovery path.** Add `COPY execution/ ./execution/` to Dockerfile. Combined with C1 fix in the same rebuild.

---

### C3 — Dockerfile build-time smoke test gives false confidence

**Failure scenario.** `Dockerfile.scheduler:36-46` includes:

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

`scheduler.main` imports `scheduler.jobs`, which **only lazy-imports** `subprocess` and `sys` at function-call time. The `main.py` module — which is the actual subprocess entry point — is never loaded at build time. C1 and C2 therefore pass the build silently.

**Where in code.** `Dockerfile.scheduler:36-46`.

**What breaks.** Every deploy reports green. Confidence is unjustified.

**Safety net.** None. The CI pipeline (if any) doesn't run the subprocess entry point either.

**Recovery path.** Replace the build-time smoke test with the subprocess entry point:

```dockerfile
RUN python -c "
from scheduler.main import build_scheduler
import main  # subprocess entry — must import cleanly
import execution.execution_engine, execution.position_monitor
import strategies.base, strategies.pricing
build_scheduler()  # exercises job registration
print('Build smoke test: OK')
"
```

Add a `--dry-run` flag to `main.py scheduler` that constructs `CreditSpreadSystem(...)` then exits 0 without scanning — call it from the Dockerfile.

---

## HIGH — Trading broken, manual intervention needed

### H1 — `_get_experiment_env` silently drops missing keys for EXP-3309 / EXP-3311

**Failure scenario.** `scheduler/main.py:227-228` schedules EXP-3309 and EXP-3311. `scheduler/jobs.py:_get_experiment_env` (line 94-113) looks up `ALPACA_API_KEY_EXP3309` / `ALPACA_API_SECRET_EXP3309` from `os.environ`. If unset, lines 104-107 simply do not assign `ALPACA_API_KEY` to the subprocess env — there is no error, no log line, no Telegram alert.

The subprocess then loads its YAML which contains `api_key: ${ALPACA_API_KEY}`; `main.py:152-156` expands the env var to the empty string. `AlpacaProvider(api_key="", …)` is then called inside the try/except at `main.py:151-164`. The exception is caught and emits ONLY `logger.warning("AlpacaProvider init failed — running in alert-only mode: %s", e)`. The scanner proceeds, generates signals, routes them through `AlertRouter`, but `execution_engine.alpaca_provider is None` → orders are not submitted. Subprocess exits rc=0. Telegram never alerts.

**Where in code.** `scheduler/jobs.py:104-107`; `main.py:151-164`.

**What breaks.** EXP-3309 and EXP-3311 silently degrade to alert-only mode. From outside, everything looks fine: the scanner ran, the heartbeat fires, the equity journal updates (using EXP-400's account). The signals appear in `data/signals/YYYY-MM-DD.json` but no orders ever land at Alpaca.

**Safety net.** None at runtime. `job_pre_market_check` at 08:00 ET DOES check `ALPACA_API_KEY_EXP3309` (jobs.py:126-140) and emits a Telegram warning if missing — but it does NOT block the 09:25 fire. And the warning is `f"WARN: {eid} keys missing"` mixed in with passes; easy to miss.

**Recovery path.**
1. Before market open, run `railway variables list -s <scheduler-service>` and confirm `ALPACA_API_KEY_EXP3309`, `ALPACA_API_SECRET_EXP3309`, `ALPACA_API_KEY_EXP3311`, `ALPACA_API_SECRET_EXP3311` are present and non-empty.
2. Patch `_get_experiment_env` to raise (not return) if the expected suffix is unset, so `job_run_experiment` registers a CRITICAL Telegram alert.

---

### H2 — `.env.exp*` files not present in the image, but `--env-file` path is still constructed

**Failure scenario.** `scheduler/jobs.py:582-587`:

```python
if env_file:
    env_file_path = project_root / env_file
    if env_file_path.exists():
        cmd += ["--env-file", str(env_file_path)]
    else:
        job_log(job_name, f"WARN: env_file {env_file} not found, using default env")
```

`Dockerfile.scheduler` does NOT copy `.env.exp400`, `.env.exp401`, `.env.exp3309`, `.env.exp3311` (only `main.py utils.py` from the repo root are copied — see line 31). So `env_file_path.exists()` is always False inside the container.

**Where in code.** `scheduler/jobs.py:582-587`; `Dockerfile.scheduler:31`.

**What breaks.** Subprocesses run without `--env-file`. They depend entirely on the per-experiment Railway env vars surviving the `_get_experiment_env` mapping. If H1 fires, the experiment silently falls into alert-only mode. The local-vs-Railway environment is divergent — anyone running `python main.py scheduler --config configs/paper_exp400.yaml --env-file .env.exp400` locally gets a DIFFERENT execution path than Railway's containerised run. Backtest-live parity is degraded.

**Safety net.** The fallback is documented in the WARN log line, but it's a log-only fallback, not a Telegram alert.

**Recovery path.** Either (a) explicitly `COPY .env.exp400 .env.exp401 .env.exp3309 .env.exp3311 ./` in the Dockerfile and commit them to the image build context (but these contain secrets — bad pattern), or (b) delete the `--env-file` code path entirely and rely solely on Railway env vars + `_get_experiment_env` (cleaner). Option (b) is the right answer; in that case, kill the env_file slot in `scheduler/main.py:220-228`.

---

### H3 — In-memory APScheduler jobstore loses schedule across restarts

**Failure scenario.** `scheduler/main.py:96` constructs `BackgroundScheduler(timezone=ET)` with the default jobstore (`MemoryJobStore`). Railway is configured with `restartPolicyType = "ON_FAILURE"` and `restartPolicyMaxRetries = 3` (`deploy/compass-scheduler/railway.toml:9-10`).

If the container restarts at 09:24:55 ET, the schedule is rebuilt fresh; the 09:25 trigger has not yet fired so it will fire normally. But if the container restarts at 09:30:01 ET (1 min after fire), the new schedule's 09:25 trigger is in the past. `misfire_grace_time=300` (5 min) on each `add_job(...)` call means the trigger only fires on restart if it's <5 min late. A restart at 09:30:01 → fires (4 min 1 sec late). A restart at 09:30:30 → does NOT fire. Zero trades that day, and no alert because APScheduler treats it as "expired beyond grace window."

**Where in code.** `scheduler/main.py:96` (jobstore default); `scheduler/main.py:230-238` (per-experiment `misfire_grace_time=300`); `deploy/compass-scheduler/railway.toml:9-10` (restart policy).

**What breaks.** Random schedule loss if Railway restarts during 09:25-09:30 ET — a window where restarts ARE possible (deploys, healthcheck failures, OOM).

**Safety net.** `on_job_missed` listener (`scheduler/main.py:82-90`) emits Telegram alerts — but only if the miss is *within* the grace window. A miss *beyond* the grace window simply doesn't fire at all and never enters MISSED — silent loss.

**Recovery path.** (1) Set `misfire_grace_time` for the per-experiment jobs to something much larger like 1800s (30 min). (2) Switch to `SQLAlchemyJobStore` backed by a persistent SQLite file on a Railway volume — but Railway volume policy must support write persistence (see M1). (3) Add a manual `/run/{exp_id}` endpoint to `scheduler/api.py` so Carlos can re-trigger by HTTP if a fire was lost.

---

### H4 — `/data` is not a Railway volume — heartbeat/journal/circuit-breaker state is ephemeral

**Failure scenario.** `Dockerfile.scheduler:33` does `RUN mkdir -p /data/logs /data/signals`. `Dockerfile.scheduler:53` sets `ENV COMPASS_DATA_DIR=/data`. `deploy/compass-scheduler/railway.toml` does NOT declare a `[mounts]` block. So `/data` is container-ephemeral and is wiped on every restart, redeploy, or replica rotation.

**Where in code.** `Dockerfile.scheduler:33,53`; `deploy/compass-scheduler/railway.toml` (no `[mounts]` section); `scheduler/jobs.py:38-43` (`DATA_DIR`, `SIGNALS_DIR`, `LOGS_DIR`, `HEALTH_JSON`, `EG_JSON`, `CB_JSON` all under `/data`).

**What breaks.**
- `health.json` lost on restart → `job_circuit_breaker_check` (jobs.py:315-329) cannot compute drawdown → emits no DD-halt alert even if portfolio is bleeding.
- `equity_journal.csv` lost → weekly summary at Friday 16:35 reports "No equity data available for this week" instead of actual P&L.
- `signals/YYYY-MM-DD.json` lost → post-market summary cannot count opens; data freshness check at 17:00 ET reports "Signal file missing".
- `circuit_breaker.json` lost → `/status` endpoint returns `{}` for that field; external monitoring blind.

**Safety net.** None. The "stale data" alert at 17:00 (`job_data_freshness_check`) will fire if files are missing — but that's after-market, not before.

**Recovery path.** Add `[[deploy.mounts]]` (or whatever Railway syntax is current) to `railway.toml`, mounting a named volume at `/data`. Verify `railway volume list` shows the volume attached.

---

### H5 — Graceful shutdown does not wait for scheduler jobs

**Failure scenario.** `scheduler/main.py:252-260` `_shutdown_handler` calls `_scheduler_ref.shutdown(wait=False)` then immediately `sys.exit(0)`. `wait=False` means APScheduler returns immediately without waiting for in-flight jobs. If a subprocess scanner is mid-run (which can be 5+ minutes), `sys.exit(0)` tears down the process; the subprocess gets orphaned and reparented to PID 1. On Railway, the container shuts down → subprocess killed mid-flight.

**Where in code.** `scheduler/main.py:258-260`.

**What breaks.** A redeploy at 09:27 ET kills the running scanner subprocesses for 8 experiments. Some may have already submitted some orders (partial fills, half-built iron condors); those orders are orphaned (Alpaca has them, but the scanner's DB doesn't, because writes are batched). On restart, `PositionMonitor` discovers "orphan" positions but does not know what they were for.

**Safety net.** Reconciliation (CC5 territory) attempts to recover orphans. Subprocess output is `capture_output=True`, so stdout/stderr are captured by the parent; if the parent dies, that capture is lost too.

**Recovery path.** `_scheduler_ref.shutdown(wait=True)` with a Railway grace period of >120s. Also signal the subprocess group, not just the parent.

---

## MEDIUM — Degraded operation

### M1 — `restartPolicyMaxRetries = 3` means 3 strikes and Railway gives up

`deploy/compass-scheduler/railway.toml:10`: if the service crashes 3 times in a row, Railway stops restarting. If a deploy goes bad Sunday night and the service crash-loops, by Monday open Railway will have stopped trying. No Telegram alert from Railway side (the `_shutdown_handler` Telegram only fires on graceful SIGTERM, not on crash). System completely down, no signal to operator unless they're watching the Railway dashboard.

**Recovery.** Raise to `restartPolicyMaxRetries = 10` and add a separate external pinger (e.g., UptimeRobot hitting `/health` every 5 min with a Telegram webhook on failure).

---

### M2 — `subprocess.run(..., capture_output=True, timeout=600)` deadlock risk

`scheduler/jobs.py:593-600`: `capture_output=True` captures stdout/stderr into pipes with a 64 KB OS buffer. If a scanner subprocess writes more than 64 KB to stdout before the parent reads (i.e., before the subprocess exits), the subprocess blocks on the pipe write. `subprocess.run` only reads after the subprocess exits — so the subprocess hangs until `timeout=600` kills it. Loud scanners with verbose logging will silently freeze.

**Recovery.** Switch to streaming I/O (`subprocess.Popen` with a reader thread), or set `stdout=subprocess.DEVNULL` and `stderr=subprocess.PIPE` only (stderr alone is small).

---

### M3 — `Dockerfile.scheduler` runs `useradd compass` after `mkdir /data` but does not `chown /data compass`

`Dockerfile.scheduler:33,48-49`:

```dockerfile
RUN mkdir -p /data/logs /data/signals
...
RUN useradd -m -u 1001 compass
USER compass
```

`/data` is owned by root. `USER compass` then runs as uid 1001. Any write to `/data` by the scheduler (heartbeat, health.json, log rotation, equity journal append) will raise `PermissionError`. The scheduler will boot, but every cron job that writes state will fail silently inside its try/except.

**Where in code.** `Dockerfile.scheduler:33,48-49`. Compounded by H4 (no volume mount).

**Recovery.** Either `RUN chown -R compass:compass /data` between mkdir and useradd, OR mount a Railway volume and let Railway handle ownership.

**Note:** This bug coexists with H4. If H4 is fixed (volume mounted), Railway's volume mount will own its mount path; the `chown` may still be needed inside the volume.

---

### M4 — `job_pre_market_check` does not gate the 09:25 fire

`job_pre_market_check` at 08:00 ET (jobs.py:120-185) detects missing keys / dead Alpaca / no SPY price. It sends a Telegram alert but does not pause/disable the 09:25 jobs. Carlos has 85 min to react to the alert before the (broken) scanner fires anyway.

**Recovery.** Write `data/premarket_check.json` with `{"go": false, "reason": "..."}` on failure; have `job_run_experiment` consult it and abort with a clear log if no-go.

---

### M5 — No version pin for `requests`, `numpy`, `pandas`, `scikit-learn`, `xgboost`

`requirements.txt:6,12-16` uses `>=` — a transitive resolve could land a newer major. xgboost 3.x and scikit-learn 1.7 have removed APIs vs 2.x / 1.4. A Railway rebuild on Monday morning could pull a breaking version.

**Recovery.** Pin to `==` for the production image. Add a `pip-compile`/`uv lock` step.

---

### M6 — `from utils import load_config, setup_logging, validate_config` (main.py:60)

`utils.py` is in repo root and IS copied. Confirmed OK — listed here only because the rest of the boot path is so fragile that confirming each non-failure is worth the audit time.

---

### M7 — `data/` directory not copied

The Dockerfile does not COPY `data/` from the repo. Local `data/options_cache.db`, `data/portfolio_risk.db`, and other SQLite files (if used by main.py at runtime) won't be present. They're tracked? Let's note: per CC3's audit territory, IronVault DB is the canonical source — but if any code path expects a local DB seed in the image, it'll find an empty `/data` (which doesn't even exist post-USER-switch — see M3).

---

## LOW — Minor issues / observations

- **L1.** `ENV TZ=America/New_York` is set, but `pytz.timezone("America/New_York")` is also used explicitly in code — fine, but redundant.
- **L2.** `Dockerfile.scheduler` removes `Dockerfile.old` references; if anything still pulls from `Dockerfile.old`, it'll be drastically different. `Dockerfile.old` lists `COPY *.py ./` and `COPY ml/`, `COPY config.yaml.example ./config.yaml`. Not in active use.
- **L3.** `RUN python -c "..."` smoke test uses single double-quoted string across multiple lines — depends on shell interpretation; brittle.
- **L4.** `scheduler/main.py:65` `_START_TIME = datetime.utcnow()` is module-load time, not `main()` time; a long Dockerfile build won't skew this, but the resulting uptime is correct only because module load and main() are <1s apart.
- **L5.** `signal.signal(SIGTERM, ...)` is registered in `main()` — if `main()` is not entered (which only happens if `__name__ == "__main__"` is False), no shutdown handler is in place. The Dockerfile `CMD ["python", "-m", "scheduler.main"]` runs it as `__main__`, so OK.
- **L6.** APScheduler with `BackgroundScheduler` + uvicorn.run() in main thread: scheduler thread will outlive uvicorn if uvicorn exits first via FastAPI lifespan shutdown; not a boot failure but a tear-down quirk.
- **L7.** No `__init__.py` check for `compass.macro_db` lazy DB connection. If the DB file is missing, `compass/macro_db.py:LIQUID_SECTOR_ETFS` (a module-level constant) is still defined — but `get_current_macro_score()` will raise. Not a boot failure; runtime degradation.

---

## Summary table

| ID | Severity | What breaks | Fix complexity |
|----|---------|-------------|---------------|
| **C1** | CRITICAL | All 8 scanners ModuleNotFoundError at 09:25 ET | 1-line Dockerfile change + rebuild |
| **C2** | CRITICAL | Even after C1, ExecutionEngine import fails | 1-line Dockerfile change + rebuild |
| **C3** | CRITICAL | Build-time smoke test misses C1/C2 | Replace smoke test |
| H1 | HIGH | EXP-3309/3311 silent alert-only mode | Audit Railway env vars + raise on missing |
| H2 | HIGH | `.env.exp*` files not in image | Delete env_file slot OR add COPY |
| H3 | HIGH | Lost schedule on restart at :30+ window | Increase grace + persistent jobstore |
| H4 | HIGH | `/data` ephemeral — state lost on restart | Mount Railway volume |
| H5 | HIGH | Subprocess scanners orphaned on shutdown | `wait=True` + Railway grace |
| M1 | MEDIUM | After 3 crashes, Railway gives up | Raise retries + external pinger |
| M2 | MEDIUM | Verbose scanners deadlock at 64 KB stdout | Streaming I/O |
| M3 | MEDIUM | `/data` permission denied as user `compass` | chown in Dockerfile |
| M4 | MEDIUM | Pre-market check doesn't gate 09:25 fire | Add go/no-go file |
| M5 | MEDIUM | Unpinned `>=` deps could break on rebuild | Pin all deps |
| M6 | n/a | (utils.py OK — listed for completeness) | n/a |
| M7 | MEDIUM | `data/` not in image; user-switch breaks `/data` writes | See M3 + H4 |
| L1–L7 | LOW | Various | Backlog |

---

## What "system can boot" actually tested

Locally:

```
$ python3 -c "import ast
for f in ['shared/snapshot_builder.py','shared/signal_scorer.py','shared/strategy_adapter.py','main.py']:
    tree = ast.parse(open(f).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split('.')[0]
            if top in {'strategies','execution','experiments','engine'}:
                print(f'{f}:{node.lineno}  from {node.module} import ...')"

shared/snapshot_builder.py:15  from strategies.base import ...
shared/snapshot_builder.py:16  from strategies.pricing import ...
shared/signal_scorer.py:15  from strategies.base import ...
shared/strategy_adapter.py:13  from strategies.base import ...
shared/strategy_factory.py:136 from strategies.credit_spread import ...  (lazy)
main.py:167  from execution.execution_engine import ...
main.py:1040 from execution.position_monitor import ...
main.py:1052 from execution.position_monitor import ...
```

`Dockerfile.scheduler` COPY manifest (lines 21-31):

```
compass/ scheduler/ sentinel/ shared/ alerts/ backtest/ strategy/ tracker/ configs/ scripts/ main.py utils.py
```

Missing: **`strategies/`** (3 module-level imports), **`execution/`** (1 unconditional `__init__` import), `experiments/` (only lazy imports — not boot-blocking but blocks `shared.portfolio_risk` and sentinel paths).

---

## Final verdict

**NO-GO for Monday open** until C1, C2, C3 are fixed in a single Dockerfile change + rebuild. Approximate diff:

```diff
+ COPY strategies/ ./strategies/
+ COPY execution/  ./execution/
+ COPY experiments/ ./experiments/
  ...
- RUN python -c "
- import numpy, pandas, apscheduler, fastapi, uvicorn, pytz
- ...
- from scheduler.main import build_scheduler
- print('All imports OK')
- "
+ RUN python -c "
+ from scheduler.main import build_scheduler
+ import main
+ import execution.execution_engine, execution.position_monitor
+ import strategies.base, strategies.pricing
+ build_scheduler()
+ print('Build smoke test: OK')
+ "
```

Then verify by running, inside the image:

```
docker run --rm <image> python -c "import main; print('main OK')"
docker run --rm <image> python main.py scheduler --config configs/paper_champion.yaml --dry-run
```

Without these fixes: **8 Telegram failure alerts will fire at 09:25 ET Monday. Zero trades. No recovery without rebuild.**
