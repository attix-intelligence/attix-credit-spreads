# 🔴 MAXIMUS IMMEDIATE FAILURE MODES — Before CC Sessions Report

**Assumption: System won't even start. Here's what I see immediately.**

---

## CRITICAL FAILURE MODES (System Cannot Trade)

### 1. **Railway Volume Mount Missing**
**Scenario:** `RAILWAY_VOLUME_MOUNT_PATH` env var not set or volume not actually mounted  
**Where:** `railway_worker.py` line 50  
**What breaks:** 
- `DATA_DIR = Path(VOLUME_MOUNT) if VOLUME_MOUNT else PROJECT_DIR / "data"`
- Falls back to `data/` in container (ephemeral storage)
- All databases written to ephemeral disk = WIPED ON EVERY DEPLOYMENT
- Every restart = fresh start, all trade history lost

**Safety net:** None. Code silently falls back to ephemeral storage.

**Recovery:** System appears to work but loses all data on restart. SILENT FAILURE.

**Severity:** 🔴 **CRITICAL**

---

### 2. **registry.json Not Found or Malformed**
**Scenario:** `experiments/registry.json` missing, corrupted, or has invalid JSON  
**Where:** `railway_worker.py` calls `get_manager().active()`  
**What breaks:**
- `get_manager()` in `experiments/manager.py` loads registry on first call
- If file missing: crashes with `FileNotFoundError`
- If JSON invalid: crashes with `JSONDecodeError`
- Worker never spawns any experiments

**Safety net:** None. Process crashes immediately.

**Recovery:** Manual fix + redeploy. No trades execute until fixed.

**Severity:** 🔴 **CRITICAL**

---

### 3. **No Active Experiments in Registry**
**Scenario:** All experiments have `"status": "paused"` or `"status": "retired"`  
**Where:** `get_manager().active()` returns empty list  
**What breaks:**
- `for p in procs.values()` loop has zero iterations
- Worker starts but spawns nothing
- System runs but never scans, never trades

**Safety net:** None. Silent success with zero work.

**Recovery:** Change at least one experiment to `"status": "active"` and redeploy.

**Severity:** 🔴 **CRITICAL**

---

### 4. **Alpaca Env Vars Missing**
**Scenario:** `ALPACA_API_KEY_EXP400` or `ALPACA_API_SECRET_EXP400` not set on Railway  
**Where:** `railway_worker.py` line 118-120 in `build_subprocess_env()`  
**What breaks:**
- Subprocess gets env with `ALPACA_API_KEY=None` or empty string
- `main.py` initializes `AlpacaProvider` with invalid credentials
- Alpaca API returns 401 Unauthorized
- System logs error but subprocess keeps running (scan loops with no execution)

**Safety net:** Smoke test should catch this. But if smoke test skipped = silent failure.

**Recovery:** Set env vars on Railway, restart worker.

**Severity:** 🔴 **CRITICAL**

---

### 5. **Config File Missing for Active Experiment**
**Scenario:** registry.json says `"config_path": "configs/paper_exp400.yaml"` but file doesn't exist  
**Where:** `main.py` line ~100 in `create_system(config_file)`  
**What breaks:**
- `load_config(config_file)` raises `FileNotFoundError`
- Subprocess crashes immediately
- Worker detects crash, waits 15 seconds, restarts subprocess
- Crash loop forever (15-second intervals)

**Safety net:** Worker supervisor restarts, but it will crash again immediately.

**Recovery:** Add missing config file, redeploy, or mark experiment inactive in registry.

**Severity:** 🔴 **CRITICAL** (for that experiment)

---

### 6. **Database File Locked (Multi-Process SQLite)**
**Scenario:** Two experiments accidentally configured with same `db_path`  
**Where:** SQLite write in `shared/database.py`  
**What breaks:**
- First subprocess opens DB, acquires lock
- Second subprocess tries to write, gets `sqlite3.OperationalError: database is locked`
- Second subprocess crashes or hangs depending on timeout

**Safety net:** SQLite WAL mode + busy timeout (5 seconds). But if lock held longer = crash.

**Recovery:** Fix registry to give each experiment unique `db_path`.

**Severity:** 🔴 **CRITICAL**

---

### 7. **IronVault options_cache.db Missing**
**Scenario:** `data/options_cache.db` not uploaded to Railway volume  
**Where:** `shared/iron_vault.py` singleton initialization  
**What breaks:**
- `HistoricalOptionsData` constructor checks if DB exists
- If missing: raises `FileNotFoundError` with message "options_cache.db not found — HARD FAIL (Rule Zero)"
- Every subprocess crashes on first `get_iron_vault()` call
- All experiments crash, worker restarts them, crash loop

