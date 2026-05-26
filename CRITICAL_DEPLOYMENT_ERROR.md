# 🚨 CRITICAL DEPLOYMENT ERROR — May 24, 2026 12:02 UTC

## Carlos: "System needs to fully run from Railway. Nothing from Mac Studio."

---

## THE PROBLEM

**Current architecture is WRONG:**

1. **Procfile runs ONLY web dashboard:**
   ```
   web: uvicorn web_dashboard.app:app --host 0.0.0.0 --port $PORT
   ```

2. **No trading loop on Railway**
   - No main.py execution
   - No scanners scheduled
   - No watchdog running
   - No orders being submitted

3. **LaunchAgents on Mac Studio = WRONG ARCHITECTURE**
   - All trading execution was designed for local Mac
   - Deploy directory full of .plist files for macOS
   - System CANNOT run from Railway in current state

---

## ROOT CAUSE

**The system was designed for local execution, not cloud deployment.**

Evidence:
- `deploy/` directory contains macOS LaunchAgent .plist files
- `Procfile` only runs web UI
- No Railway cron/worker configuration
- No scheduler for scanners on Railway
- Database path hardcoded to local filesystem

---

## WHAT NEEDS TO HAPPEN

**Railway must run the ENTIRE trading system:**

1. **Scanners must execute on schedule** (Mon-Fri 9:35 AM ET or continuous)
2. **Watchdog must run** (monitor positions, reconcile, risk management)
3. **Database must be Railway-accessible** (not local Mac filesystem)
4. **Logs must go to Railway** (not local Mac ~/pilotai/logs/)
5. **Web dashboard can continue** (already working)

---

## DEPLOYMENT REQUIREMENTS

### 1. Procfile Needs Multiple Processes

Railway needs to run:
- `web`: Web dashboard (current)
- `scanner`: Trading scanner (NEW)
- `watchdog`: Position monitoring (NEW)

Options:
- **Honcho/Foreman** (run multiple processes from Procfile)
- **Railway services** (separate deployments for web/scanner/watchdog)
- **Cron job addon** (schedule scanners)

### 2. Scheduler Needed

Scanners run Mon-Fri 9:35 AM ET:
- Railway cron plugin?
- Custom scheduler daemon?
- While-loop with sleep?

### 3. Database Migration

Current: `data/pilotai_exp1220.db` (local filesystem)

Options:
- Railway volume mount (persistent storage)
- PostgreSQL (Railway built-in)
- SQLite on Railway volume

### 4. Environment Variables

Need on Railway:
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `POLYGON_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Options Data (options_cache.db)

Current: `data/options_cache.db` (276K contracts, 6.3M option-days)

Must be accessible on Railway:
- Upload to Railway volume?
- Fetch from IronVault API on startup?
- PostgreSQL migration?

---

## IMMEDIATE ACTIONS NEEDED

### CRITICAL (Block Monday Deployment):

1. **Fix Procfile** to run trading scanner
2. **Configure Railway scheduler** for scanner execution
3. **Deploy database** to Railway (volume or PostgreSQL)
4. **Set Railway env vars** (Alpaca keys)
5. **Test end-to-end** order submission from Railway

### HIGH (This Week):

1. Add watchdog process to Railway
2. Migrate logs to Railway
3. Health check endpoint
4. Verify options_cache.db accessible

---

## GO/NO-GO DECISION

**Monday deployment = NO-GO until Railway runs trading engine.**

Current state:
- ❌ Railway does NOT execute trades
- ❌ No scanner running
- ❌ No watchdog running
- ❌ Database is local-only
- ✅ Web dashboard works (but useless without trading)

**Estimated fix time: 4-8 hours** (Procfile changes, Railway config, database migration, testing)

---

## NEXT STEPS

**Option 1: Fix Railway Deployment (Recommended)**
- CC sessions work together to migrate architecture to Railway
- Update Procfile, add scheduler, migrate database
- Test on Railway staging before Monday

**Option 2: Emergency Mac Studio Deployment (Temporary)**
- Load LaunchAgent on Charles's Mac as stopgap
- Continue Railway migration in parallel
- NOT RECOMMENDED per Carlos directive

**Option 3: Delay Monday Deployment**
- Fix architecture properly
- No rushed deployment with wrong infrastructure
- Test thoroughly before go-live

---

**Carlos: Which option? Or different approach?**

**All 5 CC sessions standing by for new mission.**
