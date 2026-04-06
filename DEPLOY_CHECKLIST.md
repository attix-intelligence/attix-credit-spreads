# EXP-1220 Deployment Checklist

**For:** Charles (Mac Studio operator)
**Experiment:** EXP-1220 Credit Spread 1.5× Static Leverage, SPY
**Paper Account:** PA3YFVQCXTD6 (Alpaca)
**Branch:** `maximus/clean-features`
**Validated:** CAGR 99.2%, Sharpe 3.83, Max DD 11.2% (commit dcf617c)

> **⛔ RULE ZERO:** This strategy uses REAL market data only. IronVault
> options_cache.db + Yahoo Finance VIX/SPY + Alpaca live quotes. No synthetic
> data. No np.random. Any deviation = FAIL.

---

## Deployment Package Contents

After you `git pull` on branch `maximus/clean-features`, these files must exist:

```
pilotai-credit-spreads/
├── scripts/
│   ├── run_exp1220.py                 ← the scanner (1,010 lines)
│   └── launch_exp1220.sh              ← one-command launcher (NEW)
├── configs/
│   └── deploy_exp1220_1.5x.yaml       ← strategy config
├── deploy/
│   ├── com.pilotai.exp1220.plist      ← macOS LaunchAgent
│   └── README_launchagent.md          ← LaunchAgent install guide
├── tests/
│   └── test_run_exp1220.py            ← 53 tests, all passing
├── .env.exp1220.example               ← env template (NEW)
└── DEPLOY_CHECKLIST.md                ← this file
```

Verify with:
```bash
git checkout maximus/clean-features
git pull
ls scripts/run_exp1220.py scripts/launch_exp1220.sh configs/deploy_exp1220_1.5x.yaml \
   deploy/com.pilotai.exp1220.plist .env.exp1220.example DEPLOY_CHECKLIST.md
```

---

## Phase 0 — Prerequisites (One-Time Setup)

### 0.1 — Mac Studio ready
- [ ] Mac Studio is powered on and connected to internet
- [ ] Admin access to terminal
- [ ] System timezone is `America/New_York` (verify with `date`)
- [ ] Mac does NOT sleep at 09:35 ET (System Settings → Displays → Never)
  - Alternative: `sudo pmset repeat wakeorpoweron MTWRF 09:30:00`

### 0.2 — Repo checkout
```bash
cd ~/pilotai  # or wherever your checkout lives
git fetch origin
git checkout maximus/clean-features
git pull
git log --oneline -5  # confirm latest commit
```

### 0.3 — Python environment
```bash
python3 --version  # must be >= 3.9
pip3 install pyyaml alpaca-py
```

Required packages for EXP-1220:
- `pyyaml` — config loader
- `alpaca-py` — Alpaca SDK (only for live scans, not dry-run)

Yahoo Finance VIX/SPY fetch uses stdlib `urllib`, no extra package needed.

### 0.4 — Alpaca paper account
1. Log in to https://app.alpaca.markets/paper/dashboard/overview
2. Confirm account ID is **PA3YFVQCXTD6**
3. Starting equity should be $100,000
4. Click **API Keys** → **View** → copy both:
   - `ALPACA_API_KEY` (publishable key)
   - `ALPACA_SECRET_KEY` (secret key)

---

## Phase 1 — Configuration

### 1.1 — Create `.env` from template
```bash
cd ~/pilotai  # or your actual checkout path
cp .env.exp1220.example .env
```

### 1.2 — Edit `.env` and paste real keys
```bash
nano .env
# or: vim .env
```

Required fields:
```
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxxxxxx
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ALPACA_BASE_URL=https://paper-api.alpaca.markets
EXPERIMENT_ID=EXP-1220
PAPER_ACCOUNT=PA3YFVQCXTD6
```

Optional (for alerts):
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Protect the file:
```bash
chmod 600 .env
```

### 1.3 — Verify config file exists
```bash
cat configs/deploy_exp1220_1.5x.yaml | head -15
```
Should show: "EXP-1220 Paper Trading — 1.5× Static Leverage"

---

## Phase 2 — Pre-Launch Validation

### 2.1 — Run smoke test (no trades)
```bash
./scripts/launch_exp1220.sh smoke
```

