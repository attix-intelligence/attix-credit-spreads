# 🔴 CC2 — SUBPROCESS CRASH MODES

**Scope:** Will `main.py scheduler` (and `main.py scan`) start, stay up, and execute trades? What kills it?

**Audit date:** 2026-05-24
**Auditor:** CC2 (skeptical audit cohort)
**Method:** Code walk from `main.py` entry through `create_system`, scheduler loop, Alpaca init, PositionMonitor, DB layer, config + env loading.

---

## 🎯 TL;DR Verdict

**🔴 NO-GO** for Tuesday 2026-05-26 market open as a subprocess-reliability matter. Three CRITICAL crash modes are unmitigated and silent — i.e. the system can appear healthy on the heartbeat while not actually executing trades. Specifically:

| # | Crash mode | Symptom |
|---|---|---|
| C-1 | DB path captured at module-import time, set AFTER imports | Reads/writes hit wrong sqlite file → "0 open trades" while Alpaca holds real positions |
| C-2 | AlpacaProvider init failure silently demotes to alert-only | Heartbeats green, scans run, but `execution_engine` has `alpaca=None` → no orders ever submitted |
| C-3 | `requirements.txt` is missing alpaca-py, pytz, colorlog, sentry-sdk, dotenv (only in -scheduler.txt) | ImportError at module load → process exits before main() — no log line, no heartbeat written |

Plus 8 HIGH issues that will degrade the subprocess (timeouts, blocked daemon threads, ephemeral filesystem) and a handful of MEDIUM/LOW noise.

---

## CRITICAL — System cannot trade

### C-1. `shared.database.DB_PATH` is frozen at module-import time
**Where:** `shared/database.py:20`
```python
DB_PATH = Path(_os.environ.get('PILOTAI_DB_PATH', str(Path(DATA_DIR) / "pilotai.db")))
```

**Flow:**
1. `main.py:49` does `from shared.database import get_trades, insert_alert, save_scanner_state, load_scanner_state`. At this point `shared.database` is imported and `DB_PATH` is captured from `os.environ` — **before any .env is loaded and before CLI args are parsed.**
2. `main.py:980` sets `os.environ['PILOTAI_DB_PATH'] = args.db_path` (or YAML `db_path`). Too late — `DB_PATH` module constant already snapshotted.
3. `load_dotenv()` is called from `utils.load_config()` (called by `create_system()`), which runs even later. Same problem.
4. `get_db(path=None)` falls back to `DB_PATH` — i.e. whatever was in env at module-load time (usually nothing, so `data/pilotai.db`).

**What breaks:** Any caller that does NOT pass `path=` explicitly hits the default DB instead of the per-experiment DB. `CreditSpreadSystem.__init__` does pass `path=_db_path` for `load_scanner_state` (line 117). PositionMonitor passes `db_path=self.db_path` on most calls (line 268). But the failure mode is one missing `path=` in a future refactor — trades silently route to `data/pilotai.db` while the operator looks at `data/pilotai_exp3311.db`.

**Safety net:** Partial. Most call sites already thread `path=` through. No structural guarantee.

**Recovery:** None automatic. Manual DB merge required if mismatched writes occur.

**Fix:** Replace `DB_PATH = Path(env.get(...))` with a function `_resolve_db_path()` called at use time, OR re-read the env var inside `get_db()`.

---

### C-2. AlpacaProvider init failure silently demotes the system to alert-only
**Where:** `main.py:147-164`
```python
if alpaca_cfg.get('enabled', False):
    try:
        ...
        self.alpaca_provider = AlpacaProvider(api_key=..., api_secret=..., paper=...)
        logger.info("AlpacaProvider initialized (paper=%s)", ...)
    except Exception as e:
        logger.warning("AlpacaProvider init failed — running in alert-only mode: %s", e)
```

