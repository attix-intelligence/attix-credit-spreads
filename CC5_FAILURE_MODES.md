# CC5 — MONITORING FAILURE MODES (skeptical audit)

**Date:** 2026-05-24
**Auditor:** Maximus
**Scope:** PositionMonitor, reconciler, watchdog, Telegram alerts, orphan handling
**Mode:** Assume total failure. Find every reason monitoring will not catch a problem.

---

## Executive Summary

🔴 **Monitoring is structurally broken.** The watchdog assumes a tmux-based deployment that is no longer in use (LaunchAgents instead), so it will fire false-positive alerts on every run, attempt unauthorised tmux restarts that conflict with `KeepAlive=true` LaunchAgents (double-run / duplicate-order risk), and silently miss the actual scanner-down condition. PositionMonitor itself starts cleanly but has six failure modes where it stops monitoring positions without alerting the operator. Reconciliation is tolerant of orphans (16 unreconciled from 2026-03-27 still in `logs/paper_exp401.log`).

---

## CRITICAL Failure Modes

### CRIT-M1 — Watchdog assumes tmux; deployment uses LaunchAgents → 100% false-positive alerts + restart conflicts
**Where:** `scripts/watchdog.py:68-80` (`tmux_session_alive`), `scripts/watchdog.py:254-287` (restart block), `deploy/com.pilotai.exp*.plist` (no tmux)
**What breaks:**
- `tmux has-session -t exp400` returns non-zero (no tmux session exists because LaunchAgent runs python3 directly).
- Watchdog logs "DEAD", calls `restart_tmux_session(...)` which does `tmux new-session -d -s exp400 ...` and spawns a SECOND python3 process running `main.py scheduler` while the LaunchAgent's process is still alive (`KeepAlive=true`).
- Result: two scanners → duplicate Alpaca order submissions → duplicate fills → orphaned positions in DB.
- Telegram fires a `WATCHDOG RESTART` alert every cycle for every experiment — operator desensitises and starts ignoring alerts.

**Safety net:** None. Watchdog has no "is there already a python3 running for this experiment" check.
**Recovery:** Manual — kill duplicate processes, audit Alpaca for duplicate fills, reconcile DB. Add a `pgrep -f "main.py scheduler --env-file .env.exp400"` check before restarting, OR replace tmux check with `launchctl list | grep com.pilotai.<id>`.

---

### CRIT-M2 — Watchdog reads `env_file` from registry.json that does not exist on disk → all Alpaca health checks return False
**Where:** `experiments/registry.json:20` (`"env_file": ".env.exp400"`), `scripts/watchdog.py:130-157` (`check_alpaca_api`)
**What breaks:** Watchdog reads `env_file=.env.exp400` from registry, but only `.env.champion`, `.env.exp401` exist on disk. `_parse_env_file()` returns `{}` → `key=None, secret=None` → function returns False without sending the request → "Alpaca API unreachable" alert every cycle for EXP-400, 503, 600, 800, 1220.
**Safety net:** None — Telegram alert is sent every run, but the operator cannot distinguish "API actually down" from "env file missing".
**Recovery:** Either create the missing `.env.exp*` files OR update registry.json to point exp400 → `.env.champion`. (Plist points to `.env.champion`; registry points to `.env.exp400`. Two sources of truth disagree.)

---

### CRIT-M3 — Heartbeat timezone mismatch: writer uses UTC, watchdog assumes ET → ~4-hour false-stale skew
**Where:** `main.py:1102-1120` (`_write_heartbeat` writes `datetime.now(timezone.utc).isoformat()`), `scripts/watchdog.py:289-307` (heartbeat age computation)
**What breaks:**
- Writer: heartbeat file contains `2026-05-24T17:30:00+00:00` (UTC).
- Reader: `datetime.fromisoformat` returns an aware datetime in UTC. Then `(now - hb_ts).total_seconds() / 60` is computed where `now = datetime.now(ET)` with ET = `timezone(timedelta(hours=-4))`. Python correctly aware-subtracts → no skew here, but the code path on line 294 says `if market_open and hb_ts.tzinfo is None: hb_ts = hb_ts.replace(tzinfo=ET)`. So if any caller ever writes a naive timestamp, the watchdog mis-tags it ET and produces a ~4h skew during EDT, ~5h during EST.
- More fundamentally: `ET = timezone(timedelta(hours=-4))` is hardcoded EDT — wrong from November to March (EST is UTC-5). Market hours window misaligned by 1 hour for half the year → false "out of hours" decisions during November–March.

**Safety net:** None — wrong-timezone alerts will fire every winter.
**Recovery:** Use `zoneinfo.ZoneInfo("America/New_York")` for ET, drop the manual offset constant.