**Safety net:** Intentional hard-fail (Rule Zero: no synthetic data). System refuses to run.

**Recovery:** Upload `options_cache.db` to Railway volume, redeploy.

**Severity:** 🔴 **CRITICAL**

---

### 8. **Python Dependencies Missing**
**Scenario:** Railway build fails to install `requirements.txt` or packages corrupted  
**Where:** Any import in `railway_worker.py`, `main.py`, etc.  
**What breaks:**
- `ImportError` or `ModuleNotFoundError` on startup
- Process crashes before even reading config

**Safety net:** Railway build should fail and refuse to deploy. But if build succeeds with partial install = runtime crash.

**Recovery:** Fix `requirements.txt`, trigger rebuild.

**Severity:** 🔴 **CRITICAL**

---

### 9. **Market Closed Forever (Infinite Sleep)**
**Scenario:** Scheduler starts on a Friday night or holiday weekend  
**Where:** `shared/scheduler.py` calculates next slot  
**What breaks:**
- Scheduler sleeps until next market open (could be 60+ hours)
- System appears alive but does nothing for days
- No scans, no trades, no errors

**Safety net:** None. Scheduler is designed to sleep until next slot.

**Recovery:** Wait for market open or manually trigger a scan.

**Severity:** 🟡 **MEDIUM** (expected behavior, not a bug, but confusing)

---

### 10. **Watchdog False Alarms (Heartbeat Staleness)**
**Scenario:** Scan takes longer than 45 minutes (e.g., Alpaca API slow, network timeout)  
**Where:** `railway_watchdog.py` checks `time.time() - heartbeat_ts > 45*60`  
**What breaks:**
- Watchdog sends Telegram alert "Scan hasn't run in 45 minutes"
- But scan is actually running, just slow
- False alarm spam

**Safety net:** None. Watchdog doesn't know if scan is running or crashed.

**Recovery:** Increase heartbeat staleness threshold or add "scan in progress" state.

**Severity:** 🟡 **MEDIUM** (annoyance, not critical)

---

## HIGH SEVERITY FAILURE MODES (Manual Intervention Needed)

### 11. **Alpaca API Rate Limit (429 Responses)**
**Scenario:** Too many API calls in short period (e.g., 9 experiments × 18 scans/day = 162 calls/day minimum)  
**Where:** `strategy/alpaca_provider.py` handles 429 with retry  
**What breaks:**
- Alpaca returns 429 Too Many Requests
- `alpaca_provider.py` sleeps 30 seconds (or reads `Retry-After` header)
- If sustained rate limiting = all scans delayed
- Execution blocked until rate limit window resets

**Safety net:** Exponential backoff with max 3 retries. After 3 retries, raises exception.

**Recovery:** Reduce scan frequency or stagger experiments.

**Severity:** 🟠 **HIGH**

---

### 12. **Alpaca API Down (Network Error)**
**Scenario:** Alpaca's API is unreachable (DNS failure, network partition, Alpaca outage)  
**Where:** Any Alpaca API call in `alpaca_provider.py`  
**What breaks:**
- `requests` library raises `ConnectionError` or `Timeout`
- Scan fails, no orders submitted
- PositionMonitor can't check positions
- System logs error and continues (next scan retries)

**Safety net:** Circuit breaker in `alpaca_provider.py` opens after 5 consecutive failures (blocks all API calls for 60 seconds).

**Recovery:** Wait for Alpaca to recover or network to restore.

**Severity:** 🟠 **HIGH**

---

### 13. **Database Corruption (SQLite File Damage)**
**Scenario:** Disk failure, incomplete write, Railway container crash mid-write  
**Where:** Any SQLite operation in `shared/database.py`  
**What breaks:**
- SQLite raises `sqlite3.DatabaseError: database disk image is malformed`
- All reads/writes fail
- Subprocess crashes on next DB operation

**Safety net:** WAL mode reduces corruption risk. But if corrupted, no automatic recovery.

**Recovery:** Restore from backup or rebuild database from Alpaca reconciliation.

**Severity:** 🟠 **HIGH**

---

