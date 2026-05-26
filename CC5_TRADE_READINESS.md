# CC5 — Trade Readiness Audit (CAN THE SYSTEM ACTUALLY TRADE?)

**Date:** 2026-05-24
**Auditor:** Maximus
**Scope:** End-to-end trade execution path — Alpaca, trading loop, scanners, deployment, smoke test
**Verdict:** 🔴 **NO-GO for Monday 2026-05-26 market open.**

Only 2 of 6 active experiments (EXP-400, EXP-401) have the full configuration required to place a real paper order. Railway runs only the dashboard UI — no scheduler, no scanner, no trading loop. All other "active" experiments are missing env files, plists, or both, and the most recent log activity is either 58 days stale (paper_exp401) or DRY-RUN with synthetic data (exp1220).

---

## 1. Alpaca Integration

| Check | Result |
|---|---|
| EXP-400 paper account reachable (PA3ZSXZ5JNEM) | ✅ equity $110,382.80, BP $220,765.60, opts_lvl 3, ACTIVE |
| EXP-401 paper account reachable (PA3IPY4E4KPA) | ✅ equity $118,885.49, BP $237,770.98, opts_lvl 3, ACTIVE |
| EXP-503 paper account credentials present | ❌ `.env.exp503` does not exist |
| EXP-600 paper account credentials present | ❌ `.env.exp600` does not exist |
| EXP-800 paper account credentials present | ❌ `.env.exp800` does not exist (only `.env.exp880.example`) |
| EXP-1220 paper account credentials present | ❌ only `.env.exp1220.example` exists; plist expects `.env` at repo root |
| Alpaca SDK installed and importable | ✅ `alpaca-py` declared in requirements |

**Verdict:** ⚠️ Partial — only EXP-400 and EXP-401 have working Alpaca credentials on disk.

---

## 2. Trading Loop (`main.py` / `scheduler/main.py`)

| Check | Result |
|---|---|
| `main.py scheduler` entry point exists | ✅ modes: scan / scheduler / backtest / dashboard / alerts |
| `scheduler/main.py` APScheduler service exists | ✅ jobs: pre_market_check 08:00, signal_generator 09:25, circuit_breaker_check every 30 min, etc. |
| Scheduler reachable from any deployment target | ❌ Not invoked by Railway Procfile. Charles plists invoke `main.py scheduler` locally — but only EXP-400 and EXP-401 plists have valid env files. |
| `PortfolioRiskMonitor.check()` called anywhere in live path | ❌ Zero call sites (see CC5_FINDINGS.md CRIT-1) |
| `monitor.allow_entry()` gates order submission | ❌ Not wired |
| Per-experiment kill switch reachable | ⚠️ Only via `sentinel_state.json` (six separate edits required) |

**Verdict:** ❌ The trading loop *exists* but is not invoked in any deployed environment with a complete configuration.

---

## 3. Scanners & Scheduling

### Railway (`Procfile`)
```
web: uvicorn web_dashboard.app:app --host 0.0.0.0 --port $PORT
```
**Smoking gun.** Railway runs ONLY the dashboard. No `main.py scheduler`. No cron. No scanners.

### Charles's Mac Studio LaunchAgents (`deploy/*.plist`)

| Experiment | Plist | Cmd | Env file required | Env file exists | Working Directory | Status |
|---|---|---|---|---|---|---|
| EXP-400 | `com.pilotai.exp400.plist` | `main.py scheduler --config configs/paper_champion.yaml --env-file .env.champion` | `.env.champion` | ✅ | `/Users/charlesbot/projects/pilotai-credit-spreads` | Plist OK |
| EXP-401 | `com.pilotai.exp401.plist` | `main.py scheduler --config configs/paper_exp401.yaml --env-file .env.exp401` | `.env.exp401` | ✅ | `/Users/charlesbot/projects/pilotai-credit-spreads` | Plist OK |
| EXP-503 | `com.pilotai.exp503.plist` | `main.py scheduler --config configs/paper_exp503.yaml --env-file .env.exp503` | `.env.exp503` | ❌ MISSING | `/Users/charlesbot/projects/pilotai-credit-spreads` | Will crash on startup |
| EXP-600 | `com.pilotai.exp600.plist` | `main.py scheduler --config configs/paper_exp600.yaml --env-file .env.exp600` | `.env.exp600` | ❌ MISSING | `/Users/charlesbot/projects/pilotai-credit-spreads` | Will crash on startup |
| EXP-800 | **NO PLIST** | — | — | — | — | ❌ No scheduling mechanism |
| EXP-1220 | `com.pilotai.exp1220.plist` | `bash -lc 'source .env && python3 scripts/run_exp1220.py'` (Mon–Fri 09:35 ET) | `.env` at repo root | ❌ MISSING | `/Users/charles/pilotai` — **different home dir from the others** | Will crash; path likely wrong |

Notable inconsistencies:
- The 4 newer plists (400/401/503/600) point to `/Users/charlesbot/projects/pilotai-credit-spreads`, the exp1220 plist points to `/Users/charles/pilotai`. Both cannot be correct on a single Mac — at least one set is a template that has not been updated, and either the long-running or the cron set will fail.
- exp400/401/503/600 use `KeepAlive=true` (the scanner is expected to be a long-running process); exp1220 uses `StartCalendarInterval` (one shot at 09:35 ET) — these are two incompatible deployment models running side by side.