Expected output:
```
[1/6] Loading config...              OK
[2/6] Checking state file...         OK
[3/6] Checking log directory...      OK
[4/6] Fetching VIX from Yahoo...     OK
[5/6] Fetching SPY from Yahoo...     OK
[6/6] Checking Alpaca connectivity... OK  Alpaca account status: ACTIVE
                                            Equity: $100,000.00

  SMOKE TEST PASSED — All 6 checks OK
```

**STOP if any check fails.** Most common failures:
- `alpaca-py not installed` → `pip3 install alpaca-py`
- `Alpaca credentials not set` → fix `.env` and re-source it
- `SPY fetch failed` → network issue, retry

### 2.2 — Run dry-run scan (mock data, no orders)
```bash
./scripts/launch_exp1220.sh dry
```

Expected: Scanner fetches SPY/VIX, picks strikes, shows proposed trade. Orders NOT submitted.

### 2.3 — Run unit tests (optional but recommended)
```bash
python3 -m pytest tests/test_run_exp1220.py -q
```
Expected: **53 passed**

### 2.4 — Verify paper account connectivity
```bash
./scripts/launch_exp1220.sh status
```
Should show: `Open positions: 0` (fresh deployment).

---

## Phase 3 — Manual Paper Trading (Week 1)

### 3.1 — First manual live scan
```bash
./scripts/launch_exp1220.sh scan
```

This submits REAL orders to your paper account. You should see:
```
Market data: SPY=$xxx.xx, VIX=xx.x
Target expiration: 2026-05-xx
Spread: SELL xxxP / BUY xxxP ($5 wide)
Credit: $x.xx
Sizing: x contracts, max loss $xxx
Submitting: SELL SPYxxxxxPxxxxxxxx / BUY SPYxxxxxPxxxxxxxx × x @ $x.xx
Short leg submitted: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Long leg submitted:  xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Position opened: xxx/xxx × x exp 2026-05-xx
```

### 3.2 — Verify in Alpaca dashboard
1. Open https://app.alpaca.markets/paper/dashboard/positions
2. Should see TWO positions:
   - SHORT SPY xxx Put (negative qty)
   - LONG SPY xxx Put (positive qty)
3. Net impact: credit received

### 3.3 — Check logs and state
```bash
tail -20 logs/exp1220.log
cat logs/exp1220_state.json | python3 -m json.tool
cat logs/exp1220_health.json
```

### 3.4 — Daily sanity check
Every weekday after market open:
```bash
./scripts/launch_exp1220.sh status
./scripts/launch_exp1220.sh health
```

---

## Phase 4 — Automated Scheduler (Week 2+)

Only enable after 3-5 successful manual scans.

### 4.1 — Edit plist for your actual path
```bash
# If your checkout is NOT at /Users/charles/pilotai, edit the plist:
sed -i '' "s|/Users/charles/pilotai|$(pwd)|g" deploy/com.pilotai.exp1220.plist
```

### 4.2 — Install LaunchAgent
```bash
./scripts/launch_exp1220.sh install
```

This copies the plist, loads it via `launchctl`, and confirms registration.

### 4.3 — Verify installation
```bash
launchctl list | grep pilotai
```
Should show: `com.pilotai.exp1220` with PID or `-`.

### 4.4 — Test manual trigger (bypass schedule)
```bash
launchctl start com.pilotai.exp1220
sleep 5
tail -20 logs/exp1220.log
```

### 4.5 — Confirm the schedule
The LaunchAgent runs **Monday-Friday at 09:35 ET**.
The scanner itself only ENTERS new trades on Mondays (config: `scan_day: monday`).
It checks exits every day and enters new positions only on Mondays.

---

## Phase 5 — Monitoring (Ongoing)

### 5.1 — Daily health check
```bash
./scripts/launch_exp1220.sh health
```
Exit codes: 0=OK, 1=warning (stale >48h), 2=error

### 5.2 — Weekly position review
```bash
./scripts/launch_exp1220.sh status
cat logs/trade_journal.csv | tail -20
```

### 5.3 — Log review
```bash
./scripts/launch_exp1220.sh logs   # tail -f
# or:
tail -50 logs/exp1220.log
```

### 5.4 — LaunchAgent logs
```bash
tail logs/exp1220_launchd.out.log
tail logs/exp1220_launchd.err.log
```