---

### CRIT-M4 — Heartbeat file naming derives `exp_id` from db_path basename — fails for plist-launched runs
**Where:** `main.py:1107-1115`
**What breaks:** `_exp_id` is derived from `os.path.basename(args.db_path).replace("pilotai_", "").replace(".db", "")`. For EXP-400 the db_path is `data/pilotai_champion.db` → exp_id becomes `"champion"`, so the heartbeat file is written to `data/.last_scan_champion`. The watchdog iterates `get_manager().live()` which returns experiment IDs like `EXP-400` and looks for `data/.last_scan_EXP-400` → not found → "heartbeat_missing": True → fires alert every cycle.
**Safety net:** None.
**Recovery:** Use the registry `id` for the heartbeat filename, or read `EXPERIMENT_ID` from env.

---

### CRIT-M5 — Watchdog itself has no scheduler in the deployment
**Where:** `scripts/watchdog.py` is a one-shot script; `scripts/watchdog_external.py` says cron-based (`*/30 * * * *`); no cron found in this repo
**What breaks:** Nothing calls the watchdog. Procfile runs only the dashboard. No `crontab`, no Railway scheduled job, no LaunchAgent in `deploy/` for watchdog.py.
**Safety net:** **None.** Monitoring system not deployed.
**Recovery:** Add either (a) a `com.pilotai.watchdog.plist` LaunchAgent on Mac Studio running every 30 min, or (b) a Railway cron service. Note: `scripts/watchdog_external.py` references `TELEGRAM_BOT_TOKEN` as a hardcoded fallback in source — secret in source control (HIGH severity by itself; see also CRIT-M6).

---

### CRIT-M6 — Production Telegram credentials hardcoded in `scripts/watchdog_external.py`
**Where:** `scripts/watchdog_external.py:38-42`
```
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8720867957:AAGrW-Qz0k50P9hRpyF9Bm-zZn_qsbTwIME")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "451136954")
```
**What breaks:** Secret exposed in any clone of the repo. If a malicious party spots it on a public mirror (or already has) they can spam alerts to Carlos's Telegram chat, masking real alerts.
**Safety net:** None.
**Recovery:** Rotate the bot token, remove the fallback default literal, fail loudly when env vars missing. Also present in `.env.champion:7` (production Polygon + Alpaca keys are sitting on disk).

---

## HIGH Failure Modes

### HIGH-M7 — PositionMonitor silently skipped when `alpaca_provider` is None
**Where:** `main.py:1197-1213`
**What breaks:** If env vars are unset or Alpaca SDK fails to init, `system.alpaca_provider` is None → monitor not started → `logger.info("PositionMonitor skipped — no AlpacaProvider configured")` → **NO Telegram alert.** Operator sees scheduler "running" in launchctl but positions are completely unmonitored.
**Safety net:** Only a log line.
**Recovery:** Promote this branch to a CRITICAL Telegram alert and a non-zero exit.

---

### HIGH-M8 — PositionMonitor catches all exceptions in the loop — silent monitoring death
**Where:** `execution/position_monitor.py:243-248`
```
while not self._stop_event.is_set():
    try:
        self._check_positions()
    except Exception as e:
        logger.error("PositionMonitor: unhandled error in check cycle: %s", e, exc_info=True)
    self._stop_event.wait(timeout=_CHECK_INTERVAL_SECONDS)
```
**What breaks:** If every cycle raises (config typo, schema mismatch, IronVault outage, DB lock), the monitor "keeps running" but does nothing useful. There's no consecutive-error counter for *non-API* exceptions and no Telegram alert path.
**Safety net:** Logs only.
**Recovery:** Track consecutive `_check_positions` exceptions and fire `notify_api_failure` after N (e.g. 3) in a row.

---

### HIGH-M9 — `consecutive_api_failures` counter resets on first success → flapping API never triggers the CRITICAL alert
**Where:** `execution/position_monitor.py:467-495`
**What breaks:** Counter increments to ≥3 only with three back-to-back failures. An API that fails every other cycle (rate-limited intermittently) will alternate `1 → 0 → 1 → 0 → …` and never trip the critical branch. Position SL/PT exits are silently skipped on each failed cycle.
**Safety net:** None.
**Recovery:** Use an EWMA / rolling-window failure rate, or alert on cumulative failure count per market session.

---