**What breaks:**
- `AlpacaProvider.__init__` (`strategy/alpaca_provider.py:147-162`) constructs `TradingClient` and immediately calls `_verify_connection()` which raises on bad creds, 401/403, or network outage.
- Caught by the broad `except Exception` → logged at WARNING level → `self.alpaca_provider = None`.
- `ExecutionEngine` is then built with `alpaca_provider=None` (`main.py:168-171`). Order submission becomes a no-op — alerts fire, nothing trades.
- Scheduler heartbeats remain GREEN. Scan count increments. No Telegram escalation. No Sentry event (we caught the exception locally).
- `PositionMonitor` is also skipped (`main.py:1197 if system.alpaca_provider`). Open positions go unmanaged.

**Safety net:** None. The only signal is a single WARNING line at startup. Anyone monitoring "is the scheduler running?" sees green.

**Recovery:** Manual restart after fixing creds. There is no auto-retry.

**Fix:** Either re-raise (and let Railway restart), or escalate to Telegram, or set a "degraded mode" flag that watchdog/sentinel keys on.

---

### C-3. `requirements.txt` does not include the runtime trading dependencies
**Where:** `requirements.txt` vs `requirements-scheduler.txt`

`requirements.txt` (used by the web Procfile entry):
```
fastapi, uvicorn, pyyaml, python-dotenv, python-multipart, requests, APScheduler,
numpy, pandas, scikit-learn, joblib, xgboost, httpx
```

`requirements-scheduler.txt` (separate file, must be explicitly used):
```
APScheduler, pytz, fastapi, uvicorn, httpx, alpaca-py, requests, yfinance, numpy, pandas
```

**Missing from EITHER file:**
- `colorlog` (imported unconditionally in `utils.py:10`)
- `sentry-sdk` (imported in `main.py:33` — wrapped in try/except ImportError, OK)
- `polygon-api-client` (used by `shared/polygon_client.py`)
- `backports.zoneinfo` (fallback in `execution/position_monitor.py:34` — only needed for Py<3.9, runtime is 3.10+ so OK)

**Plus:** the active `Procfile` declares only a `web:` worker. There is **no `worker:` entry running `main.py scheduler`**. Whatever process actually invokes `main.py` on Railway must be using a different requirements file (`requirements-scheduler.txt`?). If the deployment uses `requirements.txt` for the scan/scheduler process, `from alpaca.trading.client import TradingClient` in `strategy/alpaca_provider.py:15` raises ImportError at module load — BEFORE main() runs — and the process exits with no log, no heartbeat, no alert.

**Safety net:** Railway restartPolicyType=ON_FAILURE, maxRetries=3 → crash-loop and then dead silence.

**Recovery:** Manual deploy with correct requirements file pinned.

**Fix:** Either (a) consolidate to a single `requirements.txt` that includes alpaca-py + pytz + colorlog, or (b) make the trading worker's nixpacks.toml / start command explicitly install `requirements-scheduler.txt`, and document it.

---

## HIGH — Trading broken, manual intervention

### H-1. `create_system()` pre-warms data cache before scheduler enters its retry loop
**Where:** `main.py:893`
```python
system.data_cache.pre_warm(['SPY', '^VIX', 'TLT'])
```
This is outside the inner `try` around reconciliation. If Polygon/Yahoo is rate-limited or 503ing at startup, `pre_warm` raises → propagates up through `create_system` → caught by the outermost `try` in `main()` → `sys.exit(1)`. Railway restarts up to 3 times, then gives up.

**Symptom:** Scheduler never starts after a data-provider outage at boot.

**Fix:** Wrap `pre_warm` in try/except or make it lazy.

---

### H-2. PositionMonitor's startup reconciliation has no timeout on Alpaca calls
**Where:** `execution/position_monitor.py:262`
```python
all_alpaca = self.alpaca.get_positions()
```
If Alpaca hangs (network partition, half-closed TLS), the daemon thread blocks **before** entering the main loop. Exit signals (`_stop_event`) are not checked. The main process can exit cleanly via SIGTERM (daemon=True kills the thread on process exit), but during the hang positions are unmanaged.

**Safety net:** Caught at `except Exception`, but the underlying request has no timeout.

**Fix:** Configure socket timeout on `TradingClient` or wrap `get_positions` in a future with timeout.