### 5.5 — Metrics to watch
| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Open positions | 0-5 | 6-7 | ≥8 |
| Weekly P&L | > -2% | -2% to -5% | < -5% |
| Total DD | < 5% | 5-10% | ≥10% (auto-halt) |
| Health status | `ok` | `warning` | `error` |
| Days since last run | 0-1 | 2-3 | ≥4 |

---

## Phase 6 — Emergency Procedures

### Kill switch — close everything
```bash
./scripts/launch_exp1220.sh close-all
```
Prompts for confirmation. Submits BTC (short) + STC (long) for every open position.

### Disable the scheduler
```bash
launchctl unload ~/Library/LaunchAgents/com.pilotai.exp1220.plist
```

### Uninstall completely
```bash
./scripts/launch_exp1220.sh uninstall
```

### Scanner won't run
```bash
# Check for errors
cat logs/exp1220_launchd.err.log
cat logs/exp1220_health.json

# Re-run smoke test to diagnose
./scripts/launch_exp1220.sh smoke
```

### Alpaca API errors
```bash
# Verify keys are loaded
env | grep ALPACA  # should show 3 entries after `source .env`

# Check account status
python3 -c "
import os
from alpaca.trading.client import TradingClient
tc = TradingClient(os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'], paper=True)
a = tc.get_account()
print('Status:', a.status, 'Equity:', a.equity, 'ID:', a.account_number)
"
# Should print: Status: ACTIVE, Equity: 100000.00, ID: PA3YFVQCXTD6
```

### Stale state / orphan positions
```bash
# View state
cat logs/exp1220_state.json | python3 -m json.tool

# Reconcile with broker (manual)
./scripts/launch_exp1220.sh status  # local state
# Compare with https://app.alpaca.markets/paper/dashboard/positions
```

---

## Success Criteria (Week 8 Review — 2026-06-01)

After 8 weeks of paper trading:

| Metric | Target | Stretch |
|--------|--------|---------|
| Weeks with entries | ≥6 of 8 | 8/8 |
| Total trades placed | ≥6 | ≥10 |
| Orders filled | ≥95% | 100% |
| Max DD | ≤11.2% | ≤7% |
| Annualized return | ≥50% | ≥80% |
| Health errors | 0 | 0 |
| Scanner failures | 0 | 0 |

**Decision point:** If all criteria met → promote to live trading with real capital.

---

## Key File Locations

| File | Purpose |
|------|---------|
| `scripts/run_exp1220.py` | Main scanner |
| `scripts/launch_exp1220.sh` | One-command launcher |
| `configs/deploy_exp1220_1.5x.yaml` | Strategy config |
| `deploy/com.pilotai.exp1220.plist` | macOS LaunchAgent |
| `deploy/README_launchagent.md` | Detailed install guide |
| `.env` | Credentials (YOU create this) |
| `.env.exp1220.example` | Template |
| `logs/exp1220.log` | Scanner log (rotating) |
| `logs/exp1220_state.json` | Open position state |
| `logs/exp1220_health.json` | Health status |
| `logs/trade_journal.csv` | Every trade logged |
| `logs/exp1220_launchd.out.log` | LaunchAgent stdout |
| `logs/exp1220_launchd.err.log` | LaunchAgent stderr |

---

## Quick Reference — Most Common Commands

```bash
# Smoke test (no trades)
./scripts/launch_exp1220.sh smoke

# Dry run scan (no submissions)
./scripts/launch_exp1220.sh dry

# Live paper scan
./scripts/launch_exp1220.sh scan

# Show positions
./scripts/launch_exp1220.sh status

# Close all positions (emergency)
./scripts/launch_exp1220.sh close-all

# Health check
./scripts/launch_exp1220.sh health

# Install LaunchAgent
./scripts/launch_exp1220.sh install

# Uninstall LaunchAgent
./scripts/launch_exp1220.sh uninstall

# Tail logs
./scripts/launch_exp1220.sh logs
```

---

## Contacts & Escalation

- **Operator:** Charles (this machine)
- **Owner:** Carlos
- **Strategist:** Maximus (commit authorship, branch `maximus/clean-features`)

For questions or issues, check:
1. `logs/exp1220_health.json` — current status
2. `logs/exp1220.log` — recent scanner runs
3. This checklist — troubleshooting section above
4. `deploy/README_launchagent.md` — LaunchAgent specifics

---

*Deployment package validated: 2026-04-06*
*Scanner version: 1.0.0*
*Config version: 1.0.0*
