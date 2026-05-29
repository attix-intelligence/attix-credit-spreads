# HANDOFF → cc1 — V8A Champion-disable + Railway flush schedule (2026-05-29)

**From:** cc (on-call). **Greenlit by Carlos.** **Hard deadline: deploy champion-disable BEFORE 09:30 ET** (now ~05:57 ET → ~3.5h runway). Market opens 09:30 ET.

---

## PART 1 — URGENT: deploy the Champion-disable (before 09:30 ET)

**What:** set `EXP-V8A` registry `status: active → paused` so the worker stops spawning the V8A
scanner (`manager.active()` filters `status=="active"`) — **no new Champion entries at 09:30**, and
no position-monitor interference with the manual flush.

**Patch (clean, off `origin/main` @ a894677, 1 file, +3/−2):**
`/Users/charlesbot/v8a_flush/champion_disable_EXPV8A.patch`

```bash
cd <attix-credit-spreads>            # your branch off latest main
git apply /Users/charlesbot/v8a_flush/champion_disable_EXPV8A.patch
python3 -c "import json;print(json.load(open('experiments/registry.json'))['experiments']['EXP-V8A']['status'])"  # -> paused
# commit + merge + let Railway deploy; CONFIRM the deploy lands before 09:30 ET
```
(Only EXP-V8A changes; the other 8 stay active. If context drifts, the edit is trivial: in the
`EXP-V8A` block set `"status": "paused"` and add `"last_stopped_at"`.)

**Verify deploy reached the live worker** (cc will also check): on
`https://attix-production.up.railway.app/api/v1/health` → `experiments_active` drops 9→8 and
`EXP-V8A` leaves `live_ids`; or `/api/v1/experiments` (X-API-Key) shows V8A `status:paused`.
Ground truth: **no V8A Champion entry fires at 09:30:02**.

---

## PART 2 — Railway flush schedule on attix-worker (Mac cron is OUT)

**Script (Railway-portable, drop into repo e.g. `scripts/v8a_flush.py`):**
`/Users/charlesbot/v8a_flush/railway/v8a_flush.py` — env-based creds (`ALPACA_API_KEY_EXPV8A`/
`..._SECRET_EXPV8A`, already on the worker per health check), repo-relative paths, audit log to
`$RAILWAY_VOLUME_MOUNT_PATH/v8a_flush_audit.log`, Telegram from worker env.

**Schedule as ONE-SHOT jobs today (2026-05-29, EDT = UTC−4) — NOT recurring:**

| ET | UTC | Job | Notes |
|---|---|---|---|
| 09:33 | 13:33 | `FLUSH_LIVE=1 python scripts/v8a_flush.py close` | cancels orders + closes the 735/723 ×32 spread (marketable limit). Idempotent. **Omit `FLUSH_LIVE=1` and it's a dry-run.** |
| 09:35 | 13:35 | `python scripts/v8a_flush.py verify` | exit 1 + pages if not flat |
| 09:40 | 13:40 | `python scripts/v8a_flush.py flip-guard && <PR-E flip cmd>` | guard exits 0=GO / 1=HALT. **Only on GO** apply the flip |

- The flush jobs run **independently of V8A's paused status** (they're scheduler entries hitting Alpaca directly, not the per-exp scanner).
- **One-shot only** — if your scheduler is recurring (Railway native cron), guard each job to run only on 2026-05-29 (or remove after firing) so it doesn't re-flush daily.

**The flip (09:40) — needs YOUR PR-E wiring:** `flip-guard` only GATES (flat + PR-E#78 merged +
prod healthy). On GO, you must apply the actual cutover, which is PR-E's domain and requires:
1. `dry_run:false` (the VRP toggle PR-E added), **and**
2. **re-activate V8A** registry `status: paused → active` (we paused it in Part 1), **and**
3. worker restart/redeploy so it spawns V8A running VRP.
Please confirm the exact `dry_run:false` toggle + that re-activation is in your flip command.

---

## Blockers / confirmations needed from cc1
1. **Telegram env on attix-worker** — `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are **empty locally**. Halt/fail paging only works if they're set on the worker. **Confirm they're set on attix-worker**, else the safety pages are silent.
2. **PR-E #78 deployed** — merged 03:09 UTC; confirm Railway actually deployed it (health exposes no SHA).
3. **PR #66 (fills-based reconciler) still OPEN** — close-fill PnL attribution deferred; flag for follow-up (records cleanup).
4. Confirm the worker DB / equity_history "Champion-era end" marker is written server-side post-flush (local checkout can't write the Railway volume DB).

## cc side (done / standing by)
- ✅ Patch generated + validated. ✅ Portable script written + (about to) dry-run validated.
- ✅ No local cron/launchd/at armed for V8A (verified: empty crontab; only `com.attix.sync-dashboard` launchd job, unrelated).
- ⏳ Standing by to verify: (a) V8A `status:paused` live on worker post-deploy, (b) Railway schedule live, (c) 09:33/09:35/09:40 execution.