### Recent log activity (proves whether scanners *actually* execute)
| Log | Last mtime | Content |
|---|---|---|
| `logs/exp1220.log` | 2026-05-24 00:47 | DRY-RUN; `ALPACA_API_KEY ... must be set`; synthetic `SPY=$540.00 VIX=40.0` test data |
| `logs/paper_exp401.log` | 2026-03-27 18:55 | 58 days stale, full of "ORPHAN POSITION ... Manual review required" warnings |
| `logs/paper_exp1220_3x.log` | 2026-04-06 13:46 | 0 bytes |
| `logs/paper_exp1220_5x.log` | 2026-04-06 13:46 | 592 bytes |
| `logs/combined_portfolio.log` | 2026-04-06 12:17 | stale |
| `logs/exp400.log` | n/a | does not exist |
| `logs/exp503.log` | n/a | does not exist |
| `logs/exp600.log` | n/a | does not exist |
| `logs/exp800.log` | n/a | does not exist |

**Verdict:** ❌ There is **no evidence any active experiment has placed a real paper order in 2026-Q2.** Last live activity is 58 days old, and even that ended with 16 orphan positions never reconciled.

---

## 4. Deployment Infrastructure

| Check | Result |
|---|---|
| Railway running scheduler | ❌ Procfile only runs dashboard |
| Railway has `ALPACA_API_KEY` env var | ❓ Cannot verify from this environment — Atlas owns Railway access |
| Mac Studio LaunchAgents installed and `launchctl load`ed | ❓ Cannot verify remotely — needs Charles to run `launchctl list \| grep pilotai` |
| Health endpoint reachable | ⚠️ exp1220 health JSON path defined but other experiments have no health check |
| Watchdog process | ❌ Not present in any deployed surface |
| Per-experiment restart policy | ✅ in plists (`KeepAlive=true`, throttle 10 s) — but only for 400/401/503/600 |
| Where do logs go? | Mac: `/Users/charlesbot/logs/*.log` and `/Users/charles/pilotai/logs/*.log` — two different roots, see inconsistency above |

**Verdict:** ❌ Railway deployment is not running anything that trades. Mac Studio status unverifiable from CC5; on-disk artefacts suggest only EXP-400/EXP-401 could execute even if loaded.

---

## 5. End-to-End Smoke Test

| Check | Result |
|---|---|
| Can EXP-400 connect to Alpaca? | ✅ verified live by CC5 |
| Can EXP-401 connect to Alpaca? | ✅ verified live by CC5 |
| Can EXP-503/600/800/1220 connect? | ❌ no credentials on disk |
| Can `main.py scheduler --config configs/paper_champion.yaml --env-file .env.champion` start without crashing? | ⚠️ Not run in this audit. All required files are present, so this is the highest-likelihood path. Recommend Charles run on the Mac Studio before Monday open. |
| Can scanner place a real paper order? | ❌ Last evidence of a real order is 2026-03-27 (orphans). No 2026-Q2 placements observed. |

**Verdict:** ❌ No end-to-end execution has been demonstrated in the audit window.

---

## Summary of Gaps

| Gap | Severity | Owner |
|---|---|---|
| Railway Procfile does not run the trading loop | 🚨 CRITICAL | Atlas (Railway) — needs second service or replaced Procfile |
| `.env.exp503`, `.env.exp600`, `.env.exp800` missing | 🚨 CRITICAL | Carlos / Charles — paper accounts must be provisioned or experiments paused |
| EXP-800 has no LaunchAgent plist at all | 🚨 CRITICAL | Charles / deployment owner |
| `.env.exp1220` missing (only `.example`); plist sources `.env` not `.env.exp1220` | 🚨 CRITICAL | Charles |
| Mac home-directory mismatch between exp1220 (`/Users/charles/pilotai`) and exp400/401/503/600 (`/Users/charlesbot/projects/...`) | 🚨 CRITICAL | Charles — at least one set will fail to load |
| No portfolio-level kill switch or risk gate in live path (see CC5_FINDINGS.md) | 🚨 CRITICAL | Engineering |
| Last successful live scan was 2026-03-27, with 16 unreconciled orphans | HIGH | Charles / Carlos |
| Two incompatible deployment models in `deploy/` (KeepAlive long-running vs cron one-shot) | HIGH | Engineering — pick one |
| No verified health endpoint or watchdog | HIGH | Engineering |

---

## GO / NO-GO for Monday 2026-05-26

🔴 **NO-GO.**

**Minimum conditions to unblock:**
1. Decide deployment target: Railway scheduler service OR Charles Mac Studio. Currently neither is fully wired.
2. Provision `.env.exp503`, `.env.exp600`, `.env.exp800`, `.env.exp1220` (real keys, not examples) — or pause those experiments in `sentinel_state.json`.
3. Reconcile home-directory mismatch in plists; pick `/Users/charlesbot/projects/pilotai-credit-spreads` OR `/Users/charles/pilotai` and update all plists.
4. Add LaunchAgent plist for EXP-800 (or pause EXP-800).
5. Run `main.py scheduler --config configs/paper_champion.yaml --env-file .env.champion` on Charles's Mac and confirm a clean startup line in `logs/exp400.log` before 13:30 UTC Monday.
6. Wire `PortfolioRiskMonitor.allow_entry()` into `entry_gate.py` or `order_router.py` (see CC5_FINDINGS.md CRIT-1).

**Acceptable fall-back posture:** disable EXP-503, EXP-600, EXP-800, EXP-1220 in `sentinel_state.json`; run only EXP-400 and EXP-401 from the Mac Studio after confirming local startup. This gives a 2-experiment paper-trading restart with the only complete configuration on disk.