### HIGH-M10 — Telegram `notify_api_failure` cooldown is per-process global
**Where:** `shared/telegram_alerts.py:31-32, 207-216`
**What breaks:** `_last_api_failure_alert_time` is a module-level global, not shared across processes. Five LaunchAgent-managed scanners (exp400/401/503/600/1220) all suppressing independently → if Alpaca paper API goes down, operator receives 5 alerts in 1 second, then nothing for 5 minutes.
**Safety net:** Partial — at least one alert gets through per process. But no global deduplication.
**Recovery:** Persist cooldown timestamp to a file (e.g. `data/.alert_cooldown.json`).

---

### HIGH-M11 — Reconciler creates "unmanaged" orphan records but never closes or deletes them
**Where:** Observed in `logs/paper_exp401.log:2026-03-27` — 16 orphan WARNINGs survive across cycles and across deploys; `shared/reconciler.py` `orphans_detected` counter only increments; no remediation path
**What breaks:** Orphans accumulate indefinitely. After two months they are still listed by `_startup_reconciliation` (`execution/position_monitor.py:298-306`). Operator alert fatigue → real orphans get missed.
**Safety net:** Logs warning every startup.
**Recovery:** Either auto-close orphans (with a configurable max-loss cap) or sweep them into a `requires_manual_review` table that's surfaced on the dashboard with a count.

---

### HIGH-M12 — `_startup_reconciliation` swallows API errors with `return` — no alert
**Where:** `execution/position_monitor.py:259-266`
**What breaks:** If Alpaca is down at scanner launch, `get_positions()` raises → method returns without logging the connect issue at WARN+ severity that fires a Telegram alert. Scanner enters its 60s loop and may immediately handle pending opens / closes against a stale view.
**Safety net:** Logs `warning`, no Telegram.
**Recovery:** Call `notify_api_failure` here too.

---

### HIGH-M13 — Tier 2 reconciliation requires market hours; weekend-deployed scanners do nothing until Monday
**Where:** `execution/position_monitor.py:434-450`
**What breaks:** If positions are opened Friday and the operator restarts the process Saturday/Sunday, Tier 1 and Tier 2 reconciliation are skipped entirely. If a stop-loss should have triggered overnight on a holiday (rare but possible via after-hours equity moves and ex-dividend), no exit is queued.
**Safety net:** EOD/morning Tier 3 runs at 16:15 ET / 9:35 ET — but only on weekdays.
**Recovery:** Documented as intended (matches backtester). Not a code bug but worth listing as a coverage gap.

---

### HIGH-M14 — Heartbeat written only by SCAN slots, not by PositionMonitor cycles
**Where:** `main.py:1181-1191` — heartbeat is written after macro/retrain/scan but not by the background `PositionMonitor` thread
**What breaks:** If the ScanScheduler stops scheduling SCAN slots (e.g. after the last scan of the day at 15:55) but the PositionMonitor keeps running, the heartbeat ages. The watchdog will fire "scanner stale" 45 min after the last scan even though the process is healthy.
**Safety net:** None; the stale alert is a false positive.
**Recovery:** Have PositionMonitor write its own heartbeat (e.g. `.last_monitor_<exp_id>`).

---

## MEDIUM Failure Modes

### MED-M15 — `_write_heartbeat` silently swallows write errors
**Where:** `main.py:1119-1120` — `logger.warning(...)` only.
**Impact:** If `data/` is read-only or missing, the heartbeat is never updated → watchdog declares scanner stale → false positive.

### MED-M16 — Telegram alerts never raise, even on send failure
**Where:** `shared/telegram_alerts.py:46-75`
**Impact:** If Telegram is down, every alert returns False silently. Operator has no in-band way to know they've stopped receiving alerts. No secondary channel (email, PagerDuty).
**Recovery:** Add a counter / dead-letter file for failed sends; surface on dashboard.

### MED-M17 — `restart_tmux_session` ignores ThrottleInterval analogue — no exponential backoff
**Where:** `scripts/watchdog.py:83-115`
**Impact:** A scanner that fails to start (missing config file) gets restarted every 30 min indefinitely, each restart firing a Telegram alert. After 24 h, 48 spam alerts.

### MED-M18 — `_detect_orphans` runs unconditionally even when `open_positions` is empty
**Where:** `execution/position_monitor.py:498-507`
**Impact:** Correct behaviour but generates warning per orphan per cycle (every 5 minutes during market hours = 78 lines/day per orphan). Log volume swamps real signal.

### MED-M19 — `_strategy_registry` populated by `register_strategies(system.unified_strategies)` — if `unified_strategies` is empty, `manage_position()` is never dispatched and positions only exit on the legacy DTE/PT/SL fallback
**Where:** `execution/position_monitor.py:312-321`, `main.py:1204`
**Impact:** Strategy-specific exit logic (event_exit, signal_exit) is silently disabled. No warning that registry is empty.