---

### H-3. Scan lock derives experiment id from `db_path`; empty/missing → collision
**Where:** `main.py:1019-1022`
```python
_db_for_lock = args.db_path or os.environ.get("PILOTAI_DB_PATH", "")
_lock_base = os.path.basename(_db_for_lock).replace("pilotai_", "").replace(".db", "")
_exp_id_lock = _lock_base if _lock_base else "unk"
_lock_path = f"/tmp/pilotai_{_exp_id_lock}.lock"
```
If `db_path` is unset and PILOTAI_DB_PATH is unset (default case), the lock collapses to `/tmp/pilotai_unk.lock`. Any experiment scanning without an explicit DB path collides into the same lock → only one scan can run at a time across all such experiments, but they SHARE THE SAME DB → corrupted state.

**Fix:** Use `EXPERIMENT_ID` env var as authoritative lock key, fall back to a hash of the config path.

---

### H-4. `/tmp` lock does NOT serialize across Railway replicas
**Where:** `main.py:1023-1032`
`/tmp` is container-local on Railway. If two replicas of the trading worker were ever spun up (intentionally or via blue/green during deploy), each holds its own `/tmp/pilotai_*.lock` — they will both run scans → duplicate orders to Alpaca.

**Safety net:** Alpaca idempotency via `client_order_id` (need to verify it's set per-leg). If not, duplicate fills.

**Fix:** Use a DB-level lock (e.g., `INSERT INTO scanner_lock ... ON CONFLICT FAIL`) or a Redis/Postgres advisory lock for cross-replica serialization. Best: keep singleton replica via Railway `--replicas 1`.

---

### H-5. Scheduler scan timeout is 600s; the underlying HTTP call has no inner timeout
**Where:** `shared/scheduler.py:32, 153-163`
`ThreadPoolExecutor` cancellation in Python does NOT preempt a blocking C call (sockets). After `future.result(timeout=600)` raises `FuturesTimeoutError`, the worker thread continues running until the underlying request returns. The `with ThreadPoolExecutor(max_workers=1) as pool:` exits and waits for shutdown → it will block until the hung request finishes anyway, defeating the timeout.

**Symptom:** Slot N times out, scheduler appears stuck waiting for slot N+1, missed scans accumulate.

**Fix:** Set HTTP-level timeouts on Polygon/Alpaca clients (`httpx.Timeout(30.0)`).

---

### H-6. `compass.archive.retrain_scheduler` import — naming suggests deprecated
**Where:** `main.py:1123`
```python
from compass.archive.retrain_scheduler import RetrainScheduler
```
`archive/` is conventionally where dead code lives. If a future cleanup deletes the directory, the scheduler subcommand fails at import time on the SLOT_RETRAIN setup — and because the import is at the top of the `scheduler` block (not inside the slot handler), the whole scheduler fails to start.

**Fix:** Move into `compass/retrain_scheduler.py` or wrap the import in a deferred call so missing module only kills the retrain slot.

---

### H-7. Heartbeat written to source directory, not a volume-mounted path
**Where:** `main.py:1105`
```python
_hb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(_hb_dir, exist_ok=True)
```
On Railway, the source directory is part of the deploy image and may be read-only depending on the buildpack. Even when writable, it's ephemeral — gone on each deploy. Watchdog reading `data/.last_scan_*` will see the file disappear after every push and the swallowed `except` will only log at WARNING.

**Fix:** Honor `DATA_DIR` env var (already honored by `shared/scheduler.py:35`) for consistency, and require it to point at a mounted volume.

---

### H-8. PositionMonitor daemon thread runs `init_db()` on construction
**Where:** `execution/position_monitor.py:233` — `init_db(db_path)` in `__init__`.
This runs on the **main thread** (PositionMonitor is constructed inline at `main.py:1198` before `monitor_thread.start()`). It blocks the scheduler boot until DB schema is migrated. Usually fast, but on a corrupted SQLite (after kill -9 mid-WAL) this can take a long time or fail outright → SchedulerScheduler never gets to `run_forever()`.

**Fix:** Defer `init_db()` to `PositionMonitor.start()` so a corrupted DB only kills the monitor thread, not the whole subprocess.

---

## MEDIUM — Degraded operation

### M-1. Two heartbeat files with different schemas
- `shared/scheduler.py:35` writes `data/heartbeat.json` (atomic JSON).
- `main.py:1105` writes `data/.last_scan_{exp_id}` (single ISO timestamp).
Watchdog has to know which to check, and they can disagree (one slot fires `_write_heartbeat` but ScanScheduler's `_write_heartbeat` happens in `finally` after — so two writes per slot, possibly skewed timestamps).

### M-2. `_run_macro_weekly_with_retry` blocks the scheduler thread for up to ~75 minutes
`_BACKOFF_SECS = [300, 600, 1200, 2400]` totals 4500s = 75min of sleep, in addition to attempt durations. The scheduler is single-threaded — during this retry loop, no other slots can fire. The 16:30 SLOT_RETRAIN may be skipped if the Friday 17:00 macro snapshot is retrying.

### M-3. Telegram bot init in `CreditSpreadSystem.__init__` — failure mode unknown
`main.py:135` — `self.telegram_bot = telegram_bot or TelegramBot(self.config)`. Did not audit `TelegramBot.__init__`. If it makes a network call (`getMe`) and that fails on bad token, the whole system fails to construct. Either it eagerly validates (crash) or it lazily fails per-message (silent dropped alerts). Either way unaudited.

### M-4. `signal.signal(SIGTERM, ...)` is registered twice — second call wins
`main.py:973` registers `_shutdown_handler` (sys.exit(0)). `main.py:1223` overwrites it with `_stop_scheduler` (sets stop_event). The first handler is dead code after that point. Same semantic, but a future contributor changing the first handler thinking it's the SIGTERM path will be confused.

### M-5. `_g22_exp_id()` defaults to "EXP-MAIN"
`main.py:73` — if `EXPERIMENT_ID` env var is missing (which it is for non-experiment .env files like `.env.champion`), every sentinel heartbeat is attributed to "EXP-MAIN". The G22 watchdog can't tell experiments apart.

### M-6. `init_db()` is never called in `main.py scan` if Alpaca is disabled
PositionMonitor calls `init_db` in its constructor (`execution/position_monitor.py:233`). In `main.py:1039` PositionMonitor is only built when `system.alpaca_provider` is truthy. For pure-alert experiments, init_db is never called on the trading subprocess — but `insert_alert` / `save_scanner_state` will lazily create tables on first write via `get_db()`'s `mkdir(parents=True, exist_ok=True)`... no wait, that only creates the directory, not the schema. **First write to a fresh DB will fail** with `no such table: alerts` because `executescript` is only in `init_db`.

---

## LOW — Minor

- `datetime.utcnow()` used in `shared/scheduler.py:177` — deprecated in Py 3.12. Emits DeprecationWarning; does not break.
- Sentry init runs BEFORE `logging.basicConfig`, so its own error log line (`main.py:40`) may go to the default stderr handler and be lost on Railway.
- `fcntl` import inside the `scan` branch (`main.py:1018`) is fine on Linux; would crash on Windows but Railway is Linux so this is moot.
- `_validate_paper_mode_safety` requires explicit `paper_mode: true` opt-in (`main.py:823`). A YAML without that key but pointing at LIVE Alpaca passes silently. Belt-and-suspenders would be: if `alpaca.paper=false`, require `live_mode: true` and double-confirm.
- `CreditSpreadSystem.__init__` line 117 catches all exceptions when loading peak_equity from DB and falls back to starting capital. Drawdown CB resets to a higher high-water mark silently. Not a crash, but a risk-management regression.

---

## What Carlos's "subprocess crash mode" question maps to

| Brief question | Verdict |
|---|---|
| Will `main.py scheduler` start? | **NO**, if `requirements.txt` is used at deploy time (C-3). YES if `requirements-scheduler.txt` is used — but that's not declared in Procfile/railway.json. |
| Will it connect to Alpaca? | Maybe. On failure, it silently demotes to alert-only (C-2). |
| What if config files missing? | Crashes cleanly via `FileNotFoundError` → ON_FAILURE restart loop → eventual silence. |
| What if database locked? | `PRAGMA busy_timeout=5000` (5s wait). After that, OperationalError → caught by outer try → sys.exit(1) → restart. |
| What if imports fail? | **Hard crash, no log, no alert** — exit before main() (C-3). |
| What if no network? | AlpacaProvider init fails → silent alert-only (C-2). PolygonClient calls in scan_opportunities propagate exceptions → caught by ScanScheduler outer try → logged, slot skipped, next slot retried. |

---

## Required mitigations BEFORE market open

1. **Verify the deployment installs `requirements-scheduler.txt`** for the trading worker, OR consolidate. (C-3)
2. **Re-raise on AlpacaProvider init failure** so Railway restarts the process and operator gets a clear signal. Better: escalate to Telegram. (C-2)
3. **Confirm DB_PATH propagation** by running `python -c "from shared.database import DB_PATH; print(DB_PATH)"` AFTER sourcing `.env.exp3311` and verifying it matches `configs/paper_exp3311.yaml`. (C-1)
4. **Add HTTP-level timeouts** to Polygon and Alpaca clients (H-5).
5. **Replace `/tmp` lock with DB lock** OR pin Railway replicas to 1 (H-4).
6. **Move `init_db()` out of `PositionMonitor.__init__`** OR ensure it's called explicitly from `create_system` (M-6, H-8).

---

## Verification commands

```bash
# C-3 dependency check — run inside the actual deploy container
python -c "import alpaca.trading.client, pytz, colorlog, dotenv" || echo "MISSING DEPS"

# C-1 DB path drift
EXPERIMENT_ID=EXP-3311 python -c "
import os
os.environ['PILOTAI_DB_PATH'] = 'data/pilotai_exp3311.db'
from shared.database import DB_PATH
print('DB_PATH=', DB_PATH)
assert str(DB_PATH).endswith('exp3311.db'), 'FROZEN AT WRONG VALUE'
"

# C-2 simulated bad creds — run the actual main.py and grep
ALPACA_API_KEY=bogus ALPACA_SECRET_KEY=bogus python main.py scan 2>&1 | grep -E "AlpacaProvider|alert-only"

# H-5 timeout coverage
grep -RE "Timeout\(|timeout=" shared/polygon_client.py strategy/alpaca_provider.py

# M-6 schema bootstrap on fresh DB
rm -f /tmp/probe.db
PILOTAI_DB_PATH=/tmp/probe.db python -c "
from shared.database import insert_alert
insert_alert({'id':'t1','ticker':'SPY','data':{}})
" && echo OK || echo SCHEMA-MISSING
```

---

## GO / NO-GO

**🔴 NO-GO** until C-1, C-2, C-3 are explicitly verified by the operator in the actual Railway deployment shell (not locally). The CRITICAL issues all share the property that they fail silently — i.e. there is no automated check that will tell you the system isn't trading until trade-execution-time, by which point you've missed the slot.

Conditional GO if all three CRITICAL verifications above pass and at least H-5 + H-8 are fixed.

---

## Notes for sister CC sessions

- **CC1 (BOOT):** `Procfile` has no worker entry. `railway.json` only sets restart policy. Whatever starts `main.py scheduler` on Railway is invisible to this repo — check the Railway dashboard's start command and which requirements file it installs.
- **CC3 (SCAN):** `system.scan_opportunities` is called inside `scan_and_sync` (`main.py:1189`). Exceptions caught by `ScanScheduler` outer try. You own that path's failure modes.
- **CC4 (ORDER EXEC):** `ExecutionEngine` is built with `alpaca_provider=None` if init failed (see C-2). All your order-submission paths must handle that gracefully — ideally fail loud, not silent.
- **CC5 (MONITOR):** PositionMonitor's `init_db` in `__init__` and unbounded Alpaca calls in `_startup_reconciliation` are your problem. Daemon thread can hang the scheduler boot.