### 14. **Orphaned Positions (No DB Record)**
**Scenario:** Order filled on Alpaca but system crashed before writing to DB  
**Where:** `execution_engine.py` writes DB record BEFORE submitting order (crash-safe design)  
**What breaks:**
- If crash happens AFTER Alpaca fill but BEFORE updating record to "open":
  - Position exists on Alpaca
  - DB shows "pending_open" forever
  - PositionMonitor won't manage it (thinks it's still pending)

**Safety net:** Daily orphan detection in `position_monitor.py` Tier 3 EOD scan. Creates synthetic record.

**Recovery:** Orphan detection runs daily at 4:15 PM. Worst case: 24-hour delay before management starts.

**Severity:** 🟠 **HIGH**

---

### 15. **Telegram Bot Token Invalid**
**Scenario:** `TELEGRAM_BOT_TOKEN` env var wrong or bot deleted  
**Where:** Telegram alert sending in multiple places  
**What breaks:**
- HTTP 401 Unauthorized from Telegram API
- Alert fails silently (logged but not sent)
- Carlos doesn't receive alerts

**Safety net:** None. Code logs error but continues.

**Recovery:** Fix token, redeploy. Alerts lost in the meantime.

**Severity:** 🟡 **MEDIUM**

---

### 16. **SIGTERM Not Handled (Dirty Shutdown)**
**Scenario:** Railway deploys new version, sends SIGTERM to old container  
**Where:** `railway_worker.py` line 296 `signal.signal(signal.SIGTERM, ...)`  
**What breaks:**
- If SIGTERM handler not registered = abrupt kill
- Subprocesses killed mid-scan
- Pending DB writes lost (if not using WAL)
- Positions may be left in inconsistent state

**Safety net:** SIGTERM handler exists, forwards to all subprocesses, waits 10 seconds for clean exit.

**Recovery:** Startup reconciliation should recover state from Alpaca.

**Severity:** 🟡 **MEDIUM** (safety net exists)

---

### 17. **Experiment Config Mismatch (Backtest vs Live)**
**Scenario:** Config file modified after backtest (e.g., DTE changed from 15 to 30)  
**Where:** `main.py` loads config, no validation against backtest baseline  
**What breaks:**
- System trades with different parameters than backtest
- Performance diverges from expectations
- Not caught until post-trade analysis

**Safety net:** None. No runtime validation of config vs backtest.

**Recovery:** Manual config audit. Add config hash validation.

**Severity:** 🟠 **HIGH** (silent strategy drift)

---

## MEDIUM SEVERITY FAILURE MODES (Degraded Operation)

### 18. **Yahoo Finance Data Unavailable**
**Scenario:** Yahoo Finance API down or rate limited  
**Where:** `shared/data_cache.py` fetches price history  
**What breaks:**
- Scan can't get 2-year price history for SPY
- Technical analysis (MA, RSI) fails
- Scan returns zero opportunities

**Safety net:** DataCache has retry logic. After 3 failures, raises exception, scan aborts.

**Recovery:** Wait for Yahoo Finance to recover, next scan retries.

**Severity:** 🟡 **MEDIUM**

---

### 19. **Options Chain Empty (No Strikes Available)**
**Scenario:** Alpaca returns empty options chain (weekend, holiday, data glitch)  
**Where:** Strike selection in `strategy/spread_strategy.py`  
**What breaks:**
- No strikes found matching criteria
- Signal generation returns empty list
- No trades submitted (expected behavior)

**Safety net:** Code handles empty chain gracefully, logs warning, continues.

**Recovery:** Next scan retries. If persistent, investigate Alpaca data.

**Severity:** 🟢 **LOW** (expected in some cases)

---

### 20. **Regime Detection Returns None**
**Scenario:** VIX data missing or MA calculation fails  
**Where:** `strategy/technical_analyzer.py` ComboRegimeDetector  
**What breaks:**
- `detect_regime()` returns `None`
- If combo mode active: `if regime is None: return []` (hard block, no entries)
- Scan completes but zero trades

**Safety net:** Intentional hard block (documented in architecture). Missing regime = don't trade.

**Recovery:** Fix data source, next scan retries.

**Severity:** 🟡 **MEDIUM** (safety feature, not a bug)

---

## Summary by Severity

**CRITICAL (10):** System cannot trade, immediate action required  
**HIGH (7):** Trading broken, manual intervention needed  
**MEDIUM (3):** Degraded operation, recoverable  
**LOW (0):** Minor issues

**Total immediate failure modes identified: 20**

**Status:** CC sessions working on detailed code-level audit. Results in 20-40 minutes.

---

**Carlos — these are just what I can see without diving deep into code. CC sessions will find MORE.**