### MED-M20 — `_TIER2_INTERVAL_SECONDS = 300` is hardcoded, not configurable per experiment
**Impact:** Fast-moving 0DTE experiments cannot reduce reconciliation latency.

---

## LOW Failure Modes

### LOW-M21 — Holiday calendar hardcoded only through 2030
**Where:** `execution/position_monitor.py:68-148`
**Impact:** From 2031-01-01 the system assumes every weekday is a trading day.

### LOW-M22 — `ET = timezone(timedelta(hours=-4))` is a string-constant style hack instead of `ZoneInfo("America/New_York")`
**Where:** `scripts/watchdog.py:41` — already covered by CRIT-M3 but worth a standalone fix.

### LOW-M23 — `restart_tmux_session` passes config_file, env_file, db_path unquoted into a shell command
**Where:** `scripts/watchdog.py:94-99` — `cmd = f"cd {project_dir} && ..."`. Registry-controlled values are trusted; not user input. Still, command injection risk if registry.json is ever fed from an untrusted source.

### LOW-M24 — `notify_api_failure` cooldown shares the global with all API contexts
**Impact:** A `get_positions` failure suppresses a subsequent `submit_close` failure alert. Different contexts should track independent cooldowns.

---

## Summary Table

| ID | Severity | Failure | Safety Net? |
|---|---|---|---|
| CRIT-M1 | CRITICAL | Watchdog auto-restarts via tmux, conflicts with LaunchAgent → duplicate orders | None |
| CRIT-M2 | CRITICAL | env_file in registry ≠ env_file on disk → Alpaca check always False | None |
| CRIT-M3 | CRITICAL | Watchdog hardcoded EDT offset; DST wrong half the year | None |
| CRIT-M4 | CRITICAL | Heartbeat filename derives wrong exp_id ("champion" ≠ "EXP-400") | None |
| CRIT-M5 | CRITICAL | Watchdog has no scheduler — never runs | None |
| CRIT-M6 | CRITICAL | Telegram bot token committed in source code | None |
| HIGH-M7 | HIGH | PositionMonitor silently skipped if alpaca_provider is None | Log line only |
| HIGH-M8 | HIGH | Monitor loop swallows all exceptions; no error-count alert | Log line only |
| HIGH-M9 | HIGH | API failure counter resets on each success → flapping never alerts | None |
| HIGH-M10 | HIGH | Per-process cooldown → no global Telegram dedupe | Partial |
| HIGH-M11 | HIGH | Orphans accumulate; no remediation path | Log warning |
| HIGH-M12 | HIGH | Startup reconcile swallows API errors | Log warning |
| HIGH-M13 | HIGH | Weekend/holiday restart skips Tier 1/2 reconciliation | Tier 3 weekdays only |
| HIGH-M14 | HIGH | Heartbeat only on SCAN slots; quiet PositionMonitor → false stale | None |
| MED-M15 | MEDIUM | Heartbeat write errors swallowed | Log warning |
| MED-M16 | MEDIUM | Telegram failures silent — no dead-letter | None |
| MED-M17 | MEDIUM | Restart loop with no backoff → alert spam | None |
| MED-M18 | MEDIUM | Orphan re-warning every 5 min per cycle | None |
| MED-M19 | MEDIUM | Empty strategy registry silently disables manage_position | None |
| MED-M20 | MEDIUM | TIER2 interval not per-experiment configurable | n/a |
| LOW-M21 | LOW | Holiday calendar stops in 2030 | n/a |
| LOW-M22 | LOW | Fixed-offset ET timezone | covered by CRIT-M3 |
| LOW-M23 | LOW | Shell f-string in restart_tmux_session (mild injection risk) | trusted source |
| LOW-M24 | LOW | API failure cooldown not per-context | n/a |

---

## Top-3 Pre-Monday Fixes

1. **Disable `scripts/watchdog.py` entirely until tmux assumption is fixed.** As-is it will spawn duplicate scanners alongside LaunchAgents → duplicate Alpaca orders → corrupt DB. (CRIT-M1)
2. **Rotate the Telegram bot token, remove the fallback literal in `scripts/watchdog_external.py`.** (CRIT-M6)
3. **Reconcile `registry.json` and `deploy/*.plist` so they reference the same env files / db_paths / exp_ids.** Currently exp400's plist sources `.env.champion`, but registry says `.env.exp400`; heartbeat will be written to `data/.last_scan_champion` while watchdog looks for `data/.last_scan_EXP-400`. Both monitoring paths will mis-fire until the IDs match. (CRIT-M2, CRIT-M4)
