# 🔴 SKEPTICAL AUDIT — May 24, 2026

**ASSUMPTION: The system WILL FAIL on Monday market open unless we find and fix everything wrong.**

## Audit Started: 2026-05-24 11:35 UTC
## Target: Complete before Monday May 26 market open (13:30 UTC)

---

## 🎯 Success Criteria
- **All experiments execute trades on Monday without hickups**
- **All experiments match their respective backtesting environment EXACTLY**
- **Every potential failure mode identified and mitigated**

---

## 🔍 Independent CC Session Audits

### CC1: End-to-End Trade Execution Path
**Status:** IN PROGRESS
**Scope:** Alpaca integration, order routing, fill handling, position reconciliation
**Critical Questions:**
- Will orders actually execute on Monday?
- Will fills get recorded correctly?
- What happens when Alpaca rejects an order?
- Are we handling partial fills?
- Does position reconciliation match Alpaca's view?

**Files to audit:**
- `pilots/alpaca_driver.py`
- `pilots/order_manager.py`
- `pilots/reconciler.py`
- Railway env vars

**Red Flags to Find:**
- Hardcoded test values
- Missing error handlers
- Untested edge cases
- API auth failures
- No retry logic

---

### CC2: Backtest vs Live Environment Match
**Status:** IN PROGRESS
**Scope:** Experiment definitions, entry/exit logic, sizing, vol targeting
**Critical Questions:**
- Do experiments replicate EXACTLY what was backtested?
- Are there hidden differences between backtest and live?
- Are entry filters (NFP calendar, regime gates) active?
- Is position sizing formula identical?
- Are exit rules the same?

**Files to audit:**
- `experiments/*.yaml` configs
- `compass/exp3311*.py` (NFP filter)
- `compass/exp3312*.py` (combined)
- `compass/exp3309*.py` (pre-close execution)
- Entry/exit logic in live vs backtest code

**Red Flags to Find:**
- Commented-out filters
- Different vol targets (backtest: 12%, live: ???)
- Missing position limits
- Different entry/exit timing
- Calendar not loading

---

### CC3: Data Pipeline & Market Data
**Status:** IN PROGRESS
**Scope:** IronVault integration, Yahoo Finance fallback, data freshness, missing data handling
**Critical Questions:**
- Will we have clean option chains Monday morning?
- What breaks if data is stale?
- Do we handle missing strikes gracefully?
- Are API rate limits enforced?
- Is the database accessible on Railway?

**Files to audit:**
- `pilots/data_manager.py`
- `pilots/ironvault_client.py`
- `data/options_cache.db` (integrity check)
- Cache invalidation logic
- Yahoo Finance fallback

**Red Flags to Find:**
- Cached data from weeks ago
- No staleness checks
- Missing underliers (SPY/QQQ/XLF/XLI/GLD/SLV)
- Rate limit violations
- Database not synced to Railway

---

### CC4: Railway Deployment & Infrastructure
**Status:** IN PROGRESS
**Scope:** Railway config, env vars, cron jobs, logging, monitoring, restart policies
**Critical Questions:**
- Is the Railway app actually running?
- Will it survive a crash?
- How do we know if it's healthy?
- Are scanners scheduled correctly?
- Where do logs go?

**Files to audit:**
- `railway.toml`
- `Procfile`
- Environment variables
- Health check endpoints
- Watchdog process
- Scanner scheduling (LaunchAgents on Mac Studio vs Railway)

**Red Flags to Find:**
- No health endpoint
- Missing restart policy
- Hardcoded localhost URLs
- Missing env vars
- Watchdog not running
- Scanner conflicts between local and Railway

---

### CC5: Risk Management & Position Limits
**Status:** IN PROGRESS
**Scope:** Portfolio-level risk, per-stream limits, margin requirements, kill switches
**Critical Questions:**
- What stops us from blowing up the account?
- Are position limits enforced?
- Is 12% vol target enforced?
- Do we have margin buffer?
- Is there an emergency stop mechanism?

**Files to audit:**
- `pilots/risk_manager.py`
- Portfolio vol targeting
- Per-stream position caps
- Margin calculations
- Max notional limits

**Red Flags to Find:**
- Unenforced limits
- Missing margin checks
- No emergency stop
- Vol target not implemented
- Position limits don't match backtest

---

## 📋 Deliverables (Per Session)

Each CC session must produce:

1. **FINDINGS.md** — every issue found, severity rating (CRITICAL/HIGH/MEDIUM/LOW)
2. **FIXES.md** — proposed fixes for each issue
3. **VERIFICATION.md** — how to verify the fix works
4. **GO/NO-GO** — final verdict: safe to trade Monday or block deployment

---

## 🚨 Escalation Rules

**CRITICAL issues (immediate escalation to Carlos):**
- API keys missing or invalid
- Database not accessible
- Experiments don't match backtest environment
- No position limits enforced
- Order execution path broken

**HIGH issues (fix before Monday):**
- Missing error handlers
- Stale data not detected
- Watchdog not running
- Missing health checks
- Partial fill handling broken

**MEDIUM issues (fix this week):**
- Logging incomplete
- No retry logic
- Performance bottlenecks

**LOW issues (backlog):**
- Code style
- Documentation gaps

---

## Timeline

- **May 24 11:35 - 18:00 UTC:** Initial audits (all 5 sessions)
- **May 24 18:00 - 24:00 UTC:** Fix CRITICAL and HIGH issues
- **May 25 00:00 - 12:00 UTC:** Verification testing
- **May 25 12:00 UTC:** GO/NO-GO decision
- **May 26 13:30 UTC:** Market open (if GO)

---

## Current Status

- **CC1:** Auditing Alpaca integration
- **CC2:** Auditing experiment definitions
- **CC3:** Auditing data pipeline
- **CC4:** Auditing Railway deployment
- **CC5:** Auditing risk management

---

**Maximus tracking this audit. Updates every 30 minutes.**
